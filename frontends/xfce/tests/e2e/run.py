#!/usr/bin/env python3
"""End to end: the XFCE installer, from Welcome to Done, for real.

Unlike tests/gui/capture-screens.py this does NOT set TUNA_INSTALLER_DRY_RUN
and does NOT stub host_run: navigating to the progress page calls
InstallerWindow.start_install(), which pipes the recipe to the command
core.fisherman_command("install") gives: off live media and outside a
Flatpak, `bash -c 'pkexec /usr/local/bin/fisherman -; exit $?'`.
shared/e2e/setup.sh has put the validating shim at that path (it also answers
`fisherman probe --json` with one disk, the loop device, and says the machine
is not live media), and shared/e2e/fake-bin/pkexec stands in for the polkit
agent a headless runner does not have.

The catalog is shared/e2e/catalog.json, the one every E2E driver reads. It
goes to the frontend (FISHERMAN_IMAGES_PATH) AND to <e2e dir>/catalog.json,
so shared/e2e/check-recipe.py can judge "an account exactly when the image
needs one" against the catalog this run used.

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

# The catalog every E2E driver gives its frontend (shared/e2e/README.md,
# "The catalog"). Its default_image is the selection at the start, and that
# leaf needs an account: the identity page asks for one, the driver types
# it, and the VM job installs it. `fallback_flatpaks` is there to show that
# the frontend never reads it.
CATALOG_FILE = os.path.normpath(os.path.join(REPO, "..", "..", "shared", "e2e", "catalog.json"))
with open(CATALOG_FILE, encoding="utf-8") as fh:
    CATALOG = json.load(fh)
# The account the e2e user types. The VM job installs it for real, so it is
# a valid name for fisherman (not reserved) and names no product.
ACCOUNT = {"username": "e2euser", "fullname": "E2E User", "password": "e2e-password"}
_tmp = tempfile.mkdtemp(prefix="tuna-e2e-xfce-")
# The same catalog, where check-recipe.py looks for it.
os.makedirs(E2E_DIR, exist_ok=True)
with open(os.path.join(E2E_DIR, "catalog.json"), "w") as fh:
    json.dump(CATALOG, fh)
os.environ["FISHERMAN_IMAGES_PATH"] = CATALOG_FILE
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
            if name == "source":
                # The catalog's default_image is the selection at the start;
                # nothing else may be (shared/catalog/README.md).
                leaf = (page.selection() or {}).get("leaf")
                picked = leaf.imgref if leaf else None
                print(f"[e2e] image selected at the start: {picked}")
                if picked != CATALOG["default_image"]:
                    outcome["error"] = f"the source page selected {picked!r}"
                    app.quit()
                    return
            if name == "destination":
                radios = page.radios
                print(f"[e2e] disks offered: {[r.disk['path'] for r in radios]}")
                if not radios:
                    outcome["error"] = "no disks offered"
                    app.quit()
                    return
                radios[0].set_active(True)
            if name == "identity":
                if not win.needs_user_creation():
                    outcome["error"] = "the image needs an account and the identity page asks for none"
                    app.quit()
                    return
                page.username.set_text(ACCOUNT["username"])
                page.fullname.set_text(ACCOUNT["fullname"])
                page.password.set_text(ACCOUNT["password"])
                page.password2.set_text(ACCOUNT["password"])
                # fisherman's answer on the name (`validate --json
                # --partial -`, through the shim) comes back on the loop.
                deadline = time.monotonic() + 15
                while not page.can_continue() and time.monotonic() < deadline:
                    _pump(0.2)
                print(f"[e2e] account typed: {ACCOUNT['username']}")
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
            # The headline is the branded done_title ("{name} is installed"),
            # so compare against the resolved copy rather than a literal.
            outcome["ok"] = headline == core.BRANDING.text("done_title")
        # Read the bar BEFORE the window goes: this is the property the
        # string match below could never see. A frontend that parses
        # fisherman's protocol ends at 1.0; one that does not ends at 0.0
        # while every other assertion here still passes, which is exactly
        # how a bar that never moved kept this gate green.
        outcome["fraction"] = win.pages["progress"].bar.get_fraction()
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
        # fisherman's terminal event, in its real wire format. This was
        # `if "[9/9]" not in text`, a prefix fisherman has never written:
        # the shim invented it to satisfy this line, so the assertion was
        # checking the test harness against itself.
        if '"type":"complete"' not in text:
            print("FAIL: the log never carried a completion event",
                  file=sys.stderr)
            return 1
    if not outcome.get("ok"):
        print("FAIL: the Done page reported failure", file=sys.stderr)
        return 1
    fraction = outcome.get("fraction")
    print(f"[e2e] progress bar ended at {fraction:.0%}")
    if fraction != 1.0:
        print(f"FAIL: the progress bar ended at {fraction:.0%}, not 100% — "
              "the frontend is not parsing fisherman's progress protocol "
              "(shared/progress/README.md)", file=sys.stderr)
        return 1
    received_path = os.path.join(E2E_DIR, "recipe.json")
    if not os.path.exists(received_path):
        print("FAIL: the shim recorded no recipe", file=sys.stderr)
        return 1
    with open(received_path, encoding="utf-8") as fh:
        received = json.load(fh)
    user = received.get("user") or {}
    if user.get("username") != ACCOUNT["username"] or not user.get("password"):
        print(f"FAIL: fisherman received the user {user.get('username')!r}, "
              "not the account typed on the identity page", file=sys.stderr)
        return 1
    print("OK: XFCE reached Done through " + core.shell_line(core.fisherman_argv()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
