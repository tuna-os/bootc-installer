#!/usr/bin/env python3
"""End to end: the XFCE installer, from Welcome to Done, for real.

Unlike tests/gui/capture-screens.py this does NOT set TUNA_INSTALLER_DRY_RUN
and does NOT stub host_run: navigating to the progress page calls
InstallerWindow.start_install(), which writes the recipe and spawns
`sudo /usr/local/bin/fisherman <recipe>` exactly as it does on a live ISO.
shared/e2e/setup.sh has put the validating shim at that path, the e2e lsblk
on PATH (one disk: the loop device) and a failing bootc (no live-ISO mode).

    xvfb-run -a python3 tests/e2e/run.py

Exit 0 only when the Done page says the install completed.
"""
import json
import os
import sys
import tempfile
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

E2E_DIR = os.environ.get("TUNA_E2E_DIR", "/tmp/tuna-e2e")
TIMEOUT = float(os.environ.get("TUNA_E2E_TIMEOUT", "120"))
os.environ.pop("TUNA_INSTALLER_DRY_RUN", None)

# One image the real fisherman validates (grub2 + xfs, no composefs, no user).
CATALOG = {
    "default_image": "quay.io/centos-bootc/centos-bootc:c10s",
    "fallback_flatpaks": [],
    "images": [{
        "name": "E2E", "registry": "quay.io/centos-bootc/centos-bootc",
        "desc": "End-to-end canary.", "bootloader": "grub2", "filesystem": "xfs",
        "composefs": False, "needs_user_creation": False,
        "children": [{"name": "CentOS bootc", "tag": "c10s", "subtitle": "canary",
                      "desc": "The image the VM job installs."}],
    }],
}
_tmp = tempfile.mkdtemp(prefix="tuna-e2e-xfce-")
_catalog = os.path.join(_tmp, "images.json")
with open(_catalog, "w") as fh:
    json.dump(CATALOG, fh)
os.environ["FISHERMAN_IMAGES_PATH"] = _catalog
os.environ.setdefault("XDG_RUNTIME_DIR", _tmp)
os.environ.setdefault("XDG_STATE_HOME", os.path.join(_tmp, "state"))
os.environ.setdefault("GTK_A11Y", "none")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from tuna_installer_xfce import core  # noqa: E402
from tuna_installer_xfce.app import PAGE_ORDER, InstallerWindow  # noqa: E402

if core.dry_run():
    sys.exit("refusing: TUNA_INSTALLER_DRY_RUN is set; this run must launch the shim")


def _pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.02)


def main():
    app = Gtk.Application(application_id="org.tunaos.installer.xfce.e2e")
    outcome = {}

    def on_activate(_app):
        win = InstallerWindow(app)
        win.show_all()
        _pump(0.3)
        for name in PAGE_ORDER:
            if name == "progress":
                break
            win._enter(PAGE_ORDER.index(name))
            _pump(0.2)
            page = win.pages[name]
            if name == "destination":
                radios = page.radios
                print(f"[e2e] disks offered: {[r.disk['path'] for r in radios]}")
                if not radios:
                    outcome["error"] = "no disks offered"
                    app.quit()
                    return
                radios[0].set_active(True)
            if not page.can_continue():
                outcome["error"] = f"page {name} would not let a user continue"
                app.quit()
                return
            win.refresh_nav()
        print("[e2e] pressing Install Now")
        win._enter(PAGE_ORDER.index("progress"))   # on_enter() starts the install
        deadline = time.monotonic() + TIMEOUT
        while win.stack.get_visible_child_name() != "done" and time.monotonic() < deadline:
            _pump(0.25)
        if win.stack.get_visible_child_name() != "done":
            outcome["error"] = f"no Done page after {TIMEOUT:.0f}s"
        else:
            headline = win.pages["done"].headline.get_text()
            outcome["headline"] = headline
            outcome["ok"] = "complete" in headline.lower()
        win.destroy()
        app.quit()

    app.connect("activate", on_activate)
    app.run([])

    if "error" in outcome:
        print(f"FAIL: {outcome['error']}", file=sys.stderr)
        return 1
    print(f"[e2e] done page: {outcome.get('headline')!r}")
    log = core.install_log_path()
    if os.path.exists(log):
        with open(log) as fh:
            text = fh.read()
        print("[e2e] install log:\n" + text)
        if "[9/9]" not in text:
            print("FAIL: the log never reached step 9", file=sys.stderr)
            return 1
    if not outcome.get("ok"):
        print("FAIL: the Done page reported failure", file=sys.stderr)
        return 1
    if not os.path.exists(os.path.join(E2E_DIR, "recipe.json")):
        print("FAIL: the shim recorded no recipe", file=sys.stderr)
        return 1
    print("OK: XFCE reached Done through sudo /usr/local/bin/fisherman")
    return 0


if __name__ == "__main__":
    sys.exit(main())
