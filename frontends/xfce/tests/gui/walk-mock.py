#!/usr/bin/env python3
"""Walk the real XFCE installer against a running mock fishermand and save
one picture a page. For people, not CI: run under Xvfb with a window
manager, with $FISHERMAND_SOCKET_DIR set to the mock's socket directory.

    walk-mock.py OUT_DIR

Each picture is the whole X screen (`import -window root`). The walk types
the demo account, presses Next until the install starts, then waits on the
progress page and pictures the pages after it. It ticks the recovery key
box. Nothing here decides a pass: a person reads the pictures.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
os.environ.setdefault("BOOTC_INSTALLER_BACKEND", "daemon")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from tuna_installer_xfce import app  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
state = {"n": 0, "seen": [], "idle": 0}


def shot(name):
    while Gtk.events_pending():
        Gtk.main_iteration()
    path = os.path.join(OUT, f"{state['n']:02d}-{name}.png")
    subprocess.run(["import", "-window", "root", path], check=False)
    state["n"] += 1


def fill(page):
    for attr, value in (("username", "tester"), ("fullname", "Test User"),
                        ("pass1", "tunae2epassword25"), ("pass2", "tunae2epassword25"),
                        ("password", "tunae2epassword25"),
                        ("password2", "tunae2epassword25"),
                        ("confirm", "tunae2epassword25")):
        widget = getattr(page, attr, None)
        if isinstance(widget, Gtk.Entry) and widget.get_sensitive() and not widget.get_text():
            widget.set_text(value)
    ack = getattr(page, "ack", None)
    if isinstance(ack, Gtk.CheckButton) and ack.get_visible():
        ack.set_active(True)


def step(win):
    name = app.PAGE_ORDER[win.index]
    page = win.pages[name]
    if name in ("progress",):
        state["idle"] += 1
        if state["idle"] == 2:
            shot(name)
        return True
    state["idle"] = 0
    if name not in state["seen"] or name in ("recovery",):
        state["seen"].append(name)
        shot(name)
    if name == "done" or state["n"] > 30:
        Gtk.main_quit()
        return False
    fill(page)
    win.refresh_nav()
    if name == "destination" and not page.selected_disk():
        return True
    if win.next_btn.get_visible() and win.next_btn.get_sensitive():
        if name == "recovery":
            shot(name + "-ticked")
        win.next_btn.clicked()
    elif name == "handoff":
        Gtk.main_quit()
        return False
    return True


win = app.InstallerWindow(None)
win.show_all()
GLib.timeout_add(1500, step, win)
GLib.timeout_add(120000, Gtk.main_quit)
Gtk.main()
