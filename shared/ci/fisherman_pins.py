#!/usr/bin/env python3
"""Move the fisherman pin of this repository to one commit.

fisherman has one pin: the `fisherman` submodule gitlink. Every Flatpak
builds fisherman from that submodule. GNOME's manifest has its own module
with a `dir` source ../fisherman; the four frontend manifests include
shared/flatpak/fisherman.json, whose `dir` source is the same submodule.
tests/unit/test_shared_probe.py::TestFishermanPin holds every manifest to
that.

The four frontend manifests used to pin a fisherman git commit each, and
this script moved those pins with the gitlink. A manifest that pins a
tuna-os/fisherman git source again would be a second pin that this script
does not move, so the script refuses to run while one exists: it writes
nothing and exits non-zero.

Renovate moves the gitlink (renovate.json, `git-submodules`, group
"fisherman"); this script is for moving it by hand. It stages the result.

    python3 shared/ci/fisherman_pins.py --commit <sha> [--repo .]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flatpak_manifest  # noqa: E402

MANIFEST_GLOBS = (
    os.path.join("flatpak", "*.json"),
    os.path.join("frontends", "*", "flatpak", "*.json"),
)
SUBMODULE_PATH = "fisherman"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_FISHERMAN_URL_RE = re.compile(
    r"^(?:https?://|ssh://git@|git@)?github\.com[/:]tuna-os/fisherman(?:\.git)?/?$",
    re.IGNORECASE,
)


class PinError(Exception):
    """The fisherman pin cannot be moved safely."""


def is_fisherman_url(url):
    return isinstance(url, str) and bool(_FISHERMAN_URL_RE.match(url.strip()))


def is_app_manifest(data):
    return isinstance(data, dict) and isinstance(data.get("modules"), list) and (
        "app-id" in data or "id" in data)


def app_manifests(repo):
    """Paths (relative to repo) of the Flatpak app manifests in the repository."""
    out = []
    for pattern in MANIFEST_GLOBS:
        for path in sorted(glob.glob(os.path.join(repo, pattern))):
            with open(path, encoding="utf-8") as fh:
                try:
                    data = json.load(fh)
                except json.JSONDecodeError as e:
                    raise PinError(f"{os.path.relpath(path, repo)}: not valid JSON: {e}") from e
            if is_app_manifest(data):
                out.append(os.path.relpath(path, repo))
    return out


def fisherman_git_sources(path):
    """Every tuna-os/fisherman git source in the manifest, includes read."""
    try:
        return [source for module, _base in flatpak_manifest.walk(path)
                for source in module.get("sources") or []
                if isinstance(source, dict) and source.get("type") == "git"
                and is_fisherman_url(source.get("url"))]
    except flatpak_manifest.ManifestError as e:
        raise PinError(str(e)) from e


def second_pins(repo):
    """{manifest: count} for each manifest that pins fisherman by git."""
    out = {}
    for rel in app_manifests(repo):
        found = fisherman_git_sources(os.path.join(repo, rel))
        if found:
            out[rel] = len(found)
    return out


def set_pin(repo, commit):
    """Point the gitlink at `commit` and stage it."""
    if not _SHA_RE.fullmatch(commit or ""):
        raise PinError(f"not a full commit sha: {commit!r}")
    extra = second_pins(repo)
    if extra:
        names = ", ".join(sorted(extra))
        raise PinError(f"{names}: pins a tuna-os/fisherman git source; build fisherman "
                       "from the submodule (shared/flatpak/fisherman.json) instead")
    subprocess.run(["git", "-C", repo, "update-index", "--cacheinfo",
                    f"160000,{commit},{SUBMODULE_PATH}"], check=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--commit", required=True, help="the fisherman commit to pin")
    p.add_argument("--repo", default=".", help="repository root (default: .)")
    args = p.parse_args(argv)
    try:
        set_pin(args.repo, args.commit)
    except PinError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    print(f"{SUBMODULE_PATH} (gitlink) -> {args.commit[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
