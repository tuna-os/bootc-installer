#!/usr/bin/env python3
"""Run the tests of each frontend from its metadata file (#186).

Each frontend has one metadata file with its canonical build and test
commands:

    shared/ci/frontend-gnome.json   GNOME (the repository root)
    frontends/<name>/frontend.json  KDE, COSMIC, Niri, XFCE

The frontends are the rows of shared/ci/frontends.json, in that order.

A file has the keys `frontend` (its name), `build`, `test` and
`compliance`, and an optional `$comment`. Each of the three lists holds
commands, and each command has:

    id             a name, unique in its list
    run            the shell command, as CI runs it (bash)
    cwd            the directory, from the repository root
    workflow       the file in .github/workflows/ that runs the command
    job            the job of that workflow
    requires       what the command needs; each entry is an executable on
                   PATH, `pkg-config:<module>`, `python:<module>` (python3
                   on PATH can import it), or
                   alternatives joined with `|`
    env            optional: variables that the step sets
    needs          optional, tests only: the ids of the build commands
                   that must run first
    unless_exists  optional, build only: a path (from `cwd`); when it
                   exists, the command does not run again

tests/unit/test_ci_frontend_meta.py holds each command to its workflow:
the step of that job, in that directory, has a line that starts with the
command, with the same environment. So a command here is a command that CI
runs.

    python3 shared/ci/frontend_tests.py --list            # the plan, runs nothing
    python3 shared/ci/frontend_tests.py                    # every test of every frontend
    python3 shared/ci/frontend_tests.py kde niri:backend   # a frontend, or one test
    python3 shared/ci/frontend_tests.py --compliance       # the recipe compliance commands

The script prints each command before it runs it. When a command needs a
tool that is not here, the script skips the command and says which tool is
missing; with --require-all a skip is a failure. The exit code is 1 when a
command fails, 2 for a bad argument or a bad metadata file, else 0.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import frontend_table  # noqa: E402

SECTIONS = ("build", "test", "compliance")
COMMAND_KEYS = {"id": str, "run": str, "cwd": str, "workflow": str, "job": str,
                "requires": list}
OPTIONAL_KEYS = {"env": dict, "needs": list, "unless_exists": str}
PASSED, FAILED, SKIPPED = "passed", "failed", "skipped"


class MetaError(Exception):
    """A metadata file, or the selection, is not usable."""


def meta_path(frontend):
    """The metadata file of a frontend, from the repository root."""
    if frontend == "gnome":
        return "shared/ci/frontend-gnome.json"
    return f"frontends/{frontend}/frontend.json"


def frontends(repo=REPO):
    """The names of the frontends, in the order of shared/ci/frontends.json."""
    return list(frontend_table.load(os.path.join(repo, "shared", "ci", "frontends.json")))


def validate(meta, frontend, where):
    """Raise MetaError when `meta` is not a metadata file of `frontend`."""
    if not isinstance(meta, dict):
        raise MetaError(f"{where}: expected an object")
    extra = set(meta) - {"$comment", "frontend", *SECTIONS}
    if extra:
        raise MetaError(f"{where}: unknown keys {sorted(extra)}")
    if meta.get("frontend") != frontend:
        raise MetaError(f"{where}: `frontend` is {meta.get('frontend')!r}, expected {frontend!r}")
    for section in SECTIONS:
        commands = meta.get(section)
        if not isinstance(commands, list):
            raise MetaError(f"{where}: `{section}` must be a list")
        ids = set()
        for i, cmd in enumerate(commands):
            at = f"{where}: {section}[{i}]"
            if not isinstance(cmd, dict):
                raise MetaError(f"{at}: expected an object")
            allowed = set(COMMAND_KEYS) | {"env"}
            if section == "test":
                allowed.add("needs")
            if section in ("build", "compliance"):
                allowed.add("unless_exists")
            missing = set(COMMAND_KEYS) - set(cmd)
            unknown = set(cmd) - allowed
            if missing or unknown:
                raise MetaError(f"{at}: missing {sorted(missing)}, unknown {sorted(unknown)}")
            for key, kind in {**COMMAND_KEYS, **OPTIONAL_KEYS}.items():
                if key in cmd and type(cmd[key]) is not kind:
                    raise MetaError(f"{at}.{key}: expected a {kind.__name__}")
            for key in ("id", "run", "cwd", "workflow", "job"):
                if not cmd[key].strip():
                    raise MetaError(f"{at}.{key}: is empty")
            if cmd["id"] in ids:
                raise MetaError(f"{at}: id {cmd['id']!r} is twice in `{section}`")
            ids.add(cmd["id"])
            if os.path.isabs(cmd["cwd"]) or ".." in cmd["cwd"].split("/"):
                raise MetaError(f"{at}.cwd: must be a path in the repository")
            if not all(isinstance(r, str) and r.strip() for r in cmd["requires"]):
                raise MetaError(f"{at}.requires: each entry must be a non-empty string")
            if not all(isinstance(k, str) and isinstance(v, str)
                       for k, v in cmd.get("env", {}).items()):
                raise MetaError(f"{at}.env: names and values must be strings")
    builds = {c["id"] for c in meta["build"]}
    for cmd in meta["test"]:
        unknown = [n for n in cmd.get("needs", []) if n not in builds]
        if unknown:
            raise MetaError(f"{where}: test {cmd['id']!r} needs unknown build ids {unknown}")
    return meta


def load(frontend, repo=REPO):
    rel = meta_path(frontend)
    path = os.path.join(repo, rel)
    try:
        with open(path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError) as exc:
        raise MetaError(f"{rel}: {exc}") from exc
    return validate(meta, frontend, rel)


def load_all(repo=REPO):
    return {name: load(name, repo) for name in frontends(repo)}


def select(metas, names, compliance=False):
    """The plan: [(frontend, [steps])], in table order.

    `names` holds `<frontend>` or `<frontend>:<test id>`; empty means all.
    A step is (kind, command), where kind is "build", "test" or
    "compliance". The build commands of a test come before it, once each.
    """
    wanted = {}
    for item in names:
        frontend, _, test_id = item.partition(":")
        if frontend not in metas:
            raise MetaError(f"unknown frontend {frontend!r}; known: {', '.join(metas)}")
        if test_id:
            section = "compliance" if compliance else "test"
            if test_id not in {c["id"] for c in metas[frontend][section]}:
                raise MetaError(f"{frontend} has no {section} command {test_id!r}")
        ids = wanted.setdefault(frontend, set())
        if ids is not None:
            if test_id:
                ids.add(test_id)
            else:
                wanted[frontend] = None
    if not names:
        wanted = dict.fromkeys(metas)
    plan = []
    for frontend, meta in metas.items():
        if frontend not in wanted:
            continue
        ids = wanted[frontend]
        if compliance:
            steps = [("compliance", c) for c in meta["compliance"]
                     if ids is None or c["id"] in ids]
        else:
            tests = [c for c in meta["test"] if ids is None or c["id"] in ids]
            need = {n for c in tests for n in c.get("needs", [])}
            steps = [("build", c) for c in meta["build"] if c["id"] in need]
            steps += [("test", c) for c in tests]
        plan.append((frontend, steps))
    return plan


def missing(requires, which=shutil.which, pkg_config=None, find_spec=None):
    """The entries of `requires` that this computer does not have."""
    if pkg_config is None:
        def pkg_config(module):
            if not which("pkg-config"):
                return False
            return subprocess.run(["pkg-config", "--exists", module],
                                  capture_output=True).returncode == 0
    if find_spec is None:
        # The import, in the python3 that the commands run: a module that
        # is there but does not load (gi built for another Python) is
        # missing too.
        def find_spec(module):
            python = which("python3")
            if not python:
                return False
            return subprocess.run([python, "-c", f"import {module}"],
                                  capture_output=True).returncode == 0

    def have(entry):
        kind, sep, name = entry.partition(":")
        if sep and kind == "pkg-config":
            return pkg_config(name)
        if sep and kind == "python":
            return find_spec(name)
        return which(entry) is not None
    return [entry for entry in requires
            if not any(have(alt.strip()) for alt in entry.split("|"))]


def describe(frontend, kind, cmd):
    env = "".join(f"{k}={v} " for k, v in sorted(cmd.get("env", {}).items()))
    return (f"{frontend}:{cmd['id']} ({kind}, in {cmd['cwd']}, as in "
            f"{cmd['workflow']} job {cmd['job']}): {env}{cmd['run']}")


def run_plan(plan, repo=REPO, require_all=False, check=missing, execute=None, out=print):
    """Run the plan. Returns ({(frontend, id, kind): outcome}, exit code)."""
    if execute is None:
        def execute(cmd, cwd, env):
            return subprocess.run(["bash", "-eo", "pipefail", "-c", cmd["run"]],
                                  cwd=cwd, env=env).returncode
    results = {}
    for frontend, steps in plan:
        broken = {}  # build id: why the tests that need it cannot run
        for kind, cmd in steps:
            key = (frontend, cmd["id"], kind)
            blocked = [broken[n] for n in cmd.get("needs", []) if n in broken]
            if kind == "compliance" and broken:
                blocked = list(broken.values())[:1]
            gone = check(cmd["requires"])
            if blocked or gone:
                why = blocked[0] if blocked else f"missing {', '.join(gone)}"
                # A step after a failed build is skipped: the build is the failure.
                outcome = FAILED if require_all else SKIPPED
                out(f"{outcome.upper()}: {describe(frontend, kind, cmd)}\n    {why}")
                results[key] = outcome
                if kind in ("build", "compliance"):
                    broken[cmd["id"]] = f"{kind} {cmd['id']!r} did not run: {why}"
                continue
            cwd = os.path.join(repo, cmd["cwd"])
            marker = cmd.get("unless_exists")
            if marker and os.path.exists(os.path.join(cwd, marker)):
                out(f"DONE: {describe(frontend, kind, cmd)}\n    {marker} exists")
                results[key] = PASSED
                continue
            out(f"RUN: {describe(frontend, kind, cmd)}")
            rc = execute(cmd, cwd, {**os.environ, **cmd.get("env", {})})
            results[key] = PASSED if rc == 0 else FAILED
            if rc != 0:
                out(f"FAILED (exit {rc}): {frontend}:{cmd['id']}")
                if kind in ("build", "compliance"):
                    broken[cmd["id"]] = f"{kind} {cmd['id']!r} failed"
    failed = [k for k, v in results.items() if v == FAILED]
    out("")
    for (frontend, cid, kind), outcome in results.items():
        out(f"  {outcome:8s} {frontend}:{cid} ({kind})")
    return results, (1 if failed else 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="<frontend> or <frontend>:<id>; default all")
    ap.add_argument("--list", action="store_true", help="print the plan and run nothing")
    ap.add_argument("--compliance", action="store_true",
                    help="run the recipe compliance commands, not the tests")
    ap.add_argument("--require-all", action="store_true",
                    help="a command that cannot run (missing tool) is a failure")
    args = ap.parse_args(argv)
    try:
        plan = select(load_all(), args.names, compliance=args.compliance)
    except (MetaError, frontend_table.TableError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.list:
        for frontend, steps in plan:
            for kind, cmd in steps:
                gone = missing(cmd["requires"])
                note = f"  [would skip: missing {', '.join(gone)}]" if gone else ""
                print(describe(frontend, kind, cmd) + note)
        return 0
    _results, rc = run_plan(plan, require_all=args.require_all)
    return rc


if __name__ == "__main__":
    sys.exit(main())
