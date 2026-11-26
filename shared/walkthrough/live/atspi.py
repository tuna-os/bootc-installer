"""Print the AT-SPI tree of the installer as JSON lines, or act on one node.

A program of its own, so that a toolkit that hangs the AT-SPI client cannot
hang the walk.

    atspi.py dump
    atspi.py press PATH          the first action of the node
    atspi.py focus PATH
    atspi.py text PATH TEXT      replace the content of an entry
"""

import json
import sys

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

STATES = {"showing": Atspi.StateType.SHOWING, "visible": Atspi.StateType.VISIBLE,
          "sensitive": Atspi.StateType.SENSITIVE, "enabled": Atspi.StateType.ENABLED,
          "checked": Atspi.StateType.CHECKED, "focused": Atspi.StateType.FOCUSED,
          "selected": Atspi.StateType.SELECTED, "editable": Atspi.StateType.EDITABLE,
          "focusable": Atspi.StateType.FOCUSABLE, "pressed": Atspi.StateType.PRESSED}


def walk(node, path, out, depth=0):
    if node is None or depth > 40 or len(out) > 3000:
        return
    try:
        states = node.get_state_set()
        st = [n for n, s in STATES.items() if states.contains(s)]
        item = {"path": path, "role": node.get_role_name(), "name": node.get_name() or "",
                "description": node.get_description() or "", "states": st}
        try:
            iface = node.get_text_iface()
            if iface is not None:
                item["text"] = Atspi.Text.get_text(iface, 0, min(400, Atspi.Text.get_character_count(iface)))
        except Exception:
            pass
        try:
            a = node.get_action_iface()
            item["actions"] = a.get_n_actions() if a else 0
        except Exception:
            item["actions"] = 0
        try:
            c = node.get_component_iface()
            if c is not None:
                e = c.get_extents(Atspi.CoordType.WINDOW)
                item["box"] = [e.x, e.y, e.width, e.height]
        except Exception:
            pass
        out.append(item)
        n = node.get_child_count()
    except Exception:
        return
    for i in range(min(n, 400)):
        try:
            child = node.get_child_at_index(i)
        except Exception:
            continue
        walk(child, path + [i], out, depth + 1)


def resolve(path):
    node = Atspi.get_desktop(0)
    for i in path:
        node = node.get_child_at_index(i)
    return node


def main():
    verb = sys.argv[1]
    if verb == "dump":
        out = []
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is not None and (app.get_name() or "") not in ("sway", "at-spi-bus-launcher"):
                walk(app, [i], out)
        for item in out:
            print(json.dumps(item, ensure_ascii=False))
        return 0
    node = resolve(json.loads(sys.argv[2]))
    if verb == "press":
        return 0 if node.get_action_iface().do_action(0) else 1
    if verb == "focus":
        return 0 if node.get_component_iface().grab_focus() else 1
    if verb == "text":
        iface = node.get_editable_text_iface()
        return 0 if Atspi.EditableText.set_text_contents(iface, sys.argv[3]) else 1
    return 2


if __name__ == "__main__":
    Atspi.set_timeout(1500, 5000)
    sys.exit(main())
