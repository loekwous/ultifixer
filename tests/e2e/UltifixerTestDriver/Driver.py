"""Scripted end-to-end run inside a real Cura. See tests/e2e/run_e2e.py for the plan format."""

import json
import os
import time
import traceback

from PyQt6.QtCore import QObject, QTimer, QUrl

from UM.Extension import Extension
from UM.Logger import Logger
from UM.PluginRegistry import PluginRegistry

from cura.CuraApplication import CuraApplication

READ_KEYS_GLOBAL = ["magic_spiralize", "smooth_spiralized_contours"]
READ_KEYS_EXTRUDER = ["wall_line_width_0", "wall_line_count", "wall_thickness", "infill_sparse_density",
                      "bottom_layers", "top_layers", "machine_nozzle_size", "layer_height"]


class Driver(QObject, Extension):
    def __init__(self, parent=None) -> None:
        QObject.__init__(self, parent)
        Extension.__init__(self)
        self._app = CuraApplication.getInstance()
        plan_path = os.environ.get("ULTIFIXER_E2E_PLAN")
        self._out = os.environ.get("ULTIFIXER_E2E_OUT", "")
        if not plan_path:
            return
        with open(plan_path, encoding="utf-8") as handle:
            self._plan = json.load(handle)
        self._results = {"plan": self._plan.get("mode"), "errors": [], "scenarios": []}
        self._backend_state = None
        self._files_done = []
        self._script = None
        self._waiting = None
        self._deadline = 0.0
        self._timer = QTimer()
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._boot = QTimer()
        self._boot.setInterval(1000)
        self._boot.timeout.connect(self._waitForWindow)
        self._boot.start()

    def _waitForWindow(self) -> None:
        if self._app.getMainWindow() is None or not self._app.started:
            return
        self._boot.stop()
        QTimer.singleShot(3000, self._start)

    # ------------------------------------------------------------ runner

    def _start(self) -> None:
        Logger.log("i", "UltifixerTestDriver: starting plan %s", self._plan.get("mode"))
        self._app.fileCompleted.connect(self._files_done.append)
        self._script = self._steps()
        self._advance(None)
        self._timer.start()

    def _advance(self, value) -> None:
        try:
            self._waiting = self._script.send(value)
            if self._waiting is not None:
                self._deadline = time.time() + self._waiting[1]
        except StopIteration:
            self._waiting = None
            self._finish()
        except Exception:
            self._results["errors"].append(traceback.format_exc())
            self._waiting = None
            self._finish()

    def _tick(self) -> None:
        if self._waiting is None:
            return
        condition, _timeout, label = self._waiting
        try:
            ok = condition()
        except Exception:
            ok = False
        if ok:
            self._advance(True)
        elif time.time() > self._deadline:
            self._results["errors"].append("timeout waiting for %s" % label)
            self._advance(False)

    def _wait(self, condition, timeout, label):
        return (condition, timeout, label)

    def _finish(self) -> None:
        self._timer.stop()
        os.makedirs(self._out, exist_ok=True)
        with open(os.path.join(self._out, "results.json"), "w", encoding="utf-8") as handle:
            json.dump(self._results, handle, indent=2, default=str)
        Logger.log("i", "UltifixerTestDriver: done, %d errors", len(self._results["errors"]))
        QTimer.singleShot(500, lambda: os._exit(0))

    # ------------------------------------------------------------- helpers

    def _ultifixer(self):
        return PluginRegistry.getInstance().getPluginObject("Ultifixer")

    def _settings(self) -> dict:
        stack = self._app.getGlobalContainerStack()
        values = {key: stack.getProperty(key, "value") for key in READ_KEYS_GLOBAL}
        extruder = stack.extruderList[0]
        for key in READ_KEYS_EXTRUDER:
            values[key] = extruder.getProperty(key, "value")
        return values

    def _reset(self) -> None:
        self._app.deleteAll()
        stack = self._app.getGlobalContainerStack()
        for container in [stack.userChanges] + [e.userChanges for e in stack.extruderList]:
            container.clear()
        fixer = self._ultifixer()
        if fixer is not None:
            fixer._saved_values = []
            fixer._vase_nodes = []

    def _screenshot(self, name: str) -> str:
        folder = os.path.join(self._out, "screenshots")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name + ".png")
        window = self._app.getMainWindow()
        if window is not None:
            window.grabWindow().save(path)
        return path

    def _onBackendState(self, state) -> None:
        self._backend_state = int(state)

    # --------------------------------------------------------------- plans

    def _steps(self):
        stack_ready = lambda: self._app.getGlobalContainerStack() is not None
        if not stack_ready():
            self._app.getMachineManager().addMachine("ultimaker_s3")
        yield self._wait(stack_ready, 60, "printer")

        registry = PluginRegistry.getInstance()
        self._results["cura_version"] = self._app.getVersion()
        self._results["sdk_version"] = str(self._app.getAPIVersion())
        self._results["ultifixer_active"] = "Ultifixer" in registry.getActivePlugins()
        meta = registry.getMetaData("Ultifixer") or {}
        self._results["ultifixer_version"] = meta.get("plugin", {}).get("version")
        self._results["ultifixer_path"] = registry.getPluginPath("Ultifixer")

        if self._plan.get("mode") == "install":
            package_id = self._app.getPackageManager().installPackage(self._plan["package"])
            self._results["installed_package_id"] = package_id
            return

        backend = self._app.getBackend()
        backend.backendStateChange.connect(self._onBackendState)
        self._app.getPreferences().setValue("general/auto_slice", False)

        for scenario in self._plan.get("scenarios", []):
            result = {"name": scenario["name"], "file": scenario.get("file")}
            self._results["scenarios"].append(result)
            fixer = self._ultifixer()
            self._reset()
            yield self._wait(lambda: True, 1, "reset")
            self._app.getPreferences().setValue("ultifixer/auto_detect", scenario.get("auto", True))
            first_event = len(fixer.events) if fixer else 0
            self._files_done.clear()

            path = scenario["file"]
            self._app.readLocalFile(QUrl.fromLocalFile(path), "open_as_model")
            yield self._wait(lambda: path in self._files_done, 120, "load " + path)
            yield self._wait(lambda: fixer is None or fixer.busy == 0, 120, "analysis")
            yield self._wait(lambda: True, 1, "settle")
            result["events"] = fixer.events[first_event:] if fixer else []
            result["settings"] = self._settings()
            result["active"] = bool(fixer and fixer.isActive)

            for action in scenario.get("actions", []):
                if action == "menu_make_vase":
                    fixer.makeSelectionVase()
                elif action == "undo":
                    fixer.undoVaseMode()
                elif action == "delete_all":
                    self._app.deleteAll()
                elif action.startswith("screenshot:"):
                    yield self._wait(lambda: True, 2, "render")
                    result.setdefault("screenshots", []).append(self._screenshot(action.split(":", 1)[1]))
                    continue
                yield self._wait(lambda: True, 1, action)
                result.setdefault("after", []).append({"action": action, "settings": self._settings(),
                                                       "active": bool(fixer and fixer.isActive),
                                                       "events": fixer.events[first_event:] if fixer else []})

            if scenario.get("slice"):
                self._backend_state = None
                backend.forceSlice()
                yield self._wait(lambda: self._backend_state in (3, 4), 600, "slice " + scenario["name"])
                result["backend_state"] = self._backend_state
                if self._backend_state == 3:
                    gcode_path = os.path.join(self._out, scenario["name"] + ".gcode")
                    writer = registry.getPluginObject("GCodeWriter")
                    with open(gcode_path, "w", encoding="utf-8") as handle:
                        result["gcode_written"] = writer.write(handle, None)
                    result["gcode"] = gcode_path
                for shot in scenario.get("after_slice_screenshots", []):
                    if shot.startswith("preview:"):
                        self._app.getController().setActiveStage("PreviewStage")
                        yield self._wait(lambda: True, 6, "preview")
                        result.setdefault("screenshots", []).append(self._screenshot(shot.split(":", 1)[1]))
                        self._app.getController().setActiveStage("PrepareStage")
                        yield self._wait(lambda: True, 2, "prepare")
