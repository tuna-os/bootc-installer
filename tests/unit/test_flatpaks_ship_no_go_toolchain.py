"""No installer Flatpak ships the Go toolchain.

shared/flatpak/go.json copies the whole Go SDK to /app/go so that the
modules after it (fisherman, the niri backend) can build. Until this change
only the GNOME manifests removed it, with a top-level `cleanup`. The COSMIC,
KDE, niri and XFCE bundles carried /app/go at run time, with Go's own test
keys under go/src/crypto/tls/testdata and go/src/crypto/x509. The niri
medium's secret check stopped on them (tunaOS image-installer run
45818451287).

The go module now removes its own files (`cleanup` in go.json), so every
manifest that includes it gets the cleanup. flatpak-builder runs cleanup
after every module is built, so the later modules still build with Go.
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared" / "ci"))
import flatpak_manifest  # noqa: E402

GO = ROOT / "shared" / "flatpak" / "go.json"
MANIFESTS = sorted(
    list((ROOT / "flatpak").glob("org.bootcinstaller.Installer*.json"))
    + list((ROOT / "frontends").glob("*/flatpak/org.tunaos.Installer*.json")))


def _id(path):
    return path.stem.rsplit(".", 1)[-1]


def test_the_go_module_removes_its_own_files():
    go = json.loads(GO.read_text(encoding="utf-8"))
    assert go["build-commands"] == ["cp -r go /app/go"]
    # Only the toolchain: nothing that runs is under /app/go.
    assert go["cleanup"] == ["/go"]


def test_every_installer_manifest_is_found():
    assert {_id(p) for p in MANIFESTS} >= {
        "Installer", "Devel", "InstallerCosmic", "InstallerKde", "InstallerNiri", "InstallerXfce"}


@pytest.mark.parametrize("path", MANIFESTS, ids=_id)
def test_the_go_toolchain_is_not_shipped(path):
    manifest = flatpak_manifest.load(path)
    modules = manifest["modules"]
    names = [module["name"] for module in modules]
    assert "go" in names, "every installer manifest builds fisherman with go.json"
    go = modules[names.index("go")]
    assert go.get("cleanup") == ["/go"], "/app/go would ship in the bundle"
    # Every module that runs `go build` comes after the toolchain.
    for index, module in enumerate(modules):
        if any("go build" in command for command in module.get("build-commands", [])):
            assert index > names.index("go"), module["name"]
    # Runtime paths stay out of /app/go.
    assert not manifest.get("command", "").startswith("/app/go")
