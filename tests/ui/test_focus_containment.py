"""Tab stays on the page the user can see (#310).

Every wizard page lives in one Adw.Carousel. With the carousel on Welcome,
Tab used to walk into the disk list, the passphrase entries and the Done
page's Reboot button: controls the user cannot see. This drives the real
BootcWindow with the shipped recipe.json and presses Tab the way the key
binding does (the `move-focus` action signal).
"""

import gi
import pytest

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ._real_window import current_page, go, pages, pump, real_window, shipped_recipe

# More than the number of focusable widgets in the whole window, so the walk
# wraps around at least once.
TABS = 150


def _owner_page(window, widget):
    """The carousel page `widget` is on, or None (header bar, dialogs)."""
    for page in pages(window):
        if widget is page or widget.is_ancestor(page):
            return page
    return None


def _describe(widget):
    names = []
    while widget is not None and len(names) < 6:
        names.append(type(widget).__name__)
        widget = widget.get_parent()
    return " < ".join(names)


def _tab_walk(window, direction=Gtk.DirectionType.TAB_FORWARD, presses=TABS):
    """Press Tab `presses` times. Returns the widgets that held focus, and
    fails on the first one that sits on a page that is not on screen."""
    visited = []
    here = current_page(window)
    for press in range(presses):
        window.emit("move-focus", direction)
        pump()
        focus = window.get_focus()
        if focus is None:
            continue
        visited.append(focus)
        owner = _owner_page(window, focus)
        assert owner is None or owner is here, (
            f"Tab press {press + 1} on {type(here).__name__} put focus on "
            f"{type(owner).__name__}: {_describe(focus)}")
    return visited


@pytest.fixture(params=["shipped", "with-account"])
def window(request, tmp_path):
    recipe = None if request.param == "shipped" else shipped_recipe(needs_user_creation=True)
    with real_window(tmp_path, recipe) as win:
        yield win


@pytest.mark.parametrize("direction", [Gtk.DirectionType.TAB_FORWARD, Gtk.DirectionType.TAB_BACKWARD])
def test_tab_from_welcome_never_reaches_another_page(window, direction):
    assert current_page(window)._bootc_step_key == "welcome"
    visited = _tab_walk(window, direction)
    on_welcome = [w for w in visited if _owner_page(window, w) is current_page(window)]
    in_header = [w for w in visited if _owner_page(window, w) is None]
    # The walk is real: focus moved, on the page and through the header.
    assert len(set(on_welcome)) >= 1, "Tab never focused anything on Welcome"
    assert len(set(in_header)) >= 1, "Tab never reached the header bar"


def test_only_the_current_page_can_take_focus(window):
    """The mechanism: `can-focus` is off on every page but the current one,
    from the first frame, with no page-changed needed."""
    here = current_page(window)
    assert here.get_can_focus()
    for page in pages(window):
        if page is not here:
            assert not page.get_can_focus(), type(page).__name__
            assert not page.child_focus(Gtk.DirectionType.TAB_FORWARD), type(page).__name__


def test_the_done_page_buttons_are_out_of_reach_until_done(window):
    """Enter on a focused "Reboot Now" reboots the computer."""
    done = next(p for p in pages(window) if type(p).__name__ == "BootcDone")
    visited = _tab_walk(window)
    assert not any(w.is_ancestor(done) for w in visited)
    assert not done.grab_focus()


def test_containment_follows_the_carousel(window):
    """After Next, the new page takes focus and Welcome no longer can; after
    Back, the other way round. Focus left on the old page is dropped."""
    welcome = current_page(window)
    _tab_walk(window, presses=3)

    second = go(window, +1)
    assert second is not welcome
    focus = window.get_focus()
    assert focus is None or not focus.is_ancestor(welcome), "focus stayed on the page that left"
    assert second.get_can_focus() and not welcome.get_can_focus()
    visited = _tab_walk(window)
    assert not any(w.is_ancestor(welcome) for w in visited)

    assert go(window, -1) is welcome
    assert welcome.get_can_focus() and not second.get_can_focus()
    visited = _tab_walk(window)
    assert any(w.is_ancestor(welcome) for w in visited)


def test_a_rebuilt_carousel_is_contained_too(window):
    """rebuild_ui() takes pages out and puts them back without a
    page-changed signal."""
    window.rebuild_ui_after_image()
    pump(0.05)
    here = current_page(window)
    assert here.get_can_focus()
    assert [p for p in pages(window) if p is not here and p.get_can_focus()] == []
    _tab_walk(window)
