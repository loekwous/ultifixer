"""Look inside Cura G-code: is the print a hollow spiral vase or a filled object?"""

import re
from dataclasses import dataclass, field
from typing import Dict, List

_LAYER = re.compile(r"^;LAYER:(-?\d+)")
_TYPE = re.compile(r"^;TYPE:([A-Z-]+)")
_Z = re.compile(r"\bZ(-?\d+(?:\.\d+)?)")
_AXES = re.compile(r"([XYE])(-?\d+(?:\.\d+)?)")
MAX_STRAIGHT_MM = 15.0


@dataclass
class GcodeSummary:
    layer_count: int = 0
    types_per_layer: Dict[int, set] = field(default_factory=dict)
    z_values_per_layer: Dict[int, set] = field(default_factory=dict)
    volume_used_mm3: float = 0.0
    runs_per_layer: Dict[int, int] = field(default_factory=dict)  # separate extrusion runs
    longest_move_per_layer: Dict[int, float] = field(default_factory=dict)  # longest single extruded move, mm
    header: Dict[str, str] = field(default_factory=dict)

    def middle_layers(self) -> List[int]:
        layers = sorted(l for l in self.types_per_layer if l >= 0)
        if len(layers) < 10:
            return layers
        return layers[len(layers) // 4: 3 * len(layers) // 4]

    def spiral_problems(self) -> List[str]:
        """Why this is not a clean spiral vase (empty list: it is one).

        Clean means: the middle layers only print the outer wall, Z rises within a layer,
        each layer is one unbroken extrusion (no jumps to separate islands) and there are
        no long straight extrusions cutting through the inside of the vase.
        """
        middle = self.middle_layers()
        if not middle:
            return ["no layers"]
        problems = []
        if not all(self.types_per_layer[l] <= {"WALL-OUTER"} and self.types_per_layer[l] for l in middle):
            problems.append("middle layers print more than the outer wall")
        if sum(1 for l in middle if len(self.z_values_per_layer.get(l, ())) > 3) < len(middle) * 0.8:
            problems.append("Z does not rise within layers")
        broken = [l for l in middle if self.runs_per_layer.get(l, 0) > 1]
        if len(broken) > len(middle) * 0.02:
            problems.append("%d of %d layers jump between separate outlines" % (len(broken), len(middle)))
        longest = max((self.longest_move_per_layer.get(l, 0.0) for l in middle), default=0.0)
        if longest > MAX_STRAIGHT_MM:
            problems.append("extruded line of %.0f mm cuts through the vase" % longest)
        return problems

    def is_spiral_vase(self) -> bool:
        return not self.spiral_problems()

    def has_infill_or_inner_walls(self) -> bool:
        middle = self.middle_layers()
        return any(self.types_per_layer[l] & {"FILL", "WALL-INNER", "SKIN"} for l in middle)


def summarise(path: str) -> GcodeSummary:
    summary = GcodeSummary()
    layer = None
    x = y = None
    e = 0.0
    in_run = False
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(";"):
                match = _LAYER.match(line)
                if match:
                    layer = int(match.group(1))
                    in_run = False
                    summary.types_per_layer.setdefault(layer, set())
                    summary.z_values_per_layer.setdefault(layer, set())
                    continue
                match = _TYPE.match(line)
                if match and layer is not None:
                    summary.types_per_layer[layer].add(match.group(1))
                    continue
                if ":" in line and layer is None:
                    key, _, value = line[1:].partition(":")
                    summary.header[key.strip()] = value.strip()
                if line.startswith(";LAYER_COUNT:"):
                    summary.layer_count = int(line.split(":")[1])
                continue
            if line.startswith("G1") or line.startswith("G0"):
                axes = {k: float(v) for k, v in _AXES.findall(line)}
                new_x, new_y = axes.get("X", x), axes.get("Y", y)
                extruding = line.startswith("G1") and "E" in axes and axes["E"] > e
                if "E" in axes:
                    e = axes["E"]
                if layer is not None:
                    match = _Z.search(line)
                    if match:
                        summary.z_values_per_layer[layer].add(match.group(1))
                    if x is not None and new_x is not None and y is not None and new_y is not None:
                        distance = ((new_x - x) ** 2 + (new_y - y) ** 2) ** 0.5
                        if extruding:
                            if not in_run:
                                summary.runs_per_layer[layer] = summary.runs_per_layer.get(layer, 0) + 1
                            in_run = True
                            if distance > summary.longest_move_per_layer.get(layer, 0.0):
                                summary.longest_move_per_layer[layer] = distance
                        elif distance > 0.01:
                            in_run = False
                x, y = new_x, new_y
    for key, value in summary.header.items():
        if key.endswith("MATERIAL.VOLUME_USED"):
            try:
                summary.volume_used_mm3 += float(value)
            except ValueError:
                pass
    return summary


def extrusion_inside(path: str, center_x: float, center_y: float, radius: float, z_low: float, z_high: float) -> float:
    """Millimetres of extrusion whose middle lies inside a vertical cylinder (a hole that must stay empty)."""
    x = y = z = None
    e = 0.0
    inside = 0.0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not (line.startswith("G1") or line.startswith("G0")):
                if line.startswith("G92"):
                    axes = {k: float(v) for k, v in _AXES.findall(line)}
                    e = axes.get("E", e)
                continue
            axes = {k: float(v) for k, v in _AXES.findall(line.split(";")[0])}
            match = _Z.search(line)
            if match:
                z = float(match.group(1))
            new_x, new_y = axes.get("X", x), axes.get("Y", y)
            extruding = "E" in axes and axes["E"] > e
            if "E" in axes:
                e = axes["E"]
            if extruding and None not in (x, y, z, new_x, new_y) and z_low <= z <= z_high:
                middle_x, middle_y = (x + new_x) / 2, (y + new_y) / 2
                if (middle_x - center_x) ** 2 + (middle_y - center_y) ** 2 < radius ** 2:
                    inside += ((new_x - x) ** 2 + (new_y - y) ** 2) ** 0.5
            x, y = new_x, new_y
    return inside
