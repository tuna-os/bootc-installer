"""Language rows name the country, not its code (installer standard A2:
no locale codes shown to people). Names come from iso-codes, which GNOME's
runtime ships at /usr/share/iso-codes/json."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import locale as locale_checks  # noqa: E402


@pytest.fixture
def iso(tmp_path, monkeypatch):
    (tmp_path / "iso_3166-1.json").write_text(json.dumps({"3166-1": [
        {"alpha_2": "DE", "name": "Germany"},
        {"alpha_2": "GB", "name": "United Kingdom"},
        {"alpha_2": "TW", "name": "Taiwan, Province of China", "common_name": "Taiwan"},
    ]}), encoding="utf-8")
    (tmp_path / "iso_639-3.json").write_text(json.dumps({"639-3": [
        {"alpha_3": "fil", "name": "Filipino"},
        {"alpha_3": "yor", "alpha_2": "yo", "name": "Yoruba"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(locale_checks, "ISO_CODES_DIRS", (str(tmp_path),))
    monkeypatch.setattr(locale_checks, "_iso", {})


@pytest.mark.parametrize("name, label", [
    ("de_DE.UTF-8", "Deutsch (Germany)"),
    ("en_GB.UTF-8", "English (United Kingdom)"),
    ("zh_TW.UTF-8", "中文 (Taiwan)"),
    ("yo_NG.UTF-8", "Yoruba (NG)"),
    ("fil_PH.UTF-8", "Filipino (PH)"),
    ("de.UTF-8", "Deutsch"),
    ("xx_YY.UTF-8", "xx_YY.UTF-8"),
])
def test_a_language_row_names_its_country(iso, name, label):
    assert locale_checks.language_label(name) == label


def test_without_iso_codes_the_code_stays(monkeypatch):
    monkeypatch.setattr(locale_checks, "ISO_CODES_DIRS", ())
    monkeypatch.setattr(locale_checks, "_iso", {})
    assert locale_checks.language_label("de_DE.UTF-8") == "Deutsch (DE)"


@pytest.mark.skipif(not os.path.isdir("/usr/share/iso-codes/json"), reason="no iso-codes here")
def test_the_real_iso_codes_read(monkeypatch):
    monkeypatch.setattr(locale_checks, "_iso", {})
    assert locale_checks.language_label("fr_FR.UTF-8") == "Français (France)"
