# Copyright (c) 2026 Loek Lankhorst. Released under the MIT license.
"""Guess from the shape alone whether a model is a "solid vase".

A vase made for spiral vase mode is a solid body: every horizontal cut through it
is one closed outline, with no holes. The slicer prints only that outline, which
makes the print hollow. This module cuts the mesh at a number of heights and
looks at those outlines.

It answers two questions:

* ``single_outline``: is every cut exactly one outline? Only then can vase mode
  print the model correctly. A model that is already hollow has two outlines per
  cut (inside and outside) and must not be printed in vase mode.
* ``looks_like_vase``: is it also shaped like a vase (flat base, open flat top,
  reasonably tall, a detailed mesh or a vase-like file name)?

Only numpy is used, so this runs inside Cura and in plain tests.
"""

import math
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy

MIN_HEIGHT_MM = 30.0
MIN_TRIANGLES_WITHOUT_NAME_HINT = 2000
SAMPLE_COUNT = 24

_NAME_HINT = re.compile(
    r"(vase|vaas|vaso|vasen|vasi|florero|planter|plantpot|flower[\s_-]?pot|bloempot|blumentopf|"
    r"lamp[\s_-]?shade|lampenkap|lampshade|spiral)",
    re.IGNORECASE,
)


@dataclass
class ShapeReport:
    triangles: int = 0
    height: float = 0.0
    footprint: float = 0.0  # largest horizontal size, mm
    outline_counts: List[int] = field(default_factory=list)  # parts + holes per cut; 1 = solid single body
    areas: List[float] = field(default_factory=list)  # filled area per cut, mm2
    open_edge_fraction: float = 0.0
    name_hint: bool = False
    single_outline: bool = False
    looks_like_vase: bool = False
    reasons: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return ("triangles=%d height=%.1f footprint=%.1f outlines=%s open_edges=%.4f name_hint=%s "
                "single_outline=%s looks_like_vase=%s reasons=%s" % (
                    self.triangles, self.height, self.footprint, sorted(set(self.outline_counts)),
                    self.open_edge_fraction, self.name_hint, self.single_outline, self.looks_like_vase,
                    "; ".join(self.reasons)))


def has_name_hint(file_name: str) -> bool:
    return bool(_NAME_HINT.search(os.path.basename(file_name or "")))


def _weld(vertices: numpy.ndarray, indices: Optional[numpy.ndarray]) -> Tuple[numpy.ndarray, numpy.ndarray]:
    """Return (unique vertices, faces) with shared corners merged."""
    vertices = numpy.asarray(vertices, dtype=numpy.float64)
    if indices is None:
        faces = numpy.arange(len(vertices) - len(vertices) % 3).reshape(-1, 3)
    else:
        faces = numpy.asarray(indices, dtype=numpy.int64).reshape(-1, 3)
    rounded = numpy.round(vertices / 1e-4).astype(numpy.int64)
    _, first_index, inverse = numpy.unique(rounded, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    welded = vertices[first_index]
    return welded, inverse[faces]


def _count_regions(mask: numpy.ndarray) -> Tuple[int, int]:
    """Count 4-connected regions of True cells: (all regions, regions touching the grid border).

    Works on horizontal runs per row with a small union-find, so it stays fast in
    plain Python (Cura's bundled Python has no scipy.ndimage).
    """
    rows, columns = mask.shape
    padded = numpy.zeros((rows, columns + 2), dtype=numpy.int8)
    padded[:, 1:-1] = mask
    changes = numpy.diff(padded, axis=1)
    run_rows, run_starts = numpy.nonzero(changes == 1)
    _, run_ends = numpy.nonzero(changes == -1)  # exclusive end; same order as starts
    count = len(run_starts)
    if count == 0:
        return 0, 0
    parent = list(range(count))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    row_first = numpy.searchsorted(run_rows, numpy.arange(rows + 1))
    for row in range(1, rows):
        a0, a1 = row_first[row - 1], row_first[row]
        b0, b1 = row_first[row], row_first[row + 1]
        i, j = a0, b0
        while i < a1 and j < b1:
            if run_starts[i] < run_ends[j] and run_starts[j] < run_ends[i]:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
            if run_ends[i] < run_ends[j]:
                i += 1
            else:
                j += 1
    roots = [find(i) for i in range(count)]
    border = (run_rows == 0) | (run_rows == rows - 1) | (run_starts == 0) | (run_ends == columns)
    border_roots = {roots[i] for i in numpy.nonzero(border)[0]}
    return len(set(roots)), len(border_roots)


def _cut(vertices: numpy.ndarray, faces: numpy.ndarray, normals: numpy.ndarray, up: int, height: float):
    """Cut at one height.

    Returns (filled parts, holes, filled area in mm2, open edge fraction). The cut is
    rasterised with the non-zero winding rule, so overlapping bodies merge into one
    part, just as Cura merges them ("union overlapping volumes").
    """
    plane = (1, 2) if up == 0 else ((0, 2) if up == 1 else (0, 1))
    side = vertices[:, up] > height
    face_side = side[faces]
    above = face_side.sum(axis=1)
    crossing = (above == 1) | (above == 2)
    if not numpy.any(crossing):
        return 0, 0, 0.0, 0.0
    cf = faces[crossing]
    cs = face_side[crossing]
    cn = normals[crossing]

    keys = []
    points = []
    vertex_count = len(vertices)
    for a, b in ((0, 1), (1, 2), (2, 0)):
        crosses = cs[:, a] != cs[:, b]
        lo = numpy.minimum(cf[:, a], cf[:, b])
        hi = numpy.maximum(cf[:, a], cf[:, b])
        keys.append(numpy.where(crosses, lo * vertex_count + hi, -1))
        pa = vertices[lo]
        pb = vertices[hi]
        denom = pb[:, up] - pa[:, up]
        denom[denom == 0] = 1e-12
        t = (height - pa[:, up]) / denom
        points.append(pa[:, plane] + (pb[:, plane] - pa[:, plane]) * t[:, None])
    keys = numpy.stack(keys, axis=1)
    points = numpy.stack(points, axis=1)
    valid = keys >= 0
    rows = valid.sum(axis=1) == 2
    keys, points, valid, cn = keys[rows], points[rows], valid[rows], cn[rows]
    order = numpy.argsort(~valid, axis=1, kind="stable")[:, :2]
    seg_keys = numpy.take_along_axis(keys, order, axis=1)
    seg = numpy.take_along_axis(points, order[:, :, None], axis=1)  # (n, 2 points, 2 coords)

    unique_keys, node_ids = numpy.unique(seg_keys.reshape(-1), return_inverse=True)
    degree = numpy.bincount(node_ids.reshape(-1), minlength=len(unique_keys))
    open_fraction = float(numpy.count_nonzero(degree != 2)) / max(1, len(unique_keys))

    # Orient every segment along (up x normal): outer outlines run one way, holes the other.
    n2 = cn[:, plane]
    # up x n, projected on the plane, is (-n_b, n_a) up to the handedness of `plane`; the sign
    # convention only has to be consistent, the non-zero rule does not care which way round.
    direction = numpy.stack([-n2[:, 1], n2[:, 0]], axis=1)
    flip = numpy.einsum("ij,ij->i", seg[:, 1] - seg[:, 0], direction) < 0
    seg[flip] = seg[flip][:, ::-1]

    mins = seg.reshape(-1, 2).min(axis=0)
    maxs = seg.reshape(-1, 2).max(axis=0)
    resolution = max(0.25, float(max(maxs - mins)) / 600.0)
    columns = int(math.ceil((maxs[0] - mins[0]) / resolution)) + 3
    row_count = int(math.ceil((maxs[1] - mins[1]) / resolution)) + 3
    origin = mins - resolution  # one empty cell of border all around

    x0, y0 = seg[:, 0, 0], seg[:, 0, 1]
    x1, y1 = seg[:, 1, 0], seg[:, 1, 1]
    sign = numpy.where(y1 > y0, 1, -1)
    y_low = numpy.minimum(y0, y1)
    y_high = numpy.maximum(y0, y1)
    first_row = numpy.ceil((y_low - origin[1]) / resolution - 0.5).astype(numpy.int64)
    last_row = numpy.ceil((y_high - origin[1]) / resolution - 0.5).astype(numpy.int64) - 1
    spans = numpy.maximum(0, last_row - first_row + 1)
    total = int(spans.sum())
    winding = numpy.zeros((row_count, columns + 1), dtype=numpy.int32)
    if total:
        seg_index = numpy.repeat(numpy.arange(len(seg)), spans)
        offsets = numpy.arange(total) - numpy.repeat(numpy.cumsum(spans) - spans, spans)
        row = first_row[seg_index] + offsets
        y_center = origin[1] + (row + 0.5) * resolution
        dy = (y1 - y0)[seg_index]
        t = (y_center - y0[seg_index]) / dy
        x_cross = x0[seg_index] + t * (x1 - x0)[seg_index]
        column = numpy.clip(numpy.ceil((x_cross - origin[0]) / resolution - 0.5).astype(numpy.int64), 0, columns)
        numpy.add.at(winding, (row, column), sign[seg_index])
    filled = numpy.cumsum(winding, axis=1)[:, :columns] != 0

    parts, _ = _count_regions(filled)
    empty_count, empty_on_border = _count_regions(~filled)
    holes = empty_count - empty_on_border
    area = float(numpy.count_nonzero(filled)) * resolution * resolution
    return parts, holes, area, open_fraction


def analyse_mesh(vertices, indices=None, up: int = 1, file_name: str = "") -> ShapeReport:
    """Analyse a mesh. ``vertices`` are world coordinates in mm; ``up`` is the vertical axis (Cura: 1)."""
    report = ShapeReport()
    report.name_hint = has_name_hint(file_name)
    vertices = numpy.asarray(vertices, dtype=numpy.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3:
        report.reasons.append("no usable mesh")
        return report

    welded, faces = _weld(vertices, indices)
    corners = welded[faces]
    normals = numpy.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    report.triangles = len(faces)
    low = welded[:, up].min()
    high = welded[:, up].max()
    report.height = float(high - low)
    horizontal = [axis for axis in range(3) if axis != up]
    report.footprint = float(max(numpy.ptp(welded[:, horizontal[0]]), numpy.ptp(welded[:, horizontal[1]])))
    if report.height < 1.0:
        report.reasons.append("flat model")
        return report

    # Cut heights as fractions of the height; the odd offset avoids hitting vertices exactly.
    fractions = list(numpy.linspace(0.03, 0.96, SAMPLE_COUNT - 1)) + [0.995]
    open_fractions = []
    for fraction in fractions:
        height = low + report.height * fraction + 1.234567e-4
        parts, holes, area, open_fraction = _cut(welded, faces, normals, up, height)
        report.outline_counts.append(parts + holes)
        report.areas.append(area)
        open_fractions.append(open_fraction)
    report.open_edge_fraction = max(open_fractions) if open_fractions else 1.0

    if report.open_edge_fraction > 0.03:
        report.reasons.append("mesh has holes")
        return report
    if any(count != 1 for count in report.outline_counts):
        report.reasons.append("not one outline at every height (already hollow, or several parts)")
        return report
    report.single_outline = True

    max_area = max(report.areas) or 1.0
    base_ratio = report.areas[0] / max_area
    top_ratio = report.areas[-1] / max_area
    top_flatness = report.areas[-1] / (report.areas[-2] or 1.0)
    tall = report.height >= 0.4 * report.footprint

    checks = [
        (report.height >= MIN_HEIGHT_MM, "lower than %d mm" % MIN_HEIGHT_MM),
        (base_ratio >= 0.1, "no flat base"),
        (top_ratio >= 0.05 and top_flatness >= 0.6, "top is closed or rounded, not an open rim"),
        (report.name_hint or (report.triangles >= MIN_TRIANGLES_WITHOUT_NAME_HINT and tall),
         "simple or wide shape without 'vase' in the file name"),
    ]
    failed = [reason for ok, reason in checks if not ok]
    report.reasons.extend(failed)
    report.looks_like_vase = not failed
    if report.looks_like_vase:
        report.reasons.append("solid vase shape" + (" (file name)" if report.name_hint else ""))
    return report
