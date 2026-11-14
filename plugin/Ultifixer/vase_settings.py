# Copyright (c) 2026 Loek Lankhorst. Released under the MIT license.
"""Translate "print this as a vase" into Cura settings.

Cura's own vase mode is called "Spiralize Outer Contour" (``magic_spiralize``).
On top of that we pick a wall width that suits the nozzle, and a solid bottom.
No Cura imports, so this is testable on its own.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from .project_settings import NEGATIVE_PART, NORMAL_PART, VaseSourceSettings

DEFAULT_BOTTOM_MM = 1.0
MAX_WIDTH_FACTOR = 1.5  # a 0.4 mm nozzle prints walls up to 0.6 mm wide
MERGE_OFFSET_MM = 0.05
MIN_OUTLINE_MM = 20.0


@dataclass
class VasePlan:
    global_settings: Dict[str, object]
    extruder_settings: Dict[str, object]
    wall_width: float
    bottom_thickness: float

    def describe(self) -> str:
        return "wand %s mm, bodem %s mm" % (_nl(self.wall_width), _nl(self.bottom_thickness))


def _nl(number: float) -> str:
    """0.6 -> '0,6' (Dutch decimal comma)."""
    return ("%g" % round(number, 2)).replace(".", ",")


def make_plan(source: Optional[VaseSourceSettings], nozzle_size: float) -> VasePlan:
    nozzle = nozzle_size if nozzle_size and nozzle_size > 0 else 0.4
    widest = round(nozzle * MAX_WIDTH_FACTOR, 2)

    wanted_width = source.outer_wall_width if source and source.outer_wall_width else widest
    wall_width = round(min(max(wanted_width, nozzle), widest), 2)

    bottom = source.bottom_thickness if source and source.bottom_thickness else DEFAULT_BOTTOM_MM
    bottom = round(min(max(bottom, 0.4), 3.0), 2)

    smooth = source.smooth if source and source.smooth is not None else True

    return VasePlan(
        global_settings={
            "magic_spiralize": True,
            "smooth_spiralized_contours": smooth,
            # Drop tiny leftover outlines; in vase mode only the big outer outline matters.
            "minimum_polygon_circumference": MIN_OUTLINE_MM,
        },
        extruder_settings={
            "wall_line_width_0": wall_width,
            "wall_thickness": wall_width,
            "infill_sparse_density": 0,
            "top_thickness": 0,
            "bottom_thickness": bottom,
            # MakerWorld "Make My Vase" models are a core plus many rib bodies that almost touch.
            # Without a tiny outward offset Cura keeps the rib tips as separate islands and, in
            # vase mode, draws lines straight through the vase to reach them.
            "xy_offset": MERGE_OFFSET_MM,
        },
        wall_width=wall_width,
        bottom_thickness=bottom,
    )


# A part that prints nothing itself: no walls, no top or bottom, no infill.
_EMPTY = {"wall_line_count": 0, "top_layers": 0, "bottom_layers": 0, "initial_bottom_layers": 0}


def part_settings(kind: str) -> Optional[Dict[str, object]]:
    """Per-object Cura settings for one part of a Bambu object; None for a plain printed part.

    Cura loads every part as ordinary plastic. These settings give the part its Bambu meaning:

    * negative part: a "cutting mesh" that prints nothing. Cura removes its volume from the
      model and puts a wall around the hole, which is what Bambu Studio does.
    * support blocker: Cura's own support blocker.
    * modifier and support enforcer: Cura has no equal, so they only stop being printed
      (an "infill mesh" that changes nothing).
    """
    if kind == NORMAL_PART:
        return None
    if kind == NEGATIVE_PART:
        return dict(_EMPTY, cutting_mesh=True, infill_sparse_density=0)
    if kind == "support_blocker":
        return {"anti_overhang_mesh": True}
    return dict(_EMPTY, infill_mesh=True)
