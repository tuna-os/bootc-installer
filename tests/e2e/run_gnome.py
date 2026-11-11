#!/usr/bin/env python3
"""End to end: the GNOME installer, from Welcome to Done, through the real
backend launch path.

Everything between the first page and the Done page is the shipped code:
the step widgets, the recipe the Processor writes, BootcProgress.start()
staging and launching fisherman (pkexec outside Flatpak), the log watcher
that feeds the progress bar, and set_installation_result(). The only
substitutions are the ones shared/e2e/setup.sh makes on the host: fisherman
at /usr/local/bin is the validating shim, pkexec/bootc on PATH are the e2e
fakes, and the disk list is what the shim answers to `fisherman probe --json`:
the loop device. The disk page reads it through the real DisksManager.

    xvfb-run -a python3 tests/e2e/run_gnome.py

Exit 0 only when the Done page reported success and the shim recorded a
recipe; shared/e2e/check-recipe.py judges the recipe afterwards.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

E2E_DIR = os.environ.get("TUNA_E2E_DIR", "/tmp/tuna-e2e")
TIMEOUT = float(os.environ.get("TUNA_E2E_TIMEOUT", "120"))

# The catalog every E2E driver gives its frontend (shared/e2e/README.md,
# "The catalog"). This run installs the leaf named by its default_image:
# that leaf needs an account, so the wizard shows the user step, the driver
# fills it in below and the VM job installs the account.
CATALOG_FILE = REPO / "shared" / "e2e" / "catalog.json"
CATALOG = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
IMAGE = CATALOG["default_image"]
# The account the e2e user types. The VM job installs it for real, so it is
# a valid name for fisherman (not reserved) and names no product.
ACCOUNT = {"fullname": "E2E User", "username": "e2euser", "password": "e2e-password"}

# The system recipe the app ships (steps, log file), with the catalog above
# as its `images`. The frontend still reads every other field from the
# shipped file.
_sys = json.loads((REPO / "recipe.json").read_text())
_sys["images"] = CATALOG["images"]
_sys["imgref"] = IMAGE
# The shipped recipe has an image step that offers the whole catalog. This
# run installs the one image above, so it takes the step out, as the recipe
# loader does on live media; `imgref` then names the image. The other
# steps (the connection check included) run as shipped.
_sys["steps"].pop("image", None)
# The catalog this run gave the frontend, for shared/e2e/check-recipe.py:
# it judges "an account if, and only if, the image needs one" against it.
os.makedirs(E2E_DIR, exist_ok=True)
with open(os.path.join(E2E_DIR, "catalog.json"), "w") as fh:
    json.dump(CATALOG, fh, indent=2)
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

from bootc_installer.defaults.user import BootcDefaultUsers
from bootc_installer.windows.main_window import BootcWindow


def _fill_account_then_next(page):
    """The user step in BOOTC_TEST mode: type the account as a person does,
    wait for fisherman's answer on the name (`validate --json --partial -`
    through the shim), then press Next. The app's own test_auto_advance
    presses Next on an empty form, which gives a recipe with no account."""
    page.fullname_entry.set_text(ACCOUNT["fullname"])
    page.username_entry.set_text(ACCOUNT["username"])
    page.password_entry.set_text(ACCOUNT["password"])
    page.password_confirmation.set_text(ACCOUNT["password"])
    waited = {"ms": 0}

    def next_when_ready():
        waited["ms"] += 100
        if page.btn_next.get_sensitive():
            print(f"[e2e] account typed: {ACCOUNT['username']}")
            page.btn_next.emit("clicked")
            return GLib.SOURCE_REMOVE
        if waited["ms"] >= 15000:
            print("FAIL: the user step holds Next on a valid account after 15s",
                  file=sys.stderr)
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    GLib.timeout_add(100, next_when_ready)


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
        patch("bootc_installer.defaults.qr_companion.CompanionServer"),
        patch.object(BootcWindow, "set_installation_result", record),
        patch.object(BootcDefaultUsers, "test_auto_advance", _fill_account_then_next),
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
        # fisherman's terminal event in its real wire format. This was
        # `if "[9/9]" not in tail`, a prefix fisherman has never written —
        # the e2e shim invented it to satisfy assertions like this one, so
        # the check was comparing the harness with itself.
        if '"type":"complete"' not in tail:
            print("FAIL: the log never carried a completion event",
                  file=sys.stderr)
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
    received_path = os.path.join(E2E_DIR, "recipe.json")
    if not os.path.exists(received_path):
        print("FAIL: the shim recorded no recipe", file=sys.stderr)
        return 1
    with open(received_path, encoding="utf-8") as fh:
        received = json.load(fh)
    # The leaf needs an account: the one typed above, with the shared groups.
    user = received.get("user") or {}
    if user.get("username") != ACCOUNT["username"] or not user.get("password"):
        print(f"FAIL: fisherman received the user {user.get('username')!r}, "
              f"not the account typed on the user step", file=sys.stderr)
        return 1
    if received.get("targetImgref") != IMAGE:
        print(f"FAIL: fisherman received targetImgref {received.get('targetImgref')!r}, "
              f"not {IMAGE!r}", file=sys.stderr)
        return 1
    print("OK: GNOME reached Done through the real backend launch path")
    return 0


if __name__ == "__main__":
    sys.exit(main())
