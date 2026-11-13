"""Look inside Cura G-code: is the print a hollow spiral vase or a filled object?"""

import re
from dataclasses import dataclass, field
from typing import Dict, List

_LAYER = re.compile(r"^;LAYER:(-?\d+)")
_TYPE = re.compile(r"^;TYPE:([A-Z-]+)")
_Z = re.compile(r"\bZ(-?\d+(?:\.\d+)?)")


@dataclass
class GcodeSummary:
    layer_count: int = 0
    types_per_layer: Dict[int, set] = field(default_factory=dict)
    z_values_per_layer: Dict[int, set] = field(default_factory=dict)
    volume_used_mm3: float = 0.0
    header: Dict[str, str] = field(default_factory=dict)

    def middle_layers(self) -> List[int]:
        layers = sorted(l for l in self.types_per_layer if l >= 0)
        if len(layers) < 10:
            return layers
        return layers[len(layers) // 4: 3 * len(layers) // 4]

    def is_spiral_vase(self) -> bool:
        """Middle layers only print the outer wall, and Z rises within a layer (the spiral)."""
        middle = self.middle_layers()
        if not middle:
            return False
        only_outer = all(self.types_per_layer[l] <= {"WALL-OUTER"} and self.types_per_layer[l] for l in middle)
        rising = sum(1 for l in middle if len(self.z_values_per_layer.get(l, ())) > 3) >= len(middle) * 0.8
        return only_outer and rising

    def has_infill_or_inner_walls(self) -> bool:
        middle = self.middle_layers()
        return any(self.types_per_layer[l] & {"FILL", "WALL-INNER", "SKIN"} for l in middle)


def summarise(path: str) -> GcodeSummary:
    summary = GcodeSummary()
    layer = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(";"):
                match = _LAYER.match(line)
                if match:
                    layer = int(match.group(1))
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
            if layer is not None and (line.startswith("G1") or line.startswith("G0")):
                match = _Z.search(line)
                if match:
                    summary.z_values_per_layer[layer].add(match.group(1))
    for key, value in summary.header.items():
        if key.endswith("MATERIAL.VOLUME_USED"):
            try:
                summary.volume_used_mm3 += float(value)
            except ValueError:
                pass
    return summary
