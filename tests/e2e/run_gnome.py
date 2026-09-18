#!/usr/bin/env python3
"""End to end: the GNOME installer, from Welcome to Done, through the real
backend launch path.

Everything between the first page and the Done page is the shipped code:
the step widgets, the recipe the Processor writes, BootcProgress.start()
staging and launching fisherman (pkexec outside Flatpak), the log watcher
that feeds the progress bar, and set_installation_result(). The only
substitutions are the ones shared/e2e/setup.sh makes on the host: fisherman
at /usr/local/bin is the validating shim, pkexec/lsblk/bootc on PATH are the
e2e fakes, and the disk list is the loop device.

    xvfb-run -a python3 tests/e2e/run_gnome.py

Exit 0 only when the Done page reported success and the shim recorded a
recipe; shared/e2e/check-recipe.py judges the recipe afterwards.
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

E2E_DIR = os.environ.get("TUNA_E2E_DIR", "/tmp/tuna-e2e")
DISK = os.environ.get("TUNA_E2E_DISK") or Path(E2E_DIR, "loopdev").read_text().strip()
TIMEOUT = float(os.environ.get("TUNA_E2E_TIMEOUT", "120"))

# The system recipe the app ships (images, steps, log file), with the image
# catalogue reduced to one entry the real fisherman can validate: no
# composefs on xfs, no user creation. The frontend still reads every other
# field from the shipped file.
_sys = json.loads((REPO / "recipe.json").read_text())
_sys["images"] = [{
    "name": "E2E",
    "imgref": "quay.io/centos-bootc/centos-bootc:c10s",
    "bootloader": "grub2",
    "filesystem": "xfs",
    "composefs": False,
    "needs_user_creation": False,
}]
_sys["imgref"] = _sys["images"][0]["imgref"]
_sys["log_file"] = os.path.join(E2E_DIR, "gnome-install.log")
_sys_path = os.path.join(E2E_DIR, "gnome-sys-recipe.json")
with open(_sys_path, "w") as fh:
    json.dump(_sys, fh, indent=2)
os.environ["BOOTC_CUSTOM_RECIPE"] = _sys_path
os.environ.pop("BOOTC_DEMO", None)
# BOOTC_TEST is the app's own self-driving mode: every page auto-advances
# 700 ms after it is shown, the confirm page confirms, and outside Flatpak
# the backend launch path is unchanged (pkexec /usr/local/bin/fisherman).
# The driver therefore only has to run the main loop and wait.
os.environ["BOOTC_TEST"] = "1"
os.environ.setdefault("GTK_A11Y", "none")
os.environ.setdefault("NO_AT_BRIDGE", "1")
# Xvfb has no GPU; the cairo renderer keeps the frame clock ticking without
# one, which the animated carousel the auto-advance waits on needs.
os.environ.setdefault("GSK_RENDERER", "cairo")

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

# Same bundle the UI tests register (tests/ui/conftest.py), without pytest.
_res = next((p for p in (
    os.environ.get("BOOTC_RESOURCE", ""),
    str(REPO / "build" / "bootc_installer" / "bootc-installer.gresource"),
    str(REPO / "_build" / "bootc_installer" / "bootc-installer.gresource"),
) if p and os.path.exists(p)), None)
if not _res:
    sys.exit("FAIL: bootc-installer.gresource not built (meson setup build && ninja -C build)")
Gio.Resource.load(_res)._register()
Adw.init()

from bootc_installer.windows.main_window import BootcWindow


class _E2EDisksManager:
    def __init__(self):
        self._disks = [SimpleNamespace(
            display_name="E2E loop disk", disk=DISK, pretty_size="20 GB",
            size=20 * 1024**3, is_removable=False)]

    def all_disks(self, include_removable=False):
        return list(self._disks)


def main():
    result = {}
    orig = BootcWindow.set_installation_result
    loop = GLib.MainLoop()

    def record(self, ok, terminal, *a, **kw):
        result["ok"] = ok
        r = orig(self, ok, terminal, *a, **kw)
        GLib.timeout_add(500, loop.quit)
        return r

    patchers = [
        patch("bootc_installer.defaults.disk.DisksManager", return_value=_E2EDisksManager()),
        patch("bootc_installer.defaults.qr_companion.CompanionServer"),
        patch("bootc_installer.defaults.qr_companion.get_local_ip", return_value="127.0.0.1"),
        patch.object(BootcWindow, "set_installation_result", record),
    ]
    for p in patchers:
        p.start()

    app = Adw.Application(application_id="org.bootcinstaller.InstallerE2E",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register()
    window = BootcWindow(application=app)
    window.present()

    def watchdog():
        print(f"FAIL: no installation result after {TIMEOUT:.0f}s", file=sys.stderr)
        loop.quit()
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(int(TIMEOUT * 1000), watchdog)
    print("[e2e] running the wizard in BOOTC_TEST self-driving mode")
    loop.run()

    if "ok" not in result:
        return 1
    done = window._BootcWindow__view_done
    print(f"[e2e] result={result['ok']} done title={done.page_header.title!r}")

    log = os.path.join(os.path.expanduser("~"), ".cache", "bootc-installer", "fisherman-output.log")
    if os.path.exists(log):
        with open(log) as fh:
            tail = fh.read()
        print("[e2e] fisherman log:\n" + tail)
        if "[9/9]" not in tail:
            print("FAIL: the log never reached step 9", file=sys.stderr)
            return 1
    else:
        print(f"FAIL: no fisherman log at {log}", file=sys.stderr)
        return 1

    window.destroy()
    for p in reversed(patchers):
        p.stop()
    if not result["ok"]:
        print("FAIL: the Done page reported failure", file=sys.stderr)
        return 1
    if not os.path.exists(os.path.join(E2E_DIR, "recipe.json")):
        print("FAIL: the shim recorded no recipe", file=sys.stderr)
        return 1
    print("OK: GNOME reached Done through the real backend launch path")
    return 0


if __name__ == "__main__":
    sys.exit(main())
