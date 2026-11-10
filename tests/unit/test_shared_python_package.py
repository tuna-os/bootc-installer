"""bootc_shared (shared/python/): one package for the two Python frontends.

GNOME and XFCE used to keep byte-identical copies of five modules and three
data files, and five tests compared the copies. Both now import one
package. That moves the risk from "a copy drifts" to "a build does not ship
the package or a file that it reads", which is an import error on a user's
machine and not in a checkout. These tests hold the second risk:

1. The data files that the package reads (`_data.FILES`) are in shared/,
   and each build installs each of them where `_data.path()` looks.
2. A tree laid out as an installed build has, with no checkout near it,
   every module importable and every data file found.
3. No copy came back, and each frontend imports the package.
4. The release counts a change to the package as a change to XFCE.

The real Flatpak builds are proven only by CI.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SHARED = REPO / "shared"
PACKAGE = SHARED / "python" / "bootc_shared"
MESON = SHARED / "python" / "meson.build"
XFCE_MANIFEST = REPO / "frontends" / "xfce" / "flatpak" / "org.tunaos.InstallerXfce.json"
XFCE_LIB = "/app/lib/tuna-installer-xfce"

sys.path.insert(0, str(SHARED / "python"))
from bootc_shared import _data  # noqa: E402

MODULES = sorted(p.stem for p in PACKAGE.glob("*.py") if not p.name.startswith("_"))
# The names that the copies had. A file with one of these names in a
# frontend is a copy that came back.
OLD_COPIES = ("fisherman_probe.py", "fisherman_validate.py", "progress_parser.py",
              "readiness.py", "branding.py", "encryption-choices.json",
              "dry-run-transcript.ndjson")
FRONTEND_TREES = (REPO / "bootc_installer", REPO / "frontends" / "xfce" / "tuna_installer_xfce")


def xfce_module():
    manifest = json.loads(XFCE_MANIFEST.read_text(encoding="utf-8"))
    return next(m for m in manifest["modules"] if m["name"] == "tuna-installer-xfce")


def test_the_package_has_the_contract_modules():
    for name in ("account", "branding", "probe", "progress", "readiness", "validate",
                 "catalog", "hardware", "network", "fisherman_host", "redact"):
        assert name in MODULES


@pytest.mark.parametrize("relative", _data.FILES)
def test_each_data_file_is_in_shared_and_found_in_a_checkout(relative):
    assert (SHARED / relative).is_file()
    assert pathlib.Path(_data.path(relative)) == SHARED / relative


def test_the_package_reads_no_file_that_is_not_in_the_list():
    read = set()
    for module in PACKAGE.glob("*.py"):
        read.update(re.findall(r'_data\.(?:path|load_json)\("([^"]+)"\)',
                               module.read_text(encoding="utf-8")))
    assert read == set(_data.FILES)


@pytest.mark.parametrize("relative", _data.FILES)
def test_meson_installs_each_data_file(relative):
    contract, name = relative.split("/")
    text = MESON.read_text(encoding="utf-8")
    assert re.search(
        rf"install_data\('\.\./{re.escape(contract)}/{re.escape(name)}',\s*"
        rf"install_dir: join_paths\(shared_moduledir, 'data', '{re.escape(contract)}'\)\)", text), (
        f"shared/python/meson.build does not install {relative} to data/{contract}/")


def test_meson_installs_the_package_beside_bootc_installer():
    text = MESON.read_text(encoding="utf-8")
    assert "install_subdir('bootc_shared'" in text
    assert "install_dir: shared_pkgdatadir" in text
    root = (REPO / "meson.build").read_text(encoding="utf-8")
    assert "subdir('shared/python')" in root
    # The same directory as bootc_installer, which the launchers put on sys.path.
    launcher = (REPO / "bootc_installer" / "bootc-installer.in").read_text(encoding="utf-8")
    assert "sys.path.insert(1, pkgdatadir)" in launcher
    assert ("join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())"
            in text)


def test_the_xfce_manifest_ships_the_package():
    module = xfce_module()
    sources = module["sources"]
    assert {"type": "dir", "path": "../../../shared/python/bootc_shared",
            "dest": "shared/python/bootc_shared"} in sources
    assert f"cp -r shared/python/bootc_shared {XFCE_LIB}/" in module["build-commands"]
    # The package must be beside tuna_installer_xfce: that directory is the
    # one entry the launcher puts on sys.path.
    assert f"cp -r tuna_installer_xfce {XFCE_LIB}/" in module["build-commands"]


@pytest.mark.parametrize("relative", _data.FILES)
def test_the_xfce_manifest_ships_each_data_file(relative):
    module = xfce_module()
    contract = relative.split("/")[0]
    assert {"type": "file", "path": f"../../../shared/{relative}",
            "dest": f"shared/{contract}"} in module["sources"]
    assert (f"install -Dm644 shared/{relative} {XFCE_LIB}/bootc_shared/data/{relative}"
            in module["build-commands"])


def test_each_manifest_source_exists():
    for source in xfce_module()["sources"]:
        assert (XFCE_MANIFEST.parent / source["path"]).exists(), source["path"]


def test_an_installed_tree_needs_no_checkout(tmp_path):
    """Lay the package out as both builds install it, far from the repo,
    and import each module from there."""
    shutil.copytree(PACKAGE, tmp_path / "bootc_shared",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for relative in _data.FILES:
        target = tmp_path / "bootc_shared" / "data" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SHARED / relative, target)
    script = (
        "import importlib, json, os, sys\n"
        "from bootc_shared import _data\n"
        f"for name in {MODULES!r}:\n"
        "    mod = importlib.import_module('bootc_shared.' + name)\n"
        "    assert mod.__file__.startswith(sys.argv[1]), mod.__file__\n"
        "for relative in _data.FILES:\n"
        "    assert _data.path(relative).startswith(os.path.join(sys.argv[1], 'bootc_shared', 'data')), relative\n"
        "from bootc_shared import account, branding, progress, validate\n"
        "print(json.dumps([len(branding.COPY_DEFAULTS), len(validate.load_choices()),\n"
        "                  account.DEFAULT_GROUPS, os.path.isfile(progress.transcript_path())]))\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c",
                           "import sys; sys.path.insert(0, sys.argv[1]); " + "exec(sys.argv[2])",
                           str(tmp_path), script],
                          capture_output=True, text=True, cwd=tmp_path, check=False)
    assert done.returncode == 0, done.stderr
    defaults, choices, groups, transcript = json.loads(done.stdout)
    assert defaults > 10 and choices >= 4 and "wheel" in groups and transcript


def test_a_package_without_its_data_fails_at_import(tmp_path):
    """A build that forgets a data file must fail at start, where the
    packaged tests and the E2E gate see it, not on the page that reads it."""
    shutil.copytree(PACKAGE, tmp_path / "bootc_shared",
                    ignore=shutil.ignore_patterns("__pycache__"))
    done = subprocess.run([sys.executable, "-I", "-c",
                           "import sys; sys.path.insert(0, sys.argv[1]); import bootc_shared.branding",
                           str(tmp_path)], capture_output=True, text=True, cwd=tmp_path, check=False)
    assert done.returncode != 0
    assert "copy-defaults.json" in done.stderr


def test_no_frontend_has_a_copy():
    for tree in FRONTEND_TREES:
        for name in OLD_COPIES:
            found = [str(p.relative_to(REPO)) for p in tree.rglob(name)]
            assert not found, f"{found}: import bootc_shared; do not copy it"


def test_each_frontend_imports_the_package():
    for tree in FRONTEND_TREES:
        text = "\n".join(p.read_text(encoding="utf-8") for p in tree.rglob("*.py"))
        for module in ("account", "branding", "probe", "progress", "readiness", "validate"):
            assert re.search(rf"from bootc_shared(\.{module} import| import [^\n]*\b{module}\b)", text), (
                f"{tree.relative_to(REPO)} does not import bootc_shared.{module}")


def test_no_frontend_keeps_a_literal_group_list():
    for tree in FRONTEND_TREES:
        for path in tree.rglob("*.py"):
            assert '"incus-admin"' not in path.read_text(encoding="utf-8"), (
                f"{path.relative_to(REPO)}: the groups are shared/account/groups.json")


def test_a_change_to_the_package_is_a_change_to_xfce():
    sys.path.insert(0, str(SHARED / "ci"))
    import published_freshness as pf
    paths = ["shared/python/bootc_shared/probe.py", *("shared/" + f for f in _data.FILES),
             "shared/catalog/README.md"]
    assert pf.touches("xfce", paths) == paths[:-1]
    assert pf.touches("gnome", paths) == paths
    assert pf.touches("kde", paths) == []
    # Each path that the XFCE manifest takes from shared/ is in the table.
    for source in xfce_module()["sources"]:
        if "shared/" in source["path"]:
            relative = source["path"].replace("../../../", "")
            assert pf.touches("xfce", [relative + ("/x.py" if source["type"] == "dir" else "")])
