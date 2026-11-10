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


def test_the_identity_page_offers_only_what_it_applies(monkeypatch):
    """A Language and a Timezone combo sat here and nothing read them
    (#292). The keyboard layout is applied to the session, and says so."""
    import types

    from tuna_installer_xfce import pages

    applied = []
    monkeypatch.setattr(locale_checks, "available_keyboard_layouts", lambda: ["us", "de"])
    monkeypatch.setattr(locale_checks, "current_keyboard_layout", lambda: "us")
    monkeypatch.setattr(locale_checks, "apply_keyboard_layout", applied.append)
    monkeypatch.setattr(pages, "live_check", lambda on_result: types.SimpleNamespace(
        submit=lambda recipe: None))
    win = types.SimpleNamespace(needs_user_creation=lambda: True,
                                refresh_nav=lambda: None, selected_leaf=lambda: None)
    page = pages.IdentityPage(win)
    assert not hasattr(page, "lang_combo")
    assert not hasattr(page, "tz_combo")
    assert not hasattr(page, "locale_selection")
    assert "this session only" in page.locale_expander.get_label()
    page.kb_combo.set_active_id("de")
    assert applied == ["de"]
