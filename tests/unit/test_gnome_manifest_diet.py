"""The GNOME Flatpak manifests carry only what the application uses (#320).

Until this change the production manifest built md4c, libsass, sassc, libbge
and libpastry, shipped the whole Go toolchain in /app/go, and gave the
released application `--allow=devel`. No file of the GNOME frontend imports,
links or runs any of the five: they came with a libpastry plan
(docs/features/libpastry-integration.md) that never reached the code.

This file replaces test_libbge_installs_the_markdown_header.py. That test
pinned a workaround inside the libbge module (bootc-installer#25); with the
module gone there is no workaround left to pin. What it protected, an
aarch64 build that compiles, is covered by the absence of the module and by
the "Build (production, aarch64)" job.

`--device=all` stays. The installer lists and partitions disks through
fisherman on the host, so the sandbox may not need it, but nobody has run
the application with `--device=dri` on a live ISO yet (GPU detection reads
/sys, the companion and Wi-Fi pages talk to host services). Narrow it in a
change that carries that run.
"""

import importlib.util
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared" / "ci"))
import flatpak_manifest  # noqa: E402

FLATPAK = ROOT / "flatpak"
PRODUCTION = FLATPAK / "org.bootcinstaller.Installer.json"
DEVEL = FLATPAK / "org.bootcinstaller.Installer.Devel.json"
UNUSED = ("md4c", "libsass", "sassc", "libbge", "libpastry")

_spec = importlib.util.spec_from_file_location("generate_devel", FLATPAK / "generate-devel.py")
generate_devel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate_devel)


def _load(path):
    # Module includes (shared/flatpak/go.json) read as flatpak-builder reads them.
    return flatpak_manifest.load(path)


def _raw(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _names(manifest):
    return [module["name"] for module in manifest["modules"]]


@pytest.mark.parametrize("path", [PRODUCTION, DEVEL], ids=lambda p: p.name)
def test_the_unused_modules_are_gone(path):
    assert not set(UNUSED) & set(_names(_load(path)))
    text = path.read_text(encoding="utf-8")
    for needle in ("bazaar", "libpastry", "md4c", "sass"):
        assert needle not in text, needle


def test_nothing_in_the_gnome_frontend_uses_them():
    """The reason they could go. If a later change starts to use one, this
    fails next to the manifest that must then build it again."""
    pattern = re.compile(
        r"\b(?:md4c|libsass|sassc|libbge|libpastry|Pastry|Bge)\b|require_version\(\s*[\"'](?:Bge|Pastry)")
    roots = [ROOT / "bootc_installer", ROOT / "data"]
    files = [ROOT / "meson.build", ROOT / "meson_options.txt"]
    for root in roots:
        files += [p for p in root.rglob("*")
                  if p.suffix in (".py", ".blp", ".ui", ".build", ".xml", ".in", ".css", ".json")]
    assert len(files) > 50, "the scan found too few files to mean anything"
    hits = []
    for path in files:
        if path.is_file() and pattern.search(path.read_text(encoding="utf-8", errors="replace")):
            hits.append(str(path.relative_to(ROOT)))
    assert hits == []
    assert not list((ROOT / "bootc_installer").rglob("*.scss")), "a stylesheet needs sassc"


def test_what_the_application_does_use_is_still_built():
    assert _names(_load(PRODUCTION)) == [
        "mutter-schemas", "go", "fisherman", "blueprint-compiler",
        "python3-segno", "bootc-installer", "polkit-action",
    ]


@pytest.mark.parametrize("path", [PRODUCTION, DEVEL], ids=lambda p: p.name)
def test_the_go_toolchain_is_not_shipped(path):
    manifest = _load(path)
    go = next(module for module in manifest["modules"] if module["name"] == "go")
    assert go["build-commands"] == ["cp -r go /app/go"]
    assert "/go" in manifest.get("cleanup", []), "/app/go would ship in the bundle"
    # fisherman is built with that toolchain, after it and before cleanup.
    names = _names(manifest)
    assert names.index("go") < names.index("fisherman")
    assert manifest["build-options"]["env"]["PATH"].startswith("/app/go/bin:")


def test_cleanup_does_not_remove_what_runs():
    assert _load(PRODUCTION)["cleanup"] == ["/go"]


def test_production_has_no_devel_permission():
    args = _load(PRODUCTION)["finish-args"]
    assert "--allow=devel" not in args
    assert not [arg for arg in args if arg.startswith("--env=BOOTC_INSTALLER_DEBUG")]


def test_the_permissions_the_installer_needs_are_kept():
    args = _load(PRODUCTION)["finish-args"]
    for needed in ("--filesystem=host", "--talk-name=org.freedesktop.Flatpak",
                   "--system-talk-name=org.freedesktop.PolicyKit1",
                   "--system-talk-name=org.freedesktop.login1", "--share=network",
                   "--device=all"):
        assert needed in args, needed


def test_devel_is_generated_from_production():
    assert DEVEL.read_text(encoding="utf-8") == generate_devel.generated(), (
        "run: python3 flatpak/generate-devel.py")


def test_devel_differs_from_production_only_where_the_generator_says():
    production, devel = _load(PRODUCTION), _load(DEVEL)
    assert devel["app-id"] == production["app-id"] + ".Devel"
    assert devel["finish-args"] == production["finish-args"] + generate_devel.DEVEL_FINISH_ARGS
    assert "--allow=devel" in devel["finish-args"]
    assert devel["modules"][:-1] == production["modules"]
    assert devel["modules"][-1]["name"] == "devel-assets"
    for key in set(production) - {"app-id", "finish-args", "modules"}:
        assert devel[key] == production[key], key


def test_the_devel_assets_exist():
    for command in generate_devel.DEVEL_ASSETS["build-commands"]:
        source = command.split()[2]
        assert (ROOT / source).is_file(), source


def test_production_manifest_is_in_the_generator_format():
    """One format for both, so a hand edit and a generated file diff cleanly."""
    assert PRODUCTION.read_text(encoding="utf-8") == generate_devel.dumps(_raw(PRODUCTION))
