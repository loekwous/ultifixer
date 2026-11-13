import os
import struct
import sys

import numpy
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "plugin"))
sys.path.insert(0, os.path.join(ROOT, "tests", "fixtures"))
sys.path.insert(0, os.path.join(ROOT, "tests", "e2e"))

import make_fixtures  # noqa: E402

PRIVATE = os.path.join(ROOT, "tests", "fixtures", "private")


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory):
    target = str(tmp_path_factory.mktemp("fixtures"))
    make_fixtures.build(target)
    return target


def read_stl(path):
    """Binary STL -> (N*3, 3) vertices, Z up."""
    with open(path, "rb") as handle:
        data = handle.read()
    count = struct.unpack("<I", data[80:84])[0]
    records = numpy.frombuffer(data[84:84 + 50 * count], dtype=[("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")])
    return records["v"].reshape(-1, 3).astype(numpy.float64)
