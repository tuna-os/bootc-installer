#!/usr/bin/env python3
"""Write the Devel manifest from the production one.

    python3 flatpak/generate-devel.py            # rewrite the Devel manifest
    python3 flatpak/generate-devel.py --check    # exit 1 when it is stale

The two manifests were edited by hand and drifted (#320): a fix to a module
reached one and not the other. The Devel manifest is the production one
with exactly three differences, all listed here: the app id, the
development permissions, and the module that installs the Devel desktop
file and icon. Change the production manifest, then run this.
tests/unit/test_gnome_manifest_diet.py fails when the committed file is
not what this writes.
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCTION = os.path.join(HERE, "org.bootcinstaller.Installer.json")
DEVEL = os.path.join(HERE, "org.bootcinstaller.Installer.Devel.json")
DEVEL_ID = "org.bootcinstaller.Installer.Devel"

# Only the Devel build may be traced and debugged from inside the sandbox.
DEVEL_FINISH_ARGS = [
    "--allow=devel",
    "--env=BOOTC_INSTALLER_DEBUG=1",
    f"--env=BOOTC_APP_ID={DEVEL_ID}",
]

DEVEL_ASSETS = {
    "name": "devel-assets",
    "buildsystem": "simple",
    "build-commands": [
        f"install -Dm644 data/{DEVEL_ID}.desktop /app/share/applications/{DEVEL_ID}.desktop",
        f"install -Dm644 data/icons/hicolor/scalable/apps/{DEVEL_ID}.svg "
        f"/app/share/icons/hicolor/scalable/apps/{DEVEL_ID}.svg",
    ],
    "sources": [{"type": "dir", "path": ".."}],
}


def devel_from(production):
    manifest = copy.deepcopy(production)
    manifest["app-id"] = DEVEL_ID
    manifest["finish-args"] = [arg for arg in manifest["finish-args"]
                               if arg not in DEVEL_FINISH_ARGS] + DEVEL_FINISH_ARGS
    manifest["modules"] = manifest["modules"] + [copy.deepcopy(DEVEL_ASSETS)]
    return manifest


def dumps(manifest):
    return json.dumps(manifest, indent=4, ensure_ascii=False) + "\n"


def generated():
    with open(PRODUCTION, encoding="utf-8") as stream:
        return dumps(devel_from(json.load(stream)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    text = generated()
    if "--check" in argv:
        with open(DEVEL, encoding="utf-8") as stream:
            if stream.read() != text:
                print("flatpak/org.bootcinstaller.Installer.Devel.json is stale: "
                      "run python3 flatpak/generate-devel.py", file=sys.stderr)
                return 1
        return 0
    with open(DEVEL, "w", encoding="utf-8") as stream:
        stream.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
