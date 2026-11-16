"""Every `git` source of every Flatpak manifest is pinned to a commit (#398).

A tag or branch can be moved upstream, and the next build fetches other
code under the same name. flatpak-builder checks out a `commit` and refuses
the build when the tag no longer points at it.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared" / "ci"))
import flatpak_manifest  # noqa: E402

MANIFESTS = sorted((ROOT / "flatpak").glob("*.json")) + sorted(
    ROOT.glob("frontends/*/flatpak/org.*.json"))


@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_git_source_names_a_commit(manifest):
    assert flatpak_manifest.unpinned_git(str(manifest)) == []


def _write(tmp_path, source):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"modules": [{"name": "dep", "sources": [source]}]}))
    return str(path)


def test_a_tag_without_a_commit_is_reported(tmp_path):
    path = _write(tmp_path, {"type": "git", "url": "https://example.invalid/x.git", "tag": "v1"})
    assert flatpak_manifest.unpinned_git(path) == [
        f"{path}: module dep: git source https://example.invalid/x.git names no commit"]
    assert flatpak_manifest.main([path]) == 1


def test_a_source_include_is_read(tmp_path):
    (tmp_path / "srcs.json").write_text(json.dumps([{"type": "git", "url": "u", "branch": "main"}]))
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"modules": [{"name": "dep", "sources": ["srcs.json"]}]}))
    assert len(flatpak_manifest.unpinned_git(str(path))) == 1


def test_a_pinned_source_passes(tmp_path):
    path = _write(tmp_path, {"type": "git", "url": "u", "tag": "v1", "commit": "0" * 40})
    assert flatpak_manifest.main([path]) == 0
