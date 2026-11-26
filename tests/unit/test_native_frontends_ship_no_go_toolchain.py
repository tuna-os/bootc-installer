"""The native frontend Flatpaks do not ship the Go toolchain.

shared/flatpak/go.json copies the whole Go SDK to /app/go so that the
fisherman module (and the niri backend) can build. The GNOME manifest
removes it with a top-level `cleanup` (test_gnome_manifest_diet.py); the
COSMIC, KDE, niri and XFCE manifests did not. So each of those bundles
carried /app/go at run time, with Go's own test keys under
go/src/crypto/tls/testdata and go/src/crypto/x509. The niri medium's
secret check stopped on them (tunaOS image-installer run 45818451287).

flatpak-builder runs `cleanup` after every module is built, so the modules
that need the toolchain still build with it.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared" / "ci"))
import flatpak_manifest  # noqa: E402

NATIVE = sorted((ROOT / "frontends").glob("*/flatpak/org.tunaos.Installer*.json"))


def test_every_native_manifest_is_found():
    assert {p.parent.parent.name for p in NATIVE} >= {"cosmic", "kde", "niri", "xfce"}


@pytest.mark.parametrize("path", NATIVE, ids=lambda p: p.parent.parent.name)
def test_the_go_toolchain_is_not_shipped(path):
    manifest = flatpak_manifest.load(path)
    names = [module["name"] for module in manifest["modules"]]
    if "go" not in names:
        pytest.skip("this manifest does not build the Go toolchain")
    assert "/go" in manifest.get("cleanup", []), "/app/go would ship in the bundle"
    # The toolchain module comes before every module that builds with it.
    assert names.index("go") < names.index("fisherman")
