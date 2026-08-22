"""No flatpak manifest may fetch an architecture-specific binary unconditionally.

The `go` module downloaded go1.26.1.linux-amd64.tar.gz with no `only-arches`,
so an aarch64 build copied an amd64 toolchain into /app/go and then:

    /bin/sh: line 1: /app/go/bin/go: cannot execute binary file: Exec format error
    Error: module fisherman: Child process exited with code 126

(run 32537300795.) This is the SECOND arch assumption the aarch64 build hit —
the first was the workflow defaulting to `arch: x86_64` — and it means the
application itself was never buildable on aarch64, not merely unpublished.

Both manifests are fixed, including the Devel one, which is not built on
aarch64 today. Leaving its twin unfixed is how the pair silently diverges,
and this repo has an issue open about exactly that class of drift (#1183 in
tunaOS, on the byte-copied flatpak tooling).

The sweep below is deliberately about the SHAPE rather than the go module:
any future arch-specific download is caught the same way, without anyone
remembering this incident.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFESTS = sorted((ROOT / "flatpak").glob("*.json"))

# Substrings that mark a URL as built for one architecture. Deliberately
# narrow: matching bare "arm" or "386" would flag unrelated project names.
ARCH_MARKERS = re.compile(r"(linux-amd64|linux-arm64|linux-386|x86[_-]64|aarch64)")


def _sources(manifest: dict):
    for module in manifest.get("modules", []):
        if not isinstance(module, dict):
            continue
        for source in module.get("sources", []):
            if isinstance(source, dict):
                yield module.get("name", "?"), source


def test_there_are_manifests_to_check():
    """A glob that matches nothing would make every test below vacuous."""
    assert MANIFESTS


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.name)
def test_every_arch_specific_source_declares_its_arch(path):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for module_name, source in _sources(manifest):
        url = str(source.get("url", ""))
        if ARCH_MARKERS.search(url):
            assert source.get("only-arches"), (
                f"{path.name}: module {module_name} downloads an "
                f"architecture-specific artifact without only-arches: {url}"
            )


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.name)
def test_the_go_toolchain_covers_both_published_arches(path):
    """x86_64 and aarch64 are the two arches the release workflow builds, so
    both must resolve to a toolchain or the module produces nothing."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    go = [m for m in manifest.get("modules", []) if m.get("name") == "go"]
    if not go:
        pytest.skip(f"{path.name} has no go module")
    arches = {
        arch
        for source in go[0]["sources"]
        for arch in source.get("only-arches", [])
    }
    assert arches == {"x86_64", "aarch64"}, (path.name, arches)


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.name)
def test_no_two_sources_claim_the_same_arch(path):
    """Two candidates for one arch is ambiguous, and flatpak-builder would
    pick by order rather than by intent."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for module_name, _ in _sources(manifest):
        pass
    for module in manifest.get("modules", []):
        seen: dict[str, int] = {}
        for source in module.get("sources", []) if isinstance(module, dict) else []:
            if not isinstance(source, dict):
                continue
            for arch in source.get("only-arches", []):
                seen[arch] = seen.get(arch, 0) + 1
        for arch, count in seen.items():
            assert count == 1, (path.name, module.get("name"), arch, count)


def test_the_two_manifests_agree_on_the_go_toolchain():
    """The production and Devel manifests are near-copies; an arch fix landing
    in one and not the other is the drift this repo has paid for before."""
    versions = {}
    for path in MANIFESTS:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        go = [m for m in manifest.get("modules", []) if m.get("name") == "go"]
        if go:
            versions[path.name] = sorted(
                (s["url"], tuple(s.get("only-arches", []))) for s in go[0]["sources"]
            )
    assert len(set(map(str, versions.values()))) == 1, versions
