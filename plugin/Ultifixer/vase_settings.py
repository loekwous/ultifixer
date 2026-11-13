# Copyright (c) 2026 Loek Lankhorst. Released under the MIT license.
"""Translate "print this as a vase" into Cura settings.

Cura's own vase mode is called "Spiralize Outer Contour" (``magic_spiralize``).
On top of that we pick a wall width that suits the nozzle, and a solid bottom.
No Cura imports, so this is testable on its own.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from .project_settings import VaseSourceSettings

DEFAULT_BOTTOM_MM = 1.0
MAX_WIDTH_FACTOR = 1.5  # a 0.4 mm nozzle prints walls up to 0.6 mm wide


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
        },
        extruder_settings={
            "wall_line_width_0": wall_width,
            "wall_thickness": wall_width,
            "infill_sparse_density": 0,
            "top_thickness": 0,
            "bottom_thickness": bottom,
        },
        wall_width=wall_width,
        bottom_thickness=bottom,
    )
