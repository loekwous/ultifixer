import os
import zipfile

import pytest

from conftest import PRIVATE, read_stl
from Ultifixer.project_settings import read_3mf_settings
from Ultifixer.vase_settings import make_plan
from Ultifixer.vase_shape import analyse_mesh, has_name_hint


# ------------------------------------------------------------------ 3MF settings

def test_bambu_vase_mode_is_read(fixtures_dir):
    found = read_3mf_settings(os.path.join(fixtures_dir, "bambu_vase.3mf"))
    assert found.slicer == "bambu"
    assert found.spiral_mode is True
    assert found.outer_wall_width == 1.0
    assert found.bottom_layers == 5
    assert found.bottom_thickness == 1.0
    assert found.smooth is True


def test_bambu_without_vase_mode(fixtures_dir):
    found = read_3mf_settings(os.path.join(fixtures_dir, "bambu_not_vase.3mf"))
    assert found.slicer == "bambu"
    assert found.spiral_mode is False


def test_prusa_vase_mode_is_read(fixtures_dir):
    found = read_3mf_settings(os.path.join(fixtures_dir, "prusa_vase.3mf"))
    assert found.slicer == "prusa"
    assert found.spiral_mode is True
    assert found.outer_wall_width == 0.6
    assert found.bottom_layers == 4


def test_plain_3mf_has_no_slicer_settings(fixtures_dir):
    found = read_3mf_settings(os.path.join(fixtures_dir, "plain_vase.3mf"))
    assert found.slicer == ""
    assert found.spiral_mode is False


def test_broken_files_never_raise(tmp_path):
    assert read_3mf_settings(str(tmp_path / "missing.3mf")).spiral_mode is False
    not_zip = tmp_path / "not_a_zip.3mf"
    not_zip.write_bytes(b"hello")
    assert read_3mf_settings(str(not_zip)).spiral_mode is False
    bad_json = tmp_path / "bad.3mf"
    with zipfile.ZipFile(bad_json, "w") as archive:
        archive.writestr("Metadata/project_settings.config", "{not json")
    assert read_3mf_settings(str(bad_json)).spiral_mode is False


def test_plate_override_in_model_settings(tmp_path):
    path = tmp_path / "plate.3mf"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/project_settings.config", '{"spiral_mode": "0"}')
        archive.writestr("Metadata/model_settings.config",
                         '<config><plate><metadata key="spiral_mode" value="1"/></plate></config>')
    assert read_3mf_settings(str(path)).spiral_mode is True


# ------------------------------------------------------------------ shape

VASES = ["model_a.stl", "ribbed_pillar.stl", "Cylinder_vase.stl"]
NOT_VASES = ["hollow_cup.stl", "ball.stl", "block.stl", "cylinder.stl"]


@pytest.mark.parametrize("name", VASES)
def test_solid_vases_are_recognised(fixtures_dir, name):
    path = os.path.join(fixtures_dir, name)
    report = analyse_mesh(read_stl(path), None, up=2, file_name=path)
    assert report.single_outline, report.summary()
    assert report.looks_like_vase, report.summary()


@pytest.mark.parametrize("name", NOT_VASES)
def test_other_models_are_left_alone(fixtures_dir, name):
    path = os.path.join(fixtures_dir, name)
    report = analyse_mesh(read_stl(path), None, up=2, file_name=path)
    assert not report.looks_like_vase, report.summary()


def test_hollow_cup_is_not_single_outline(fixtures_dir):
    report = analyse_mesh(read_stl(os.path.join(fixtures_dir, "hollow_cup.stl")), None, up=2)
    assert not report.single_outline


def test_up_axis_matters_cura_uses_y(fixtures_dir):
    vertices = read_stl(os.path.join(fixtures_dir, "model_a.stl"))[:, [0, 2, 1]]  # Z-up -> Y-up
    assert analyse_mesh(vertices, None, up=1).looks_like_vase


def test_name_hints():
    assert has_name_hint("C:/Downloads/Spiral Vase v2.stl")
    assert has_name_hint("bloempot.stl")
    assert has_name_hint("Vaas_klein.3mf")
    assert not has_name_hint("bracket.stl")


@pytest.mark.skipif(not os.path.isdir(PRIVATE), reason="private MakerWorld files not present")
def test_private_makerworld_stl_files():
    for name in os.listdir(PRIVATE):
        if name.lower().endswith(".stl"):
            path = os.path.join(PRIVATE, name)
            report = analyse_mesh(read_stl(path), None, up=2, file_name=path)
            assert report.looks_like_vase, (name, report.summary())


@pytest.mark.skipif(not os.path.isdir(PRIVATE), reason="private MakerWorld files not present")
def test_private_makerworld_3mf_files():
    # Stratos Pillar is a vase-mode 3MF. VASO_CALLE is not: it is hollowed by a Bambu negative part (see HANDOFF.md).
    for name in os.listdir(PRIVATE):
        if name.lower().startswith("stratos") and name.lower().endswith(".3mf"):
            assert read_3mf_settings(os.path.join(PRIVATE, name)).spiral_mode, name


# ------------------------------------------------------------------ settings

def test_plan_caps_wall_to_nozzle():
    source = read_3mf_settings.__globals__["VaseSourceSettings"](spiral_mode=True, outer_wall_width=1.0,
                                                                   bottom_layers=5, layer_height=0.2)
    plan = make_plan(source, 0.4)
    assert plan.global_settings["magic_spiralize"] is True
    assert plan.extruder_settings["wall_line_width_0"] == 0.6
    assert plan.extruder_settings["wall_thickness"] == 0.6
    assert plan.extruder_settings["bottom_thickness"] == 1.0
    assert plan.extruder_settings["infill_sparse_density"] == 0
    assert plan.describe() == "wand 0,6 mm, bodem 1 mm"


def test_plan_follows_nozzle_size():
    assert make_plan(None, 0.8).wall_width == 1.2
    assert make_plan(None, 0.25).wall_width == 0.38
    assert make_plan(None, 0).wall_width == 0.6  # unknown nozzle -> assume 0.4


def test_plan_keeps_narrow_source_width():
    source = read_3mf_settings.__globals__["VaseSourceSettings"](outer_wall_width=0.45)
    assert make_plan(source, 0.4).wall_width == 0.45


# ------------------------------------------------------------------ Bambu negative parts

def test_negative_part_is_read(fixtures_dir):
    from Ultifixer.project_settings import read_negative_parts
    path = os.path.join(fixtures_dir, "bambu_negative_part.3mf")
    found = read_3mf_settings(path)
    assert found.spiral_mode is False
    assert found.parts == {"3": ["normal_part", "negative_part"]}
    assert found.has_negative_parts
    shapes = read_negative_parts(path, found)
    assert list(shapes) == ["3"] and len(shapes["3"].holes) == 1
    assert shapes["3"].anchor.shape == (3, 3)
    triangles = shapes["3"].holes[0]
    assert triangles.shape[1:] == (3, 3)
    low, high = triangles.reshape(-1, 3).min(axis=0), triangles.reshape(-1, 3).max(axis=0)
    assert low == pytest.approx([-20, -20, 3], abs=0.01) and high == pytest.approx([20, 20, 85], abs=0.01)


def test_files_without_negative_parts(fixtures_dir):
    from Ultifixer.project_settings import read_negative_parts
    for name in ("bambu_vase.3mf", "plain_vase.3mf", "prusa_vase.3mf"):
        path = os.path.join(fixtures_dir, name)
        found = read_3mf_settings(path)
        assert not found.has_negative_parts
        assert read_negative_parts(path, found) == {}


def test_part_settings():
    from Ultifixer.vase_settings import part_settings
    assert part_settings("normal_part") is None
    hole = part_settings("negative_part")
    assert hole["cutting_mesh"] is True and hole["wall_line_count"] == 0 and hole["infill_sparse_density"] == 0
    assert part_settings("support_blocker") == {"anti_overhang_mesh": True}
    assert part_settings("modifier_part")["infill_mesh"] is True


def test_gap_ribs_is_a_vase(fixtures_dir):
    path = os.path.join(fixtures_dir, "gap_ribs.stl")
    assert analyse_mesh(read_stl(path), None, up=2, file_name=path).looks_like_vase


@pytest.mark.skipif(not os.path.exists(os.path.join(PRIVATE, "VASO_CALLE.3mf")), reason="private file not present")
def test_private_calla_vase_has_a_negative_part():
    from Ultifixer.project_settings import read_negative_parts
    path = os.path.join(PRIVATE, "VASO_CALLE.3mf")
    found = read_3mf_settings(path)
    assert found.has_negative_parts and not found.spiral_mode
    shapes = read_negative_parts(path, found)
    assert sum(len(v.holes) for v in shapes.values()) == 1


def test_plan_keeps_small_outlines():
    # Rib bodies of "Make My Vase" models are only ~8 mm around; dropping small outlines loses the ribs.
    plan = make_plan(None, 0.4)
    assert "minimum_polygon_circumference" not in plan.global_settings
    assert "minimum_polygon_circumference" not in plan.extruder_settings
