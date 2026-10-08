"""The capture harness must not credit a screen for text nobody can see.

tests/gui/capture-screens.py walks the visible carousel page and collects
its strings; shared/walkthrough/parity_report.py matches tunaOS's screen
keywords against them, and docs/PARITY.md is read off the result.

The walk used to visit hidden widgets too. Pages hide rows on runtime
probes -- welcome.py hides the Bluetooth row unless /sys/class/bluetooth
has an adapter, which no CI runner does -- so the committed
walkthrough-gnome.json claimed "Connect Bluetooth Devices" while
01-welcome.png showed no such row. The XFCE harness had the same hole and
credited its done page with a "Visit the store" button that is hidden
when no store URL is configured.
"""

import importlib.util
import pathlib

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]


def _harness():
    spec = importlib.util.spec_from_file_location(
        "capture_harness_under_test", REPO / "tests" / "gui" / "capture-screens.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _box(*children):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    for c in children:
        box.append(c)
    return box


def test_visible_label_is_collected():
    page_text = _harness()._page_text
    assert "shown" in " ".join(page_text(_box(Gtk.Label(label="shown"))))


def test_hidden_label_is_not_collected():
    page_text = _harness()._page_text
    hidden = Gtk.Label(label="invisible")
    hidden.set_visible(False)
    collected = " ".join(page_text(_box(Gtk.Label(label="shown"), hidden)))
    assert "shown" in collected
    assert "invisible" not in collected, \
        "a hidden label reached the parity report"


def test_children_of_a_hidden_container_are_not_collected():
    # The Bluetooth case: the ROW is hidden, and its title and subtitle are
    # children of it. Pruning only the hidden widget itself would still
    # collect them.
    page_text = _harness()._page_text
    row = Adw.ActionRow(title="Connect Bluetooth Devices",
                        subtitle="Pair your keyboard or mouse to continue")
    row.set_visible(False)
    collected = " ".join(page_text(_box(Gtk.Label(label="shown"), row)))
    assert "shown" in collected
    assert "Bluetooth" not in collected, \
        "a hidden row's title reached the parity report"
    assert "Pair your keyboard" not in collected, \
        "a hidden row's subtitle reached the parity report"


def test_the_xfce_harness_has_the_same_guard():
    # Its tree walk is a separate GTK3 implementation, so the behaviour
    # cannot be shared; assert the guard is present rather than silently
    # letting that one drift back.
    text = (REPO / "frontends" / "xfce" / "tests" / "gui"
            / "capture-screens.py").read_text()
    assert "get_visible()" in text, "XFCE's _page_text lost its visibility guard"
