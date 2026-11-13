#!/usr/bin/env python3
"""Generate the test models (no copyrighted MakerWorld files in this public repo).

Every model is a solid of revolution with optional ribs, built from a closed
profile, so the meshes are watertight with consistent normals.

    python tests/fixtures/make_fixtures.py [output dir]
"""

import json
import math
import os
import struct
import sys
import zipfile

import numpy

HERE = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------ meshes

def revolve(profile, segments=120, ribs=0, rib_depth=0.0, twist=0.0):
    """Revolve a closed (r, z) profile around the Z axis. Returns (vertices, faces)."""
    profile = [(float(r), float(z)) for r, z in profile]
    vertices = []
    ids = []
    for r, z in profile:
        if r == 0.0:
            vertices.append((0.0, 0.0, z))
            ids.append([len(vertices) - 1] * segments)
            continue
        ring = []
        for i in range(segments):
            theta = 2 * math.pi * i / segments
            radius = r * (1 + rib_depth * math.cos(ribs * theta + twist * z)) if ribs else r
            vertices.append((radius * math.cos(theta), radius * math.sin(theta), z))
            ring.append(len(vertices) - 1)
        ids.append(ring)
    faces = []
    count = len(profile)
    for j in range(count):
        a_ring = ids[j]
        b_ring = ids[(j + 1) % count]
        for i in range(segments):
            k = (i + 1) % segments
            quad = (a_ring[i], a_ring[k], b_ring[k], b_ring[i])
            for tri in ((quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])):
                if len(set(tri)) == 3:
                    faces.append(tri)
    vertices = numpy.array(vertices)
    faces = numpy.array(faces)
    if signed_volume(vertices, faces) < 0:
        faces = faces[:, ::-1]
    return vertices, faces


def box(center, size):
    cx, cy, cz = center
    sx, sy, sz = (s / 2 for s in size)
    vertices = numpy.array([(cx + x * sx, cy + y * sy, cz + z * sz)
                            for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)])
    faces = numpy.array([(0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6), (0, 1, 4), (1, 5, 4),
                         (2, 6, 3), (3, 6, 7), (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5)])
    if signed_volume(vertices, faces) < 0:
        faces = faces[:, ::-1]
    return vertices, faces


def signed_volume(vertices, faces):
    a, b, c = (vertices[faces[:, i]] for i in range(3))
    return float(numpy.einsum("ij,ij->i", a, numpy.cross(b, c)).sum() / 6.0)


def merge(*meshes):
    vertices, faces, offset = [], [], 0
    for v, f in meshes:
        vertices.append(v)
        faces.append(f + offset)
        offset += len(v)
    return numpy.concatenate(vertices), numpy.concatenate(faces)


def vase_profile(height=120.0, steps=60):
    """A bulbous vase with a narrower neck and a flared, flat open top."""
    points = [(0.0, 0.0)]
    for k in range(steps + 1):
        z = height * k / steps
        t = z / height
        r = 22 + 14 * math.sin(math.pi * min(t / 0.7, 1.0)) - 10 * max(0.0, t - 0.7) + 14 * max(0.0, t - 0.85) ** 1.5 * 6
        points.append((r, z))
    points.append((0.0, height))
    return points


def write_stl(path, vertices, faces, header=b"Ultifixer test model"):
    tris = vertices[faces]
    normals = numpy.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    lengths = numpy.linalg.norm(normals, axis=1)
    lengths[lengths == 0] = 1
    normals = normals / lengths[:, None]
    with open(path, "wb") as handle:
        handle.write(header.ljust(80, b"\0")[:80])
        handle.write(struct.pack("<I", len(faces)))
        record = numpy.zeros(len(faces), dtype=[("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")])
        record["n"] = normals
        record["v"] = tris.reshape(-1, 9)
        handle.write(record.tobytes())


def write_3mf(path, vertices, faces, slicer_config=None, prusa_config=None):
    z_shift = -vertices[:, 2].min()
    vertex_xml = "".join('<vertex x="%.5f" y="%.5f" z="%.5f"/>' % (x, y, z + z_shift) for x, y, z in vertices)
    triangle_xml = "".join('<triangle v1="%d" v2="%d" v3="%d"/>' % tuple(f) for f in faces)
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Application">UltifixerTest</metadata>'
             '<resources><object id="1" type="model"><mesh><vertices>%s</vertices><triangles>%s</triangles></mesh></object></resources>'
             '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 128 128 0" printable="1"/></build></model>'
             % (vertex_xml, triangle_xml))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        archive.writestr("_rels/.rels",
                         '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        archive.writestr("3D/3dmodel.model", model)
        if slicer_config is not None:
            archive.writestr("Metadata/project_settings.config", json.dumps(slicer_config, indent=4))
        if prusa_config is not None:
            archive.writestr("Metadata/Slic3r_PE.config", "\n".join("; %s = %s" % kv for kv in prusa_config.items()))


BAMBU_VASE = {"spiral_mode": "1", "spiral_mode_smooth": "1", "outer_wall_line_width": "1", "line_width": "0.42",
              "bottom_shell_layers": "5", "top_shell_layers": "0", "sparse_infill_density": "0%",
              "layer_height": "0.2", "wall_loops": "1", "printer_model": "Bambu Lab A1",
              "nozzle_diameter": ["0.4"]}
BAMBU_NORMAL = dict(BAMBU_VASE, spiral_mode="0", top_shell_layers="5", sparse_infill_density="15%")


def build(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    ribbed_vase = revolve(vase_profile(), segments=144, ribs=12, rib_depth=0.06, twist=0.03)
    plain_vase = revolve(vase_profile(), segments=144)
    core = revolve([(0, 0)] + [(30, 100 * k / 40) for k in range(41)] + [(0, 100)], segments=96)
    ribs = [box((31 * math.cos(a), 31 * math.sin(a), 50), (6, 6, 100)) for a in numpy.linspace(0, 2 * math.pi, 16, endpoint=False)]
    # Rotate each rib box to face outwards is not needed: overlapping axis-aligned boxes are fine.
    multi_body = merge(core, *ribs)
    cup = revolve([(0, 0), (35, 0), (35, 90), (33, 90), (33, 2), (0, 2)], segments=144)
    ball = revolve([(0, -30)] + [(30 * math.sin(math.pi * k / 40), -30 * math.cos(math.pi * k / 40)) for k in range(1, 40)] + [(0, 30)], segments=96)
    simple_cylinder = revolve([(0, 0), (30, 0), (30, 80), (0, 80)], segments=24)
    cube = box((0, 0, 20), (40, 40, 40))

    files = {
        "model_a.stl": ribbed_vase,             # solid vase, neutral name: found by shape
        "ribbed_pillar.stl": multi_body,        # core + overlapping rib bodies (like MakerWorld "Make My Vase")
        "hollow_cup.stl": cup,                  # already hollow: must stay untouched
        "ball.stl": ball,                       # solid but closed top: not a vase
        "block.stl": cube,                      # simple box: not a vase without a name hint
        "cylinder.stl": simple_cylinder,        # simple shape without a name hint
        "Cylinder_vase.stl": simple_cylinder,   # same shape, but the name says vase
    }
    for name, mesh in files.items():
        write_stl(os.path.join(out_dir, name), *mesh, header=b"MW 1.0 test")
    write_3mf(os.path.join(out_dir, "bambu_vase.3mf"), *simple_cylinder, slicer_config=BAMBU_VASE)
    write_3mf(os.path.join(out_dir, "bambu_not_vase.3mf"), *ribbed_vase, slicer_config=BAMBU_NORMAL)
    write_3mf(os.path.join(out_dir, "plain_vase.3mf"), *ribbed_vase)
    write_3mf(os.path.join(out_dir, "prusa_vase.3mf"), *simple_cylinder,
              prusa_config={"spiral_vase": "1", "external_perimeter_extrusion_width": "0.6",
                            "bottom_solid_layers": "4", "layer_height": "0.2"})
    return sorted(os.listdir(out_dir))


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "generated")
    for name in build(target):
        print(os.path.join(target, name))
