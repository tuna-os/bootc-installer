"""Each non-GNOME frontend ships a translation catalog that is current (#300).

shared/i18n/catalogs.py writes a catalog per frontend and language from the
frontend's template and the GNOME frontend's po/<lang>.po. These tests fail
when a shipped catalog is stale, hold the merge rules (a translator's work
stays, GNOME's fuzzy entries are not used, nothing is invented), and check
that each frontend ships the same seed language. Each frontend has its own
test that the catalog loads in its toolkit: test_backend
(shippedCatalogLoadsAndTranslates, KDE), translations/tests/test_catalog.cpp
(Niri), tests/test_catalogs.py (XFCE) and i18n.rs (COSMIC).
"""

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared" / "i18n"))

_spec = importlib.util.spec_from_file_location("i18n_catalogs",
                                               ROOT / "shared" / "i18n" / "catalogs.py")
catalogs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(catalogs)

# The language every frontend ships first: one of the most complete
# po/<lang>.po files of the GNOME frontend (shared/i18n/README.md).
SEED = "fr"


@pytest.mark.parametrize("name", sorted(catalogs.CATALOGS))
def test_the_frontend_ships_the_seed_catalog(name):
    assert SEED in catalogs.CATALOGS[name].languages()


@pytest.mark.parametrize("name", sorted(catalogs.CATALOGS))
def test_every_shipped_catalog_is_current(name):
    c = catalogs.CATALOGS[name]
    for lang in c.languages():
        problems = c.problems(lang)
        assert problems == [], "\n".join(problems) + \
            f"\n  run: python3 shared/i18n/catalogs.py {lang} {name}"


@pytest.mark.parametrize("name", sorted(catalogs.CATALOGS))
def test_the_seed_catalog_has_every_gnome_translation_and_no_other(name):
    """Built today from GNOME's po/fr.po, the catalog is the shipped one:
    every identical, translated, not fuzzy GNOME string is in it, and no
    message has a translation GNOME does not have (nothing was invented)."""
    c = catalogs.CATALOGS[name]
    have = c.read(c.file(SEED).read_text(encoding="utf-8"))
    assert have == c.read(c.build(SEED))
    gnome, _header = catalogs.gnome_translations(SEED)
    translated = 0
    for message in c.messages():
        value = have[c.key(message)]
        found = gnome.get(c._gnome_key(message))
        if found:
            assert value in (found, found[0]), message
            translated += 1
        else:
            assert not value, f"{message}: a translation that is not GNOME's"
    assert translated >= 5, "the seed catalog translates almost nothing"


def test_the_seed_is_one_of_the_most_complete_gnome_languages():
    counts = {}
    for po in sorted((ROOT / "po").glob("*.po")):
        counts[po.stem] = len(catalogs.gnome_translations(po.stem)[0])
    assert counts[SEED] == max(counts.values()), counts


def test_the_po_reader_matches_msgfmt_rules(tmp_path):
    text = '''msgid ""
msgstr ""
"Language: xx\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

#, fuzzy
msgid "Fuzzy"
msgstr "Flou"

msgid "Done"
msgstr "Fait"

msgid "Empty"
msgstr ""

msgctxt "button"
msgid "Done"
msgstr "Bouton"

msgid "One file"
msgid_plural "{n} files"
msgstr[0] "Un fichier"
msgstr[1] "{n} fichiers"

msgid "Multi"
msgstr ""
"two "
"lines\\n"

#~ msgid "Gone"
#~ msgstr "Parti"
'''
    entries = catalogs.read_po(text)
    assert [e["msgid"] for e in entries] == ["", "Fuzzy", "Done", "Empty", "Done",
                                              "One file", "Multi"]
    po = tmp_path / "po"
    po.mkdir()
    (po / "xx.po").write_text(text, encoding="utf-8")
    old = catalogs.GNOME_PO
    catalogs.GNOME_PO = po
    try:
        found, header = catalogs.gnome_translations("xx")
    finally:
        catalogs.GNOME_PO = old
    assert found == {("Done", ""): ["Fait"],
                     ("One file", "{n} files"): ["Un fichier", "{n} fichiers"],
                     ("Multi", ""): ["two lines\n"]}
    assert header["Language"] == "xx"


def _scratch_target(tmp_path, monkeypatch, gnome_po):
    """The COSMIC catalogs on a scratch tree: a template with three
    messages, and a GNOME po/xx.po."""
    base = tmp_path / "frontends" / "cosmic"
    (base / "src").mkdir(parents=True)
    (base / "src" / "ui.rs").write_text(
        'pub mod copy {\n'
        '    pub const A: &str = "Back";\n'
        '    pub const B: &str = "Step {n}";\n'
        '    pub const C: &str = "Brand new";\n'
        '}\nuse copy::*;\n', encoding="utf-8")
    po = tmp_path / "po"
    po.mkdir()
    (po / "xx.po").write_text(gnome_po, encoding="utf-8")
    monkeypatch.setattr(catalogs.templates, "FRONTENDS", tmp_path / "frontends")
    monkeypatch.setattr(catalogs, "GNOME_PO", po)
    monkeypatch.setattr(catalogs, "ROOT", tmp_path)
    monkeypatch.setattr(catalogs.templates, "ROOT", tmp_path)
    return catalogs.CATALOGS["cosmic"]


GNOME_XX = '''msgid ""
msgstr "Language: xx\\n"

msgid "Back"
msgstr "Zurueck"

#, fuzzy
msgid "Step {n}"
msgstr "Schritt {n}"
'''


def test_a_new_catalog_takes_gnome_and_invents_nothing(tmp_path, monkeypatch):
    c = _scratch_target(tmp_path, monkeypatch, GNOME_XX)
    c.write("xx")
    data = json.loads(c.file("xx").read_text(encoding="utf-8"))
    # The fuzzy GNOME entry is not used; the new string stays untranslated.
    assert data == {"Back": "Zurueck", "Brand new": "", "Step {n}": ""}
    assert c.problems("xx") == []


def test_a_translators_work_stays_and_a_stale_catalog_fails(tmp_path, monkeypatch):
    c = _scratch_target(tmp_path, monkeypatch, GNOME_XX)
    c.file("xx").parent.mkdir(parents=True, exist_ok=True)
    c.file("xx").write_text(json.dumps({"Back": "Retour", "Step {n}": "Etape {n}",
                                        "Gone": "Parti"}), encoding="utf-8")
    problems = c.problems("xx")
    assert len(problems) == 1 and "1 messages missing" in problems[0] \
        and "1 no longer in the template" in problems[0]
    c.write("xx")
    data = json.loads(c.file("xx").read_text(encoding="utf-8"))
    assert data == {"Back": "Retour", "Brand new": "", "Step {n}": "Etape {n}"}
    assert c.problems("xx") == []


def test_a_translation_that_drops_a_placeholder_fails(tmp_path, monkeypatch):
    c = _scratch_target(tmp_path, monkeypatch, GNOME_XX)
    c.file("xx").parent.mkdir(parents=True, exist_ok=True)
    c.file("xx").write_text(json.dumps({"Back": "", "Brand new": "",
                                        "Step {n}": "Etape {count}"}), encoding="utf-8")
    assert any("placeholders" in p for p in c.problems("xx"))


def test_the_check_and_the_writer_run_from_the_command_line(capsys):
    assert catalogs.main(["--check"]) == 0
    assert "is current" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        catalogs.main([])          # no language to write
    with pytest.raises(SystemExit):
        catalogs.main(["--check", "fr"])


def test_a_qt_catalog_names_its_language_and_marks_untranslated_messages():
    c = catalogs.CATALOGS["kde"]
    text = c.file(SEED).read_text(encoding="utf-8")
    assert catalogs.ts_language(text) == SEED
    have = catalogs.read_ts(text)
    assert have[("Wizard", "Back", "", False)] == "Retour"
    assert have[("Wizard", "User Account", "", False)] == ""
    assert '<translation type="unfinished"></translation>' in text
