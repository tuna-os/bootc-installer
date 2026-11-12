"""The shipped catalogs load, and translate (#300).

Each po/<lang>.po is compiled the way the Flatpak compiles it (msgfmt into
<localedir>/<lang>/LC_MESSAGES/tuna-installer-xfce.mo), and i18n.py, as the
app imports it, must then find the catalog for the locale and translate a
known string. The run is in a child process: i18n.py picks its catalog once,
at import, from the locale variables.
"""

import glob
import json
import os
import shutil
import subprocess
import sys

import pytest

XFCE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(XFCE, "flatpak", "org.tunaos.InstallerXfce.json")
CATALOGS = sorted(glob.glob(os.path.join(XFCE, "po", "*.po")))

# A string of every UI and its French translation in po/fr.po (taken from
# the GNOME frontend's po/fr.po).
KNOWN = {"fr": ("fr_FR.UTF-8", "Back", "Retour")}

PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
from tuna_installer_xfce import i18n
print(json.dumps({"text": i18n._(sys.argv[2]), "type": type(i18n._translation).__name__}))
"""


def _compile(localedir, po):
    lang = os.path.splitext(os.path.basename(po))[0]
    out = os.path.join(localedir, lang, "LC_MESSAGES", "tuna-installer-xfce.mo")
    os.makedirs(os.path.dirname(out))
    subprocess.run(["msgfmt", "--check", "-o", out, po], check=True)
    return lang


def _run(localedir, lang_env, msgid):
    env = {k: v for k, v in os.environ.items()
           if k not in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")}
    env.update(lang_env, TUNA_INSTALLER_LOCALEDIR=localedir)
    out = subprocess.run([sys.executable, "-c", PROBE, XFCE, msgid], env=env,
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def test_a_catalog_ships():
    assert [os.path.basename(p) for p in CATALOGS], "no po/<lang>.po in this frontend"
    assert "fr" in KNOWN and os.path.join(XFCE, "po", "fr.po") in CATALOGS


def test_msgfmt_is_there():
    # The Flatpak (org.gnome.Sdk) and the CI job have it; without it the
    # tests below cannot prove anything.
    assert shutil.which("msgfmt"), "install gettext"


@pytest.mark.parametrize("lang", sorted(KNOWN))
def test_the_shipped_catalog_loads_and_translates(tmp_path, lang):
    localedir = str(tmp_path / "locale")
    for po in CATALOGS:
        _compile(localedir, po)
    locale, msgid, want = KNOWN[lang]
    got = _run(localedir, {"LANG": locale}, msgid)
    assert got == {"text": want, "type": "GNUTranslations"}
    # Another locale with no catalog shows the English text.
    assert _run(localedir, {"LANG": "C.UTF-8"}, msgid)["text"] == msgid
    # A message the catalog leaves untranslated is its own text.
    assert _run(localedir, {"LANG": locale},
                "What do you want to install?")["text"] == "What do you want to install?"


def test_the_flatpak_compiles_every_catalog_into_the_dir_i18n_reads():
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    # flatpak-builder moves share/locale into a .Locale extension by
    # default, and the OCI bundle carries the app only: keep them in.
    assert manifest.get("separate-locales") is False
    module = next(m for m in manifest["modules"]
                  if isinstance(m, dict) and m["name"] == "tuna-installer-xfce")
    commands = "\n".join(module["build-commands"])
    assert "msgfmt" in commands and "po/*.po" in commands
    assert "/app/share/locale/" in commands and "LC_MESSAGES/tuna-installer-xfce.mo" in commands
    from tuna_installer_xfce import i18n
    assert "/app/share/locale" in i18n.LOCALE_DIRS
