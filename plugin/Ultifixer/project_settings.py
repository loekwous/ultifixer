# Copyright (c) 2026 Loek Lankhorst. Released under the MIT license.
"""Read the slicer settings that Bambu Studio, OrcaSlicer and PrusaSlicer store in a 3MF file.

Cura only reads the shape from these files. The setting that matters for vases,
"spiral vase mode", lives in a slicer-specific config file inside the 3MF zip:

* Bambu Studio / OrcaSlicer: ``Metadata/project_settings.config`` (JSON) with ``"spiral_mode": "1"``.
  Plate overrides can also appear in ``Metadata/model_settings.config`` (XML).
* PrusaSlicer / SuperSlicer: ``Metadata/Slic3r_PE.config`` (INI-like) with ``; spiral_vase = 1``.

This module has no Cura imports, so it can be tested on its own.
"""

import json
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Optional

MAX_CONFIG_BYTES = 8 * 1024 * 1024


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
