#!/usr/bin/env python3
"""Read a Flatpak manifest the way flatpak-builder does: with its includes.

A manifest may name a module by a string, the path of a JSON file that holds
the module (shared/flatpak/go.json). flatpak-builder reads that file and
resolves the module's relative source paths against the directory of that
file, not of the manifest. The tests and CI scripts that read the manifests
use this module so that they see the same modules and paths.

    python3 shared/ci/flatpak_manifest.py <manifest>...   # check local paths

The command exits non-zero when a module include, a `dir` or `file` source or
a source include does not exist where flatpak-builder looks for it.
"""

from __future__ import annotations

import copy
import json
import os
import sys


class ManifestError(Exception):
    """A module include cannot be read."""


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        raise ManifestError(f"{path}: {e}") from e


def walk(path):
    """Yield (module, base_dir) for every module of the manifest at `path`.

    String modules are read from their file, and nested `modules` are walked
    too. `base_dir` is the directory that the module's relative source paths
    resolve against.
    """
    manifest = _read(path)

    def visit(modules, base):
        for module in modules or []:
            here = base
            if isinstance(module, str):
                include = os.path.normpath(os.path.join(base, module))
                if not os.path.isfile(include):
                    raise ManifestError(f"{path}: module include {module} does not exist "
                                        f"({include})")
                module = _read(include)
                here = os.path.dirname(include)
            if not isinstance(module, dict):
                continue
            yield module, here
            yield from visit(module.get("modules"), here)

    yield from visit(manifest.get("modules"), os.path.dirname(os.path.abspath(path)))


def load(path):
    """The manifest at `path` with every string module replaced by its content.

    Only the top-level module list and nested lists are inlined; sources are
    left as they are.
    """
    manifest = _read(path)
    base = os.path.dirname(os.path.abspath(path))

    def inline(modules, base):
        out = []
        for module in modules or []:
            here = base
            if isinstance(module, str):
                include = os.path.normpath(os.path.join(base, module))
                module = _read(include)
                here = os.path.dirname(include)
            if isinstance(module, dict):
                module = copy.deepcopy(module)
                if "modules" in module:
                    module["modules"] = inline(module["modules"], here)
            out.append(module)
        return out

    manifest["modules"] = inline(manifest.get("modules"), base)
    return manifest


def local_paths(path):
    """(module name, kind, absolute path) for each local file the build reads."""
    out = []
    for module, base in walk(path):
        for source in module.get("sources") or []:
            if isinstance(source, str):
                out.append((module.get("name", "?"), "source include",
                            os.path.normpath(os.path.join(base, source))))
            elif isinstance(source, dict) and source.get("type") in ("dir", "file", "patch", "script") \
                    and isinstance(source.get("path"), str):
                out.append((module.get("name", "?"), source["type"],
                            os.path.normpath(os.path.join(base, source["path"]))))
    return out


def missing_paths(path):
    """Messages for each local path of the manifest that does not exist."""
    problems = []
    try:
        entries = local_paths(path)
    except ManifestError as e:
        return [str(e)]
    for name, kind, target in entries:
        exists = os.path.isdir(target) if kind == "dir" else os.path.isfile(target)
        if not exists:
            problems.append(f"{path}: module {name}: {kind} {target} does not exist")
    return problems


def main(argv=None):
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        print("usage: flatpak_manifest.py <manifest>...", file=sys.stderr)
        return 2
    problems = [p for path in paths for p in missing_paths(path)]
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
