"""The phone companion page against real GTK, in the real window.

The QR code is a Gdk.Texture made from in-memory PNG bytes, black on white
with a quiet zone; without segno the page falls back to the link; the
token-bearing URL never lands in a widget the user can read.

Each test opens the real BootcWindow on the shipped recipe.json and moves
the carousel to the companion page, as a user does: the page starts its
server because it is the page on screen (#321). The tests used to build
the page alone with a step number and call its private start method, so
they could not see where the window starts it. Only the server is a
stand-in (RecordingServer): no test binds a port or runs openssl.
"""

import contextlib
from unittest.mock import patch

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from bootc_installer.defaults import qr_companion as mod

from ._real_window import (
    RecordingServer,
    current_page,
    go,
    go_to_before,
    page_by_key,
    real_window,
    shipped_recipe,
    wait_for,
)

# What RecordingServer hands out when it starts.
TOKEN = "window-test-token"
ADDRESS = "192.0.2.10:8443"


@pytest.fixture()
def companion(tmp_path):
    """Open the window and go to the companion page. Yields a function of
    (start_ok, segno), so that each test picks the server's answer."""
    with contextlib.ExitStack() as stack:
        def open_page(start_ok=True, segno=mod.segno):
            stack.enter_context(patch.object(mod, "segno", segno))
            window = stack.enter_context(
                real_window(tmp_path, shipped_recipe(needs_user_creation=True)))
            RecordingServer.start_result = start_ok
            page = page_by_key(window, "qr_companion")
            assert page is not None
            go_to_before(window, "qr_companion")
            assert not RecordingServer.any_running()
            go(window, +1)
            assert current_page(window) is page
            assert RecordingServer.any_running() is start_ok
            return page
        yield open_page


def _strings(widget, acc=None):
    """Every string any widget under `widget` carries, visible or not."""
    acc = [] if acc is None else acc
    if isinstance(widget, Gtk.Label):
        acc.append(widget.get_label() or "")
    if isinstance(widget, Gtk.Button):
        acc.append(widget.get_label() or "")
    if isinstance(widget, Adw.StatusPage):
        acc += [widget.get_title() or "", widget.get_description() or ""]
    acc.append(widget.get_tooltip_text() or "")
    child = widget.get_first_child()
    while child is not None:
        _strings(child, acc)
        child = child.get_next_sibling()
    return acc


def _pixel(texture, x, y):
    """(R, G, B) of one texel."""
    downloader = Gdk.TextureDownloader.new(texture)
    downloader.set_format(Gdk.MemoryFormat.R8G8B8)
    data, stride = downloader.download_bytes()
    buf = data.get_data()
    i = y * stride + x * 3
    return tuple(buf[i:i + 3])


@pytest.mark.skipif(mod.segno is None, reason="segno not installed")
def test_qr_is_a_crisp_black_on_white_texture(companion):
    page = companion()
    assert page.state_stack.get_visible_child_name() == "companion"
    assert page.qr_stack.get_visible_child_name() == "code"
    texture = page.qr_picture.get_paintable()
    assert isinstance(texture, Gdk.Texture)

    url = f"https://{ADDRESS}/?token={TOKEN}"
    modules = mod.segno.make_qr(url, error="m").symbol_size(
        scale=1, border=mod.QR_QUIET_ZONE)[0]
    assert texture.get_width() == texture.get_height()
    assert texture.get_width() % modules == 0, "whole pixels per module"
    px = texture.get_width() // modules
    edge = texture.get_width() // mod.QR_OVERSAMPLE
    assert edge <= mod.QR_TARGET_SIZE
    assert page.qr_picture.get_size_request() == (edge, edge)

    q = mod.QR_QUIET_ZONE * px
    assert _pixel(texture, 0, 0) == (255, 255, 255), "quiet zone is white"
    assert _pixel(texture, q - 1, q - 1) == (255, 255, 255)
    assert _pixel(texture, q, q) == (0, 0, 0), "finder corner is black"
    assert _pixel(texture, q + 3 * px, q + 3 * px) == (0, 0, 0)


def test_without_segno_the_page_offers_the_link(companion):
    page = companion(segno=None)
    assert page.state_stack.get_visible_child_name() == "companion"
    assert page.qr_stack.get_visible_child_name() == "nocode"
    assert page.qr_picture.get_paintable() is None
    assert page.address_label.get_text() == ADDRESS
    assert page.copy_button.get_sensitive()


@pytest.mark.parametrize("segno", [mod.segno, None])
def test_the_token_is_never_in_a_label(companion, segno):
    page = companion(segno=segno)
    strings = _strings(page)
    assert ADDRESS in strings
    for s in strings:
        assert TOKEN not in s, f"token on screen: {s!r}"
        assert "token=" not in s, f"full URL on screen: {s!r}"


def test_copy_link_copies_the_full_url(companion):
    page = companion(segno=None)
    with patch.object(mod.GLib, "timeout_add_seconds", return_value=0):
        page.copy_button.emit("clicked")
    clipboard = Gdk.Display.get_default().get_clipboard()
    got = {}
    loop = GLib.MainLoop()

    def done(cb, res):
        got["text"] = cb.read_text_finish(res)
        loop.quit()

    clipboard.read_text_async(None, done)
    GLib.timeout_add(2000, loop.quit)
    loop.run()
    assert got.get("text") == f"https://{ADDRESS}/?token={TOKEN}"


def test_skip_is_a_plain_button(companion):
    page = companion()
    assert not page.btn_next.has_css_class("suggested-action")
    page.btn_next.emit("clicked")
    # Skip moves on, and the server stops with the page.
    wait_for(lambda: not RecordingServer.any_running(), what="the server to stop")


def test_unavailable_is_a_status_page(companion):
    page = companion(start_ok=False)
    assert page.state_stack.get_visible_child_name() == "unavailable"
    assert isinstance(page.state_stack.get_visible_child(), Adw.StatusPage)
    assert "Unavailable" in page.unavailable_page.get_title()
    assert not page.copy_button.get_sensitive()
