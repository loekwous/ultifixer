# Copyright (c) 2026 Loek Lankhorst. Released under the MIT license.
"""Read the slicer settings that Bambu Studio, OrcaSlicer and PrusaSlicer store in a 3MF file.

Cura only reads the shape from these files. The setting that matters for vases,
"spiral vase mode", lives in a slicer-specific config file inside the 3MF zip:

* Bambu Studio / OrcaSlicer: ``Metadata/project_settings.config`` (JSON) with ``"spiral_mode": "1"``.
  Plate overrides can also appear in ``Metadata/model_settings.config`` (XML).
  The same XML says per object what each part is for: a ``negative_part`` is a shape that Bambu
  cuts out of the model (often the hole of a vase), a ``modifier_part`` only changes settings.
* PrusaSlicer / SuperSlicer: ``Metadata/Slic3r_PE.config`` (INI-like) with ``; spiral_vase = 1``.

This module has no Cura imports, so it can be tested on its own.
"""

import json
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy

MAX_CONFIG_BYTES = 8 * 1024 * 1024
MAX_MODEL_BYTES = 1024 * 1024 * 1024
MAX_PART_BYTES = 64 * 1024 * 1024
NORMAL_PART = "normal_part"
NEGATIVE_PART = "negative_part"


@dataclass
class VaseSourceSettings:
    """What the 3MF says about printing it as a vase."""

    spiral_mode: bool = False
    slicer: str = ""  # "bambu", "prusa" or "" when nothing was found
    outer_wall_width: Optional[float] = None  # mm
    bottom_layers: Optional[int] = None
    layer_height: Optional[float] = None  # mm
    smooth: Optional[bool] = None
    raw: Dict[str, str] = field(default_factory=dict)
    # Bambu object id -> what each of its parts is, in file order ("normal_part", "negative_part", ...).
    # Only objects that have a part that must not be printed as plain plastic are listed.
    parts: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def has_negative_parts(self) -> bool:
        return any(NEGATIVE_PART in kinds for kinds in self.parts.values())

    @property
    def bottom_thickness(self) -> Optional[float]:
        if self.bottom_layers is None or self.layer_height is None:
            return None
        return round(self.bottom_layers * self.layer_height, 3)


def _truthy(value) -> bool:
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _first(value) -> str:
    """Bambu stores per-extruder values as lists; take the first one."""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value)


def _float(value) -> Optional[float]:
    try:
        text = _first(value).strip().rstrip("%")
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _int(value) -> Optional[int]:
    number = _float(value)
    return int(round(number)) if number is not None else None


def _read_member(archive: zipfile.ZipFile, name: str) -> Optional[str]:
    lowered = {n.lower(): n for n in archive.namelist()}
    real_name = lowered.get(name.lower())
    if real_name is None:
        return None
    info = archive.getinfo(real_name)
    if info.file_size > MAX_CONFIG_BYTES:
        return None
    return archive.read(real_name).decode("utf-8", errors="replace")


def _parse_bambu(archive: zipfile.ZipFile) -> Optional[VaseSourceSettings]:
    text = _read_member(archive, "Metadata/project_settings.config")
    if text is None:
        return None
    try:
        config = json.loads(text)
    except ValueError:
        return None
    if not isinstance(config, dict):
        return None

    result = VaseSourceSettings(slicer="bambu")
    result.spiral_mode = _truthy(config.get("spiral_mode", "0"))
    result.outer_wall_width = _float(config.get("outer_wall_line_width")) or _float(config.get("line_width"))
    result.bottom_layers = _int(config.get("bottom_shell_layers"))
    result.layer_height = _float(config.get("layer_height"))
    if "spiral_mode_smooth" in config:
        result.smooth = _truthy(config.get("spiral_mode_smooth"))
    result.raw = {k: _first(config[k]) for k in ("spiral_mode", "outer_wall_line_width", "bottom_shell_layers",
                                                  "layer_height", "spiral_mode_smooth", "printer_model") if k in config}

    # A plate or object can override the project setting.
    model_text = _read_member(archive, "Metadata/model_settings.config")
    if model_text:
        try:
            root = ET.fromstring(model_text)
            for meta in root.iter("metadata"):
                if meta.get("key") == "spiral_mode":
                    result.spiral_mode = result.spiral_mode or _truthy(meta.get("value", "0"))
            for obj in root.iter("object"):
                kinds = [part.get("subtype") or NORMAL_PART for part in obj.findall("part")]
                if any(kind != NORMAL_PART for kind in kinds):
                    result.parts[str(obj.get("id", ""))] = kinds
        except ET.ParseError:
            pass
    return result


_PRUSA_LINE = re.compile(r"^\s*;\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")


def _parse_prusa(archive: zipfile.ZipFile) -> Optional[VaseSourceSettings]:
    text = _read_member(archive, "Metadata/Slic3r_PE.config")
    if text is None:
        return None
    config = {}
    for line in text.splitlines():
        match = _PRUSA_LINE.match(line)
        if match:
            config[match.group(1)] = match.group(2)
    result = VaseSourceSettings(slicer="prusa")
    result.spiral_mode = _truthy(config.get("spiral_vase", "0"))
    width = config.get("external_perimeter_extrusion_width", "")
    if width and not width.endswith("%"):
        result.outer_wall_width = _float(width) or None
    result.bottom_layers = _int(config.get("bottom_solid_layers"))
    result.layer_height = _float(config.get("layer_height"))
    result.raw = {k: config[k] for k in ("spiral_vase", "external_perimeter_extrusion_width",
                                         "bottom_solid_layers", "layer_height") if k in config}
    return result


def read_3mf_settings(path: str) -> VaseSourceSettings:
    """Return the vase-related slicer settings from a 3MF file.

    Never raises for a bad or unknown file: it then returns settings with ``spiral_mode=False``.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            for parser in (_parse_bambu, _parse_prusa):
                found = parser(archive)
                if found is not None:
                    return found
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError):
        pass
    return VaseSourceSettings()


_VERTEX = re.compile(rb'<vertex\s+x="([^"]+)"\s+y="([^"]+)"\s+z="([^"]+)"')
_TRIANGLE = re.compile(rb'<triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"')


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _object_mesh(model: bytes, object_id: str) -> Optional[Tuple[numpy.ndarray, numpy.ndarray]]:
    """Vertices and triangles of one <object> in a 3MF model file, without parsing the whole file."""
    start = re.search(rb'<object\b[^>]*\bid="%s"[^>]*>' % re.escape(object_id.encode()), model)
    if start is None:
        return None
    end = model.find(b"</object>", start.end())
    if end < 0 or end - start.end() > MAX_PART_BYTES:
        return None
    body = model[start.end():end]
    vertices = numpy.array(_VERTEX.findall(body), dtype=numpy.float64).reshape(-1, 3)
    faces = numpy.array(_TRIANGLE.findall(body), dtype=numpy.int64).reshape(-1, 3)
    if not len(vertices) or not len(faces) or faces.max() >= len(vertices):
        return None
    return vertices, faces


def _first_triangle(model: bytes, object_id: str) -> Optional[numpy.ndarray]:
    """The three corners of the first triangle of one <object>, as a (3, 3) array."""
    start = re.search(rb'<object\b[^>]*\bid="%s"[^>]*>' % re.escape(object_id.encode()), model)
    if start is None:
        return None
    end = model.find(b"</object>", start.end())
    triangle = _TRIANGLE.search(model, start.end(), end if end > 0 else len(model))
    if triangle is None:
        return None
    wanted = [int(i) for i in triangle.groups()]
    corners = {}
    for index, vertex in enumerate(_VERTEX.finditer(model, start.end(), triangle.start())):
        if index in wanted:
            corners[index] = [float(x) for x in vertex.groups()]
            if len(corners) == len(set(wanted)):
                break
    if len(corners) != len(set(wanted)):
        return None
    return numpy.array([corners[i] for i in wanted])


def _transform(component) -> numpy.ndarray:
    """A 3MF component transform as a (4, 3) array: three rows of rotation/scale, then the shift."""
    numbers = [float(x) for x in (component.get("transform") or "").split()]
    if len(numbers) != 12:
        numbers = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]
    return numpy.array(numbers).reshape(4, 3)


@dataclass
class NegativeParts:
    """The shapes Bambu Studio cuts out of one object, in the coordinates of that object."""

    holes: List[numpy.ndarray] = field(default_factory=list)  # each (n, 3, 3): triangles
    # First triangle of the first printed part, (3, 3). Cura shifts the mesh of an object when it
    # loads it; comparing this triangle with Cura's copy tells by how much.
    # Cura may or may not have applied the part's own transform, so the triangle is kept as it
    # is in the file, with that transform next to it.
    anchor: Optional[numpy.ndarray] = None
    anchor_matrix: Optional[numpy.ndarray] = None  # (4, 3): three rows of rotation/scale, then the shift


def read_negative_parts(path: str, source: VaseSourceSettings) -> Dict[str, NegativeParts]:
    """The shapes that Bambu Studio cuts out of each object, by object id.

    Cura's 3MF reader leaves these parts out, so the plugin has to add them itself.
    Never raises; an object it cannot read is left out.
    """
    found: Dict[str, NegativeParts] = {}
    if not source.has_negative_parts:
        return found
    try:
        with zipfile.ZipFile(path) as archive:
            names = {n.lower(): n for n in archive.namelist()}
            main = _read_member(archive, "3D/3dmodel.model")
            if main is None:
                return found
            models: Dict[str, bytes] = {}

            def model_of(component) -> Optional[bytes]:
                member = next((v for k, v in component.attrib.items() if _local(k) == "path"), "")
                real_name = names.get(member.lstrip("/").lower())
                if real_name is None or archive.getinfo(real_name).file_size > MAX_MODEL_BYTES:
                    return None
                if real_name not in models:
                    models[real_name] = archive.read(real_name)
                return models[real_name]

            for obj in ET.fromstring(main).iter():
                if _local(obj.tag) != "object" or str(obj.get("id")) not in source.parts:
                    continue
                kinds = source.parts[str(obj.get("id"))]
                components = [c for c in obj.iter() if _local(c.tag) == "component"]
                if len(components) != len(kinds):
                    continue
                parts = NegativeParts()
                for component, kind in zip(components, kinds):
                    model = model_of(component)
                    if model is None:
                        continue
                    matrix = _transform(component)
                    if kind == NORMAL_PART and parts.anchor is None:
                        corners = _first_triangle(model, str(component.get("objectid")))
                        if corners is not None:
                            parts.anchor = corners
                            parts.anchor_matrix = matrix
                    elif kind == NEGATIVE_PART:
                        mesh = _object_mesh(model, str(component.get("objectid")))
                        if mesh is not None:
                            vertices, faces = mesh
                            parts.holes.append((vertices @ matrix[:3] + matrix[3])[faces])
                if parts.holes and parts.anchor is not None:
                    found[str(obj.get("id"))] = parts
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, ValueError, ET.ParseError, MemoryError):
        pass
    return found
