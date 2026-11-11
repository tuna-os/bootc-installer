"""Locale detection and the connectivity probe (locale.py).

Every external command has a fallback: localectl/timedatectl are absent
from minimal live media and from this container, so these tests pin the
fallback path as well as the parsing path.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import locale as locale_checks  # noqa: E402


def test_language_falls_back_without_localectl(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("no localectl here")

    monkeypatch.setattr(locale_checks.subprocess, "run", fail)
    assert locale_checks.available_languages() == ["C", "en_US.UTF-8"]


def test_language_parses_localectl_output(monkeypatch):
    class Out:
        returncode = 0
        stdout = "C.UTF-8\nen_US.UTF-8\npt_BR.UTF-8\n"

    monkeypatch.setattr(locale_checks.subprocess, "run",
                        lambda *a, **k: Out())
    assert locale_checks.available_languages() == [
        "C.UTF-8", "en_US.UTF-8", "pt_BR.UTF-8"]


def test_current_language_prefers_lc_all(monkeypatch):
    monkeypatch.setenv("LC_ALL", "pt_BR.UTF-8")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert locale_checks.current_language() == "pt_BR.UTF-8"


def test_keyboard_layout_parses_setxkbmap(monkeypatch):
    class Out:
        returncode = 0
        stdout = "rules: evdev\nlayout: de\nvariant: ,\n"

    monkeypatch.setattr(locale_checks.subprocess, "run",
                        lambda *a, **k: Out())
    assert locale_checks.current_keyboard_layout() == "de"


def test_keyboard_layout_falls_back_to_us(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("no setxkbmap on Wayland")

    monkeypatch.setattr(locale_checks.subprocess, "run", fail)
    assert locale_checks.current_keyboard_layout() == "us"
    assert "us" in locale_checks.available_keyboard_layouts()


def test_apply_keyboard_reports_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("no setxkbmap")

    monkeypatch.setattr(locale_checks.subprocess, "run", fail)
    assert locale_checks.apply_keyboard_layout("de") is False


def test_timezone_reads_localtime_symlink(monkeypatch):
    import os as _os
    monkeypatch.setattr(_os, "readlink",
                        lambda p: "/usr/share/zoneinfo/Europe/Lisbon")
    assert locale_checks.current_timezone() == "Europe/Lisbon"

    def fail(path):
        raise OSError("no /etc/localtime")

    monkeypatch.setattr(_os, "readlink", fail)
    assert locale_checks.current_timezone() == "UTC"


def test_connectivity_skip_env_short_circuits(monkeypatch):
    monkeypatch.setenv("TUNA_INSTALLER_SKIP_CONN_CHECK", "1")
    assert locale_checks.has_connectivity() is True


def test_connectivity_failure_is_false(monkeypatch):
    monkeypatch.delenv("TUNA_INSTALLER_SKIP_CONN_CHECK", raising=False)
    monkeypatch.delenv("VANILLA_SKIP_CONN_CHECK", raising=False)

    def fail(*args, **kwargs):
        raise OSError("no route")

    monkeypatch.setattr(locale_checks.socket, "create_connection", fail)
    assert locale_checks.has_connectivity(timeout=1) is False


def test_needs_network_mirrors_conn_check_should_show():
    assert locale_checks.needs_network(False) is True
    assert locale_checks.needs_network(True) is False


def _identity_page(monkeypatch, submitted=None):
    import types

    from tuna_installer_xfce import pages

    applied = []
    monkeypatch.setattr(locale_checks, "available_languages", lambda: ["C.UTF-8", "de_DE.UTF-8"])
    monkeypatch.setattr(locale_checks, "available_keyboard_layouts", lambda: ["us", "de"])
    monkeypatch.setattr(locale_checks, "available_timezones", lambda: ["UTC", "Europe/Berlin"])
    monkeypatch.setattr(locale_checks, "apply_keyboard_layout", applied.append)
    sent = submitted if submitted is not None else []
    monkeypatch.setattr(pages, "live_check", lambda on_result: types.SimpleNamespace(
        submit=sent.append))
    win = types.SimpleNamespace(needs_user_creation=lambda: True,
                                refresh_nav=lambda: None, selected_leaf=lambda: None)
    return pages.IdentityPage(win), applied


def test_the_identity_page_writes_only_what_the_person_picked(monkeypatch):
    """The language, keyboard and time zone reach the installed system
    (#292). Each combo starts at "keep", which writes no key."""
    sent = []
    page, applied = _identity_page(monkeypatch, sent)
    assert "this session" not in page.locale_expander.get_label()
    assert page.region_fields() == {}
    assert "locale" not in page.partial_recipe()
    page.lang_combo.set_active_id("de_DE.UTF-8")
    page.kb_combo.set_active_id("de")
    page.tz_combo.set_active_id("Europe/Berlin")
    assert page.region_fields() == {"locale": "de_DE.UTF-8", "keyboard": {"layout": "de"},
                                    "timezone": "Europe/Berlin"}
    # fisherman checks each pick (`validate --partial`).
    assert sent[-1]["timezone"] == "Europe/Berlin"
    assert sent[-1]["keyboard"] == {"layout": "de"}
    # The keyboard also switches this live session.
    assert applied == ["de"]
    page.kb_combo.set_active_id("")
    assert "keyboard" not in page.region_fields()


def test_a_region_problem_holds_the_page(monkeypatch):
    page, _applied = _identity_page(monkeypatch)
    page.hostname.set_text("box")
    page.username.set_text("jo")
    page.password.set_text("pw")
    page.password2.set_text("pw")
    page._on_checked([], None)
    assert page.can_continue()
    page._on_checked([{"field": "keyboard.layout", "code": "keyboard_layout_invalid",
                       "message": "bad"}], None)
    assert not page.can_continue()
    assert page.region_problem.get_text()


def test_build_recipe_writes_the_three_keys():
    from tuna_installer_xfce import core

    recipe = core.build_recipe(disk="/dev/vda", filesystem="xfs")
    for key in ("locale", "keyboard", "timezone"):
        assert key not in recipe
    recipe = core.build_recipe(disk="/dev/vda", filesystem="xfs", locale="de_DE.UTF-8",
                               keyboard_layout="de", timezone="Europe/Berlin")
    assert (recipe["locale"], recipe["keyboard"], recipe["timezone"]) == (
        "de_DE.UTF-8", {"layout": "de"}, "Europe/Berlin")
    assert core.is_region_field("keyboard.variant")
    assert not core.is_region_field("hostname")


# ─── which host the connectivity check asks (#301) ──────────────────────────

def test_the_registry_of_the_selected_image_is_probed_first():
    assert locale_checks.connectivity_targets("quay.io/centos-bootc/centos-bootc:c10s") == [
        ("quay.io", 443), ("ghcr.io", 443), ("8.8.8.8", 53)]
    # No duplicate when the image is on the shared registry.
    assert locale_checks.connectivity_targets("ghcr.io/example/os:latest") == [
        ("ghcr.io", 443), ("8.8.8.8", 53)]
    # No image (live media): the shared targets.
    assert locale_checks.connectivity_targets("") == list(locale_checks.SHARED_TARGETS)


def test_registry_target_reads_a_reference():
    target = locale_checks.registry_target
    assert target("registry.example:5000/os/atlas:stable") == ("registry.example", 5000)
    assert target("localhost/os:1") == ("localhost", 443)
    assert target("docker://quay.io/fedora/fedora-bootc:42") == ("quay.io", 443)
    # A name with no registry is a Docker Hub name.
    assert target("library/ubuntu:26.04") == (locale_checks.DEFAULT_REGISTRY, 443)
    assert target("ubuntu") == (locale_checks.DEFAULT_REGISTRY, 443)
    assert target("") is None


def test_has_connectivity_tries_the_targets_in_order(monkeypatch):
    monkeypatch.delenv("TUNA_INSTALLER_SKIP_CONN_CHECK", raising=False)
    monkeypatch.delenv("VANILLA_SKIP_CONN_CHECK", raising=False)
    tried = []

    class _Sock:
        def close(self):
            pass

    def connect(address, timeout=None):
        tried.append(address)
        if address == ("ghcr.io", 443):
            return _Sock()
        raise OSError("no route")

    monkeypatch.setattr(locale_checks.socket, "create_connection", connect)
    assert locale_checks.has_connectivity(timeout=1, imgref="quay.io/a/b:1") is True
    assert tried == [("quay.io", 443), ("ghcr.io", 443)]
