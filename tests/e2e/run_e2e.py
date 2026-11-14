#!/usr/bin/env python3
"""End-to-end test of Ultifixer inside a real UltiMaker Cura (Linux AppImage, under Xvfb).

1. Starts Cura with a test driver plugin that installs dist/Ultifixer.curapackage
   the same way dragging it onto the Cura window does, then quits.
2. Starts Cura again (now Ultifixer is installed from the package) and runs the
   scenarios below: open a file, check what Ultifixer did, use the menu actions,
   slice with CuraEngine and check the G-code is really a hollow spiral vase.

Usage:
    python tests/e2e/run_e2e.py --cura /path/to/squashfs-root --package dist/Ultifixer.curapackage \
        --fixtures tests/fixtures/generated --out e2e-out/5.13 [--private tests/fixtures/private]

Exit code 0 when every check passes.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "plugin"))
from gcode_check import extrusion_inside, summarise  # noqa: E402
from Ultifixer.project_settings import read_3mf_settings  # noqa: E402

VASE = "vase"
NOT_VASE = "not_vase"


MAX_SHRINK_MM = 1.5  # a spiral runs half a wall width inside the model on each side


def scenarios(fixtures, private):
    f = lambda name: os.path.join(fixtures, name)
    plan = [
        # name, file, expectation, extra
        ("shape_stl", f("model_a.stl"), VASE, {"slice": True, "actions": ["screenshot:melding-vaas-herkend"],
                                                "after_slice_screenshots": ["preview:voorbeeld-holle-vaas"]}),
        ("bambu_3mf", f("bambu_vase.3mf"), VASE, {"slice": True}),
        ("bambu_3mf_vase_mode_off", f("bambu_not_vase.3mf"), NOT_VASE, {}),
        ("plain_3mf_by_shape", f("plain_vase.3mf"), VASE, {}),
        ("prusa_3mf", f("prusa_vase.3mf"), VASE, {}),
        ("multi_body_stl", f("ribbed_pillar.stl"), VASE, {"slice": True}),
        ("gap_ribs_stl", f("gap_ribs.stl"), VASE, {"slice": True}),
        ("bambu_negative_part", f("bambu_negative_part.3mf"), NOT_VASE, {"slice": True, "hole": "centered"}),
        ("hollow_cup_untouched", f("hollow_cup.stl"), NOT_VASE, {}),
        ("ball_untouched", f("ball.stl"), NOT_VASE, {}),
        ("block_untouched", f("block.stl"), NOT_VASE, {"slice": True}),
        ("name_hint_stl", f("Cylinder_vase.stl"), VASE, {}),
        ("menu_make_vase", f("cylinder.stl"), NOT_VASE, {"actions": ["menu_make_vase"], "expect_after": [True]}),
        ("undo_button", f("model_a.stl"), VASE, {"actions": ["undo"], "expect_after": [False]}),
        ("remove_restores", f("model_a.stl"), VASE, {"actions": ["delete_all"], "expect_after": [False]}),
        ("auto_off", f("model_a.stl"), NOT_VASE, {"auto": False, "actions": ["menu_make_vase"], "expect_after": [True]}),
    ]
    if private and os.path.isdir(private):
        for name in sorted(os.listdir(private)):
            if name.lower().endswith((".stl", ".3mf")):
                safe = re.sub(r"[^A-Za-z0-9]+", "_", os.path.splitext(name)[0]).strip("_").lower()
                path = os.path.join(private, name)
                source = read_3mf_settings(path) if name.lower().endswith(".3mf") else None
                if source is not None and source.slicer and not source.spiral_mode:
                    plan.append(("private_" + safe, path, NOT_VASE, {"slice": True, "hole": source.has_negative_parts}))
                else:
                    plan.append(("private_" + safe, path, VASE, {"slice": True}))
    return plan


def cura_version(cura_dir):
    text = open(os.path.join(cura_dir, "cura", "CuraVersion.py"), encoding="utf-8").read()
    full = re.search(r'CuraVersion = "([^"]+)"', text).group(1)
    return full, ".".join(full.split(".")[:2])


def run_cura(cura_dir, home, plan, out, timeout):
    os.makedirs(out, exist_ok=True)
    plan_path = os.path.join(out, "plan-%s.json" % plan["mode"])
    with open(plan_path, "w", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=2)
    results_path = os.path.join(out, "results.json")
    if os.path.exists(results_path):
        os.remove(results_path)
    env = dict(os.environ, HOME=home, ULTIFIXER_E2E_PLAN=plan_path, ULTIFIXER_E2E_OUT=out,
               XDG_CONFIG_HOME=os.path.join(home, ".config"), XDG_DATA_HOME=os.path.join(home, ".local", "share"),
               XDG_CACHE_HOME=os.path.join(home, ".cache"), LC_ALL="C.UTF-8", LANG="C.UTF-8")
    command = [os.path.join(cura_dir, "AppRun")]
    if not os.environ.get("DISPLAY"):
        command = ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24"] + command
    log_path = os.path.join(out, "cura-stdout-%s.log" % plan["mode"])
    with open(log_path, "w") as log:
        try:
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            pass
    for log_file in glob.glob(os.path.join(home, ".local", "share", "cura", "*", "cura.log")):
        shutil.copyfile(log_file, os.path.join(out, "cura-%s.log" % plan["mode"]))
    partial = os.path.join(out, "partial-results.json")
    if not os.path.exists(results_path) and os.path.exists(partial):
        shutil.copyfile(partial, results_path)
        with open(results_path, encoding="utf-8") as handle:
            data = json.load(handle)
        data.setdefault("errors", []).append("Cura did not finish in time; results are partial")
        with open(results_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    if not os.path.exists(results_path):
        raise SystemExit("Cura produced no results for plan %s; see %s" % (plan["mode"], log_path))
    with open(results_path, encoding="utf-8") as handle:
        results = json.load(handle)
    os.rename(results_path, os.path.join(out, "results-%s.json" % plan["mode"]))
    return results


def prepare_home(home, version_dir):
    config = os.path.join(home, ".config", "cura", version_dir)
    os.makedirs(config, exist_ok=True)
    with open(os.path.join(config, "cura.cfg"), "w", encoding="utf-8") as handle:
        handle.write("[general]\nversion = 7\naccepted_user_agreement = True\nauto_slice = False\n"
                     "[info]\nsend_slice_info = False\nsend_engine_crash = False\nasked_send_slice_info = True\nautomatic_update_check = False\n"
                     "automatic_plugin_update_check = False\n"
                     "[cura]\nchoice_on_open_project = open_as_model\nselect_models_on_load = True\n")
    plugins = os.path.join(home, ".local", "share", "cura", version_dir, "plugins", "UltifixerTestDriver")
    os.makedirs(plugins, exist_ok=True)
    target = os.path.join(plugins, "UltifixerTestDriver")
    if os.path.exists(target):
        shutil.rmtree(target)
    shutil.copytree(os.path.join(HERE, "UltifixerTestDriver"), target)


def check(results, plan):
    failures = []
    rows = []
    by_name = {s["name"]: s for s in results.get("scenarios", [])}
    if not results.get("ultifixer_active"):
        failures.append("Ultifixer plugin is not active in Cura (path: %s)" % results.get("ultifixer_path"))
    for name, path, expectation, extra in plan:
        scenario = by_name.get(name)
        notes = []
        if scenario is None:
            failures.append("%s: scenario did not run" % name)
            rows.append((name, "MISSING", ""))
            continue
        spiral = bool(scenario.get("settings", {}).get("magic_spiralize"))
        if expectation == VASE and not spiral:
            failures.append("%s: expected vase mode on, it is off; events=%s" % (name, scenario.get("events")))
        if expectation == NOT_VASE and spiral:
            failures.append("%s: expected vase mode off, it is on; events=%s" % (name, scenario.get("events")))
        if expectation == VASE and spiral:
            width = scenario["settings"].get("wall_line_width_0")
            nozzle = scenario["settings"].get("machine_nozzle_size")
            if not (nozzle and nozzle - 1e-6 <= width <= 1.5 * nozzle + 1e-6):
                failures.append("%s: wall width %s does not suit nozzle %s" % (name, width, nozzle))
            notes.append("wall %.2f mm, infill %s%%" % (width, scenario["settings"].get("infill_sparse_density")))
        for want, after in zip(extra.get("expect_after", []), scenario.get("after", [])):
            got = bool(after["settings"].get("magic_spiralize"))
            if got != want:
                failures.append("%s: after %s expected vase mode %s, got %s" % (name, after["action"], want, got))
            notes.append("after %s: %s" % (after["action"], "on" if got else "off"))
        if extra.get("slice"):
            gcode = scenario.get("gcode")
            if not gcode or not os.path.exists(gcode):
                failures.append("%s: slicing produced no G-code (backend state %s)" % (name, scenario.get("backend_state")))
            else:
                summary = summarise(gcode)
                if expectation == VASE and not summary.is_spiral_vase():
                    failures.append("%s: G-code is not a hollow spiral vase" % name)
                # The spiral must follow the whole model. Ribs that are separate bodies are easily lost,
                # which leaves a smooth vase that is narrower than the model.
                boxes = [n["box"] for n in scenario.get("nodes", []) if not n["group"] and n["box"]]
                if expectation == VASE and boxes:
                    model = (max(b[3] for b in boxes) - min(b[0] for b in boxes),
                             max(b[5] for b in boxes) - min(b[2] for b in boxes))
                    printed = summary.printed_size()
                    if min(printed[0] - model[0], printed[1] - model[1]) < -MAX_SHRINK_MM:
                        failures.append("%s: print is %.1f x %.1f mm, model is %.1f x %.1f mm (ribs or outer shape lost)"
                                        % (name, printed[0], printed[1], model[0], model[1]))
                    notes.append("print %.1f x %.1f mm of model %.1f x %.1f" % (printed + model))
                if expectation == NOT_VASE and not summary.has_infill_or_inner_walls():
                    failures.append("%s: G-code unexpectedly has no infill or inner walls" % name)
                if extra.get("hole"):
                    holes = scenario.get("holes") or []
                    if not holes:
                        failures.append("%s: the negative part was not turned into a hole" % name)
                    solid = [n["box"] for n in scenario.get("nodes", []) if not n["group"] and n["name"] != "Uitsparing" and n["box"]]
                    for hole in holes:
                        if extra.get("hole") == "centered" and solid:
                            left, _bottom, back, right, _top, front = solid[0]
                            middle = ((hole["box"][0] + hole["box"][3]) / 2, (hole["box"][2] + hole["box"][5]) / 2)
                            if abs(middle[0] - (left + right) / 2) > 0.5 or abs(middle[1] - (back + front) / 2) > 0.5:
                                failures.append("%s: the hole is not in the middle of the model" % name)
                            if abs(hole["z_low"] - 3.0) > 0.3:
                                failures.append("%s: the hole starts at %.1f mm, expected 3 mm" % (name, hole["z_low"]))
                        # Stay clear of the wall around the hole and of the layers at its bottom. A real
                        # hole need not be a cylinder, so there only its core is checked.
                        radius = hole["radius"] - 2.0 if extra.get("hole") == "centered" else hole["radius"] * 0.6
                        filled = extrusion_inside(gcode, hole["x"], hole["y"], radius,
                                                  hole["z_low"] + 1.0, hole["z_high"])
                        if filled > 1.0:
                            failures.append("%s: %.0f mm of plastic printed inside the hole" % (name, filled))
                        notes.append("hole r=%.0f mm from z=%.1f: %.0f mm plastic inside" % (hole["radius"], hole["z_low"], filled))
                    if extra.get("hole") == "centered" and solid and abs((solid[0][4] - solid[0][1]) - 80.0) > 0.2:
                        failures.append("%s: model is %.1f mm high, expected 80 (part scale not applied)"
                                        % (name, solid[0][4] - solid[0][1]))
                notes.append("G-code: %d layers, %s, %.1f cm3 filament" % (
                    summary.layer_count, "hollow spiral" if summary.is_spiral_vase() else "filled",
                    summary.volume_used_mm3 / 1000))
        rows.append((name, "vase mode on" if spiral else "vase mode off", "; ".join(notes)))
    return failures, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cura", required=True, help="extracted AppImage folder (squashfs-root)")
    parser.add_argument("--package", required=True)
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--private", default=os.path.join(HERE, "..", "fixtures", "private"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--only", default="", help="regular expression: run only the scenarios whose name matches")
    args = parser.parse_args()

    cura_dir = os.path.abspath(args.cura)
    out = os.path.abspath(args.out)
    full_version, version_dir = cura_version(cura_dir)
    os.makedirs(out, exist_ok=True)
    plan = scenarios(os.path.abspath(args.fixtures), os.path.abspath(args.private) if args.private else None)
    home = tempfile.mkdtemp(prefix="cura-home-", dir=out)
    prepare_home(home, version_dir)
    print("Cura %s, home %s" % (full_version, home), flush=True)

    install = run_cura(cura_dir, home, {"mode": "install", "package": os.path.abspath(args.package)}, out, 300)
    if install.get("installed_package_id") != "Ultifixer" or install.get("errors"):
        raise SystemExit("Installing the package failed: %s" % json.dumps(install, indent=2))
    print("Package scheduled for install, restarting Cura", flush=True)

    plan_json = {"mode": "scenarios", "scenarios": [
        dict({"name": name, "file": path}, **{k: v for k, v in extra.items() if k not in ("expect_after", "hole")})
        for name, path, _expectation, extra in plan if not args.only or re.search(args.only, name)]}
    plan = [row for row in plan if not args.only or re.search(args.only, row[0])]
    results = run_cura(cura_dir, home, plan_json, out, args.timeout)
    failures, rows = check(results, plan)
    failures = list(results.get("errors", [])) + failures

    lines = ["# Ultifixer end-to-end test, Cura %s (SDK %s, Ultifixer %s)" % (
        results.get("cura_version"), results.get("sdk_version"), results.get("ultifixer_version")), "",
        "| Scenario | Result | Details |", "|---|---|---|"]
    lines += ["| %s | %s | %s |" % row for row in rows]
    lines += ["", "**%s**" % ("All checks passed" if not failures else "%d failure(s)" % len(failures))]
    lines += ["- " + failure.replace("\n", " ") for failure in failures]
    report = "\n".join(lines)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as handle:
        handle.write(report + "\n")
    print(report)
    shutil.rmtree(home, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
