"""The phone companion in the real window, with the shipped recipe (#304, #305).

The page-level tests (test_qr_companion_page.py) call the page's own methods.
They could not see either defect: the server followed a step number that did
not match the carousel, and the user page read the phone's data before any
phone could have sent it. Both only show when the real BootcWindow builds the
real carousel from recipe.json.
"""

import json

import pytest

from bootc_installer.utils import phone_companion
from bootc_installer.utils.user_step import user_step_shows

from ._real_window import (
    SHIPPED_RECIPE,
    RecordingServer,
    current_page,
    go,
    go_to_before,
    page_by_key,
    pages,
    pump,
    real_window,
    shipped_recipe,
    wait_for,
)

PHONE = {"fullname": "Ada Lovelace", "username": "countess", "password": "an4lytical-Engine!",
         "hostname": "engine-room"}


@pytest.fixture(autouse=True)
def _clean_companion_state():
    phone_companion.GLOBAL_CONFIG = None
    phone_companion.CONFIG_RECEIVED_EVENT.clear()
    yield
    phone_companion.GLOBAL_CONFIG = None
    phone_companion.CONFIG_RECEIVED_EVENT.clear()


def _step_pages(window):
    return [p for p in pages(window) if getattr(p, "_bootc_step_key", None)]


def _walk_and_check(window):
    """Forward over every step page and back again. At each stop, the server
    runs if and only if the companion page is the one on screen."""
    companion = page_by_key(window, "qr_companion")
    seen = []

    def check():
        page = current_page(window)
        seen.append(getattr(page, "_bootc_step_key", type(page).__name__))
        assert RecordingServer.any_running() == (page is companion), (
            f"on {seen[-1]!r}: server running={RecordingServer.any_running()}, visited {seen}")

    check()
    for _ in range(len(_step_pages(window)) - 1):
        go(window, +1)
        check()
    for _ in range(len(_step_pages(window)) - 1):
        go(window, -1)
        check()
    return seen


def test_the_server_runs_only_on_the_companion_page(tmp_path):
    """#304, with recipe.json as shipped except that the image needs an
    account, so the companion has a reason to show."""
    with real_window(tmp_path, shipped_recipe(needs_user_creation=True)) as window:
        companion = page_by_key(window, "qr_companion")
        assert companion is not None and page_by_key(window, "user") is not None
        assert current_page(window)._bootc_step_key == "welcome"
        assert not RecordingServer.any_running(), "the server started on the Welcome page"

        seen = _walk_and_check(window)
        assert seen.count("qr_companion") == 2

        # First visit: the code is there at once, not after Back and forward.
        go_to_before(window, "qr_companion")
        go(window, +1)
        assert current_page(window) is companion
        assert companion.state_stack.get_visible_child_name() == "companion"
        assert companion.copy_button.get_sensitive()
        assert companion.address_label.get_text() == "192.0.2.10:8443"
        go(window, +1)
        assert not RecordingServer.any_running()
        assert all(s.started == s.stopped for s in RecordingServer.instances if s.started)


def test_the_shipped_recipe_exactly(tmp_path):
    """recipe.json byte for byte. Whatever it says about the account, the
    companion page follows the user page, and the server follows the
    companion page."""
    with open(SHIPPED_RECIPE, encoding="utf-8") as f:
        shipped = json.load(f)
    with real_window(tmp_path) as window:
        expected = bool(user_step_shows(window, {"sys_recipe": window.recipe}))
        assert (page_by_key(window, "user") is not None) == expected
        if "qr_companion" in shipped["steps"]:
            assert (page_by_key(window, "qr_companion") is not None) == expected, (
                "the companion asks for an account exactly when the user page does")
        seen = _walk_and_check(window)
        if not expected:
            assert "qr_companion" not in seen
            assert RecordingServer.instances == [] or not any(
                s.started for s in RecordingServer.instances)


def test_the_companion_hides_when_no_account_is_created(tmp_path):
    """#305: the page used to show, and ask for an account that was never
    created."""
    with real_window(tmp_path, shipped_recipe(needs_user_creation=False)) as window:
        assert page_by_key(window, "user") is None
        assert page_by_key(window, "qr_companion") is None
        _walk_and_check(window)
        assert not any(s.started for s in RecordingServer.instances)


def test_account_from_the_phone_reaches_the_user_page_and_the_finals(tmp_path):
    """#305: the phone said "Setup Completed!" and the user reached an empty
    Create User page."""
    with real_window(tmp_path, shipped_recipe(needs_user_creation=True)) as window:
        companion = page_by_key(window, "qr_companion")
        user = page_by_key(window, "user")
        assert user.username_entry.get_text() == "" and user.password_entry.get_text() == ""

        go_to_before(window, "qr_companion")
        go(window, +1)
        assert current_page(window) is companion and RecordingServer.any_running()
        here = window.carousel.get_position()

        # What CompanionRequestHandler.do_POST does with an accepted form.
        phone_companion.GLOBAL_CONFIG = dict(PHONE)
        phone_companion.CONFIG_RECEIVED_EVENT.set()

        # The page's own poll sees it, stops the server and moves on.
        wait_for(lambda: window.carousel.get_position() == here + 1,
                 what="the companion page to move on by itself")
        assert not RecordingServer.any_running()
        assert window.companion_config == PHONE

        while current_page(window) is not user:
            go(window, +1)
        pump(0.05)

        assert user.fullname_entry.get_text() == PHONE["fullname"]
        assert user.username_entry.get_text() == PHONE["username"], (
            "the username from the phone wins over the one suggested from the name")
        assert user.password_entry.get_text() == PHONE["password"]
        assert user.password_confirmation.get_text() == PHONE["password"]

        window.update_finals()
        finals = window.finals
        account = next(f["user"] for f in finals if isinstance(f, dict) and "user" in f)
        assert account["username"] == PHONE["username"]
        assert account["fullname"] == PHONE["fullname"]
        assert account["password"] == PHONE["password"]
        assert {"hostname": PHONE["hostname"]} in finals
        assert not any("sshkey" in json.dumps(f) for f in finals)


def test_a_later_visit_keeps_what_the_user_typed(tmp_path):
    """The phone's data applies once. Going Back and forward again must not
    put the phone's password back over a correction typed here."""
    with real_window(tmp_path, shipped_recipe(needs_user_creation=True)) as window:
        user = page_by_key(window, "user")
        window.companion_config = dict(PHONE)
        while current_page(window) is not user:
            go(window, +1)
        assert user.username_entry.get_text() == PHONE["username"]

        user.username_entry.set_text("ada")
        go(window, -1)
        go(window, +1)
        assert current_page(window) is user
        assert user.username_entry.get_text() == "ada"

        # A second scan is a new submission, and applies.
        window.companion_config = {**PHONE, "username": "lovelace"}
        go(window, -1)
        go(window, +1)
        assert user.username_entry.get_text() == "lovelace"


def test_no_route_shows_unavailable_and_no_address(tmp_path):
    """#306: without a LAN address the page says so. It shows no code and no
    127.0.0.1."""
    with real_window(tmp_path, shipped_recipe(needs_user_creation=True)) as window:
        RecordingServer.start_result = False
        companion = page_by_key(window, "qr_companion")
        go_to_before(window, "qr_companion")
        go(window, +1)
        assert current_page(window) is companion
        assert companion.state_stack.get_visible_child_name() == "unavailable"
        assert "network" in companion.unavailable_page.get_description()
        assert companion.address_label.get_text() == ""
        assert not companion.copy_button.get_sensitive()
        assert not RecordingServer.any_running()


def _choose_catalog_image(window, needs_account):
    """Select a catalog image on the image page and press its Next, as the
    user does. Returns False when the catalog has no such image."""
    image = page_by_key(window, "image")
    rows = [row for row in image._BootcDefaultImage__leaf_rows if bool(row[6]) == needs_account]
    if not rows:
        return False
    rows[0][1].set_active(True)
    pump()
    assert image.get_finals()["needs_user_creation"] == needs_account
    image.btn_next.emit("clicked")
    pump(0.3)
    return True


def test_the_shipped_recipe_decides_the_companion_from_the_image_chosen(tmp_path):
    """#315 with #305: the shipped recipe has an image step, so whether an
    account is made is known only after the image is chosen. The companion
    and the account page follow that choice, and both come after the image
    page."""
    with real_window(tmp_path) as window:
        assert page_by_key(window, "image") is not None
        if not _choose_catalog_image(window, needs_account=True):
            pytest.skip("the catalog has no image that needs an account")
        keys = [getattr(p, "_bootc_step_key", "") for p in pages(window)]
        assert "qr_companion" in keys and "user" in keys
        assert keys.index("image") < keys.index("qr_companion") < keys.index("user")
        assert not RecordingServer.any_running(), "the server ran before its page"

    with real_window(tmp_path) as window:
        if not _choose_catalog_image(window, needs_account=False):
            pytest.skip("each catalog image needs an account")
        assert page_by_key(window, "qr_companion") is None
        assert page_by_key(window, "user") is None
        assert not any(s.started for s in RecordingServer.instances)
