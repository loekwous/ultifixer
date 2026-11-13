#!/usr/bin/env python3
"""Build dist/Ultifixer.curapackage (and a copy with the version in its name).

Usage: python scripts/build_package.py [version]
The version defaults to the one in plugin/Ultifixer/plugin.json. A leading "v" is dropped.
"""

import json
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(ROOT, "plugin", "Ultifixer")
DIST = os.path.join(ROOT, "dist")
SDK_VERSION = "8.0.0"


def main() -> int:
    with open(os.path.join(PLUGIN_DIR, "plugin.json"), encoding="utf-8") as handle:
        plugin_meta = json.load(handle)
    version = (sys.argv[1] if len(sys.argv) > 1 else plugin_meta["version"]).lstrip("v")
    plugin_meta["version"] = version

    package_meta = {
        "package_id": "Ultifixer",
        "package_type": "plugin",
        "display_name": "Ultifixer",
        "description": plugin_meta["description"],
        "package_version": version,
        "sdk_version": SDK_VERSION,
        "sdk_version_semver": SDK_VERSION,
        "website": "https://github.com/loekwous/ultifixer",
        "author": {
            "author_id": "loekwous",
            "display_name": "Loek Lankhorst",
            "website": "https://github.com/loekwous",
        },
        "tags": ["vase", "spiralize", "bambu", "makerworld"],
    }

    os.makedirs(DIST, exist_ok=True)
    target = os.path.join(DIST, "Ultifixer.curapackage")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package.json", json.dumps(package_meta, indent=4))
        archive.write(os.path.join(ROOT, "LICENSE"), "LICENSE")
        for name in sorted(os.listdir(PLUGIN_DIR)):
            path = os.path.join(PLUGIN_DIR, name)
            if not os.path.isfile(path) or name.endswith((".pyc", ".pyo")):
                continue
            arcname = "files/plugins/Ultifixer/" + name
            if name == "plugin.json":
                archive.writestr(arcname, json.dumps(plugin_meta, indent=4))
            else:
                archive.write(path, arcname)
        archive.write(os.path.join(ROOT, "LICENSE"), "files/plugins/Ultifixer/LICENSE")
    versioned = os.path.join(DIST, "Ultifixer-%s.curapackage" % version)
    shutil.copyfile(target, versioned)
    print(target)
    print(versioned)
    return 0


if __name__ == "__main__":
    sys.exit(main())
