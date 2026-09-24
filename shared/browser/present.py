#!/usr/bin/env python3
"""Present a frontend's real installer window on a Broadway display.

Broadway is GTK's own HTML5 backend: ``gtk4-broadwayd`` (GTK4) and
``broadwayd`` (GTK3) each serve a display over HTTP, and a GTK client started
with ``GDK_BACKEND=broadway`` draws into it. The browser then holds the real
widgets -- not a video, not a mock -- so Playwright can screenshot and drive
them.

This process does not capture anything. It puts the window up and then waits,
so the browser can step it through the wizard. Which page is showing is
negotiated through two small files rather than a socket, because the GTK main
loop is already running and a poll on a timeout is less machinery than an
HTTP server for two strings:

    <cmd file>    the browser writes the page it wants
    <state file>  this process writes {"pages": [...], "current": "<page>"}

The browser waits for ``current`` to match what it asked for, so no screenshot
is ever taken mid-transition.

Every fixture -- fake disks, the refusal to launch fisherman, the canned
recipe -- is imported from the frontend's existing capture harness rather than
restated here. There is one definition of "the installer, with nothing real
behind it", and both harnesses use it.

    python3 shared/browser/present.py gnome
    python3 shared/browser/present.py xfce
"""

import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Each entry says where the frontend's capture harness lives and how to build
# and drive its window. The two differ in more than GTK version: GNOME holds
# its pages in an Adw.Carousel, XFCE in a Gtk.Stack with a separate step bar.
FRONTENDS = {
    "gnome": {
        "harness": "tests/gui/capture-screens.py",
        "syspath": [""],
        "gtk": "4.0",
    },
    "xfce": {
        "harness": "frontends/xfce/tests/gui/capture-screens.py",
        "syspath": ["frontends/xfce"],
        "gtk": "3.0",
    },
}


def _load_harness(rel):
    spec = importlib.util.spec_from_file_location(
        "capture_harness", os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # runs its env setup and mocks
    return mod


def _run_gnome(cap, cmd_file, state_file):
    from gi.repository import Adw, Gio, GLib

    for patcher in cap.PATCHERS:
        patcher.start()

    app = Adw.Application(application_id="org.bootcinstaller.Installer.Browser",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(_app):
        win = cap.BootcWindow(application=app)
        win.set_default_size(1000, 700)
        win.present()
        carousel = win.carousel
        names = [cap._page_name(carousel.get_nth_page(i))
                 for i in range(carousel.get_n_pages())]

        def show(name):
            page = carousel.get_nth_page(names.index(name))
            cap._seed(win, page, name)
            carousel.scroll_to(page, False)

        _serve(names, show, cmd_file, state_file, GLib)

    app.connect("activate", on_activate)
    app.run([])


def _run_xfce(cap, cmd_file, state_file):
    from gi.repository import Gtk, GLib

    app = Gtk.Application(application_id="org.tunaos.installer.xfce.browser")

    def on_activate(_app):
        win = cap.InstallerWindow(app)
        win.set_default_size(760, 560)
        win.show_all()
        names = list(cap.PAGE_ORDER)

        def show(name):
            index = names.index(name)
            win.index = index
            win.stack.set_visible_child_name(name)
            win.trawl.set_step(index)
            # Drive the stack directly, exactly as the capture harness does:
            # _enter() fires on_enter side effects, and on the progress page
            # that side effect is the install itself.
            if name == "progress":
                cap._seed_progress(win.pages["progress"])
            elif name == "done":
                win.pages["done"].set_result(True, "")
            else:
                win.pages[name].on_enter()
            win.refresh_nav()

        _serve(names, show, cmd_file, state_file, GLib)

    app.connect("activate", on_activate)
    app.run([])


def _serve(names, show, cmd_file, state_file, GLib):
    """Publish the page list, then honour page requests until killed."""
    def publish(current):
        # Written to a temporary and renamed so the browser never reads a
        # half-written file and concludes the page never changed.
        tmp = state_file + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"pages": names, "current": current}, fh)
        os.replace(tmp, state_file)

    publish(None)
    print("PAGES " + " ".join(names), flush=True)

    last = {"want": None}

    def poll():
        try:
            with open(cmd_file) as fh:
                want = fh.read().strip()
        except OSError:
            return True
        if want and want != last["want"] and want in names:
            last["want"] = want
            show(want)
            print("SHOW " + want, flush=True)
            # One frame of grace: scroll_to and set_visible_child_name return
            # before GTK has drawn, and Broadway pushes the new frame after
            # that. Announcing the page early is how a screenshot catches the
            # previous one.
            GLib.timeout_add(400, lambda: (publish(want), False)[1])
        return True

    GLib.timeout_add(200, poll)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in FRONTENDS:
        print("usage: present.py {%s}" % "|".join(FRONTENDS), file=sys.stderr)
        return 2
    name = sys.argv[1]
    spec = FRONTENDS[name]
    cmd_file = os.environ.get("BROWSER_CMD_FILE", "/tmp/browser-cmd-" + name)
    state_file = os.environ.get("BROWSER_STATE_FILE", "/tmp/browser-state-" + name)

    for entry in spec["syspath"]:
        sys.path.insert(0, os.path.join(REPO, entry) if entry else REPO)
    # The harness reads sys.argv for its output directory; it has none here.
    sys.argv = [sys.argv[0]]
    cap = _load_harness(spec["harness"])

    {"gnome": _run_gnome, "xfce": _run_xfce}[name](cap, cmd_file, state_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
