"""One gettext domain, and a template that describes this tree (#311).

51 `.po` files shipped and none was ever loaded: meson built the catalogs as
`vanilla-installer`, the launcher bound `bootc_installer`, POTFILES listed
files of another project, and Python's own gettext was never pointed at a
domain at all.
"""

import gettext
import importlib.util
import pathlib
import re
import shutil
import struct
import subprocess
import sys

import pytest

from bootc_installer.utils import i18n

ROOT = pathlib.Path(__file__).resolve().parents[2]
PO = ROOT / "po"

_spec = importlib.util.spec_from_file_location("update_pot", PO / "update-pot.py")
update_pot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_pot)


def _meson_domain():
    match = re.search(r"i18n\.gettext\(\s*'([^']+)'", (PO / "meson.build").read_text())
    assert match, "po/meson.build has no i18n.gettext() call"
    return match.group(1)


# ── one domain ───────────────────────────────────────────────────────────────

def test_meson_builds_the_domain_the_launcher_binds():
    assert _meson_domain() == i18n.DOMAIN


def test_the_launcher_binds_through_the_one_module():
    text = (ROOT / "bootc_installer" / "bootc-installer.in").read_text()
    assert "from bootc_installer.utils import i18n" in text
    assert "i18n.bind(localedir)" in text
    # No second place that could name another domain.
    assert not re.search(r"\b(bindtextdomain|textdomain|gettext\.install)\s*\(", text)


def test_no_other_module_names_a_domain():
    offenders = []
    for path in (ROOT / "bootc_installer").rglob("*.py"):
        if path.name == "i18n.py":
            continue
        if re.search(r"\b(bindtextdomain|textdomain)\s*\(", path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_the_settings_schema_uses_the_same_domain():
    schema = (ROOT / "data" / "org.bootcinstaller.Installer.gschema.xml").read_text()
    assert re.search(r'gettext-domain="([^"]+)"', schema).group(1) == i18n.DOMAIN


def test_the_template_is_named_after_the_domain():
    assert [p.name for p in PO.glob("*.pot")] == [f"{i18n.DOMAIN}.pot"]


# ── the binding really translates ────────────────────────────────────────────

def _write_mo(path, catalog):
    """A minimal GNU .mo file: no msgfmt needed."""
    catalog = {"": "Content-Type: text/plain; charset=UTF-8\n", **catalog}
    keys = sorted(catalog)
    ids = [k.encode() for k in keys]
    strs = [catalog[k].encode() for k in keys]
    n = len(keys)
    id_table, str_table = 28, 28 + 8 * n
    offset = str_table + 8 * n
    index, blob = [], b""
    for chunk in ids + strs:
        index.append((len(chunk), offset + len(blob)))
        blob += chunk + b"\0"
    data = struct.pack("<Iiiiiii", 0x950412DE, 0, n, id_table, str_table, 0, 0)
    for length, where in index:
        data += struct.pack("<ii", length, where)
    path.parent.mkdir(parents=True)
    path.write_bytes(data + blob)


def test_bind_makes_the_modules_underscore_translate(tmp_path, monkeypatch):
    """The modules do `from gettext import gettext as _`. That reads Python's
    default domain, which gettext.install() does not set: with only the old
    three lines in the launcher, this stayed English even with the right
    name."""
    _write_mo(tmp_path / "de" / "LC_MESSAGES" / f"{i18n.DOMAIN}.mo", {"Weak": "Schwach"})
    monkeypatch.setenv("LANGUAGE", "de")
    before = gettext.textdomain()
    try:
        i18n.bind(str(tmp_path))
        from gettext import gettext as _
        assert gettext.textdomain() == i18n.DOMAIN
        assert _("Weak") == "Schwach"
        assert _("Not in the catalog") == "Not in the catalog"
    finally:
        gettext.textdomain(before)


# ── POTFILES and the template ────────────────────────────────────────────────

def test_every_path_in_potfiles_exists():
    listed = update_pot.listed_files()
    assert listed, "po/POTFILES is empty"
    missing = [path for path in listed if not (ROOT / path).is_file()]
    assert missing == [], "po/POTFILES names files that are not in the tree"
    assert len(listed) == len(set(listed))


def test_potfiles_lists_every_source_that_can_hold_a_string():
    """A new page or template is in POTFILES, or its strings never reach a
    translator. Regenerate with `python3 po/update-pot.py`."""
    assert (PO / "POTFILES").read_text() == update_pot.potfiles_text()
    listed = set(update_pot.listed_files())
    for must in ("bootc_installer/defaults/qr_companion.py", "bootc_installer/utils/phone_companion.py",
                 "bootc_installer/views/recovery_key.py", "bootc_installer/gtk/recovery-key.blp",
                 "bootc_installer/gtk/window.blp", "data/org.bootcinstaller.Installer.desktop.in"):
        assert must in listed, must


def test_every_language_in_linguas_has_a_catalog():
    languages = (PO / "LINGUAS").read_text().split()
    assert languages
    assert sorted(languages) == sorted(p.stem for p in PO.glob("*.po"))


def test_the_template_has_the_strings_the_old_one_never_saw():
    msgids = {msgid for _ctxt, msgid, _plural in update_pot.messages(PO / f"{i18n.DOMAIN}.pot")}
    for msgid in (
        # the password strength labels and the disk page strings of #311
        "Weak", "Fair", "Good", "Strong", "Btrfs (with subvolumes)",
        "LVM volume group: %s", "LVM physical volume: %s",
        # the phone companion page and its form
        "Set Up From Your Phone", "Phone Setup Unavailable", "Confirm Password",
        "Show passwords", "The passwords do not match.",
    ):
        assert msgid in msgids, msgid
    assert any("recovery key" in m.lower() for m in msgids)
    assert not any("Vanilla" in m for m in msgids), "a string of the project this was forked from"


def test_the_named_strings_are_wrapped_at_their_source():
    user = (ROOT / "bootc_installer/defaults/user.py").read_text()
    for label in ("Weak", "Fair", "Good", "Strong"):
        assert f'_("{label}")' in user
    disk = (ROOT / "bootc_installer/defaults/disk.py").read_text()
    assert '"LVM volume group: " +' not in disk and '"LVM physical volume: " +' not in disk
    assert '_("Btrfs (with subvolumes)")' in disk


def test_translations_survived_the_new_template():
    """The .po files were merged, not thrown away."""
    de = (PO / "de.po").read_text(encoding="utf-8")
    assert len(re.findall(r'^msgstr "[^"]', de, flags=re.MULTILINE)) > 50
    assert 'msgid "Next"' in de


def test_the_template_is_current():
    """The same check CI runs (`python3 po/update-pot.py --check`): the
    messages in the template are the messages in the tree."""
    if shutil.which("xgettext") is None or update_pot.missing_its_rules():
        pytest.skip("needs gettext, appstream and libglib2.0-dev; the UI job in "
                    "python-test.yml runs this check where they are installed")
    result = subprocess.run([sys.executable, str(PO / "update-pot.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
