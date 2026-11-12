#!/usr/bin/env python3
"""The version of the shared contracts (#226).

`shared/VERSION` holds one semantic version for every contract in shared/.
`shared/README.md` ("How a contract changes") says which change bumps which
part. This module computes the digest of the contract files, which the
newest versioned entry of `shared/CHANGELOG.md` records, and compares the
tree with a base revision.

A contract file is a file that git tracks under shared/, except:

- Markdown (README.md, CHANGELOG.md and the other prose),
- VERSION itself,
- the CI tooling in ci/, browser/ and e2e/. No frontend reads those at run
  time; they drive the workflows.

Run it to print the two lines for a new CHANGELOG.md entry:

    python3 shared/ci/contract_version.py            # lines for the entry
    python3 shared/ci/contract_version.py --changed  # files changed from origin/dev
    python3 shared/ci/contract_version.py --check [--base REF]
        # the whole check, history included; the "Shared contract version"
        # job of python-test.yml runs it against the PR base or the commit
        # before the push
"""

import argparse
import hashlib
import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SHARED = "shared"
TOOLING = ("ci", "browser", "e2e")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
DEFAULT_BASE = "origin/dev"


def is_contract_file(rel):
    """rel is a path relative to the repository root, with / separators."""
    parts = rel.split("/")
    if len(parts) < 2 or parts[0] != SHARED:
        return False
    if rel == f"{SHARED}/VERSION" or rel.endswith(".md"):
        return False
    if len(parts) > 2 and parts[1] in TOOLING:
        return False
    if "__pycache__" in parts or rel.endswith(".pyc"):
        return False
    return True


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def tracked_files(repo=REPO):
    """The tracked files under shared/, or every file when git is absent."""
    try:
        out = _git(repo, "ls-files", "-z", "--cached", "--", SHARED)
        names = [n for n in out.split("\0") if n]
        return sorted(n for n in names if (pathlib.Path(repo) / n).is_file())
    except (OSError, subprocess.CalledProcessError):
        root = pathlib.Path(repo)
        return sorted(p.relative_to(root).as_posix()
                      for p in (root / SHARED).rglob("*") if p.is_file())


def contract_files(repo=REPO):
    return [f for f in tracked_files(repo) if is_contract_file(f)]


def digest(repo=REPO, files=None):
    """sha256 over the sorted (path, content sha256) pairs."""
    h = hashlib.sha256()
    for rel in contract_files(repo) if files is None else sorted(files):
        content = (pathlib.Path(repo) / rel).read_bytes()
        h.update(rel.encode() + b"\0" + hashlib.sha256(content).hexdigest().encode() + b"\n")
    return h.hexdigest()


def parse_version(text):
    m = SEMVER.match(text.strip())
    if not m:
        raise ValueError(f"not a MAJOR.MINOR.PATCH version: {text.strip()!r}")
    return tuple(int(x) for x in m.groups())


def read_version(repo=REPO):
    return parse_version((pathlib.Path(repo) / SHARED / "VERSION").read_text())


def base_revision(repo=REPO, base=None):
    """The merge base of HEAD and the base ref, or None when git has no such ref."""
    ref = base or os.environ.get("SHARED_CONTRACT_BASE", DEFAULT_BASE)
    try:
        return _git(repo, "merge-base", "HEAD", ref).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def changed_contract_files(repo, rev):
    """Contract files that differ between rev and the working tree."""
    out = _git(repo, "diff", "--name-only", "-z", "--no-renames", rev, "--", SHARED)
    return sorted(n for n in out.split("\0") if n and is_contract_file(n))


def show(repo, rev, rel):
    """The text of rel at rev, or None when rev has no such file."""
    try:
        return _git(repo, "show", f"{rev}:{rel}")
    except subprocess.CalledProcessError:
        return None


VERSION_LINE = re.compile(r"^Contracts version: `([^`]*)`$", re.M)
DIGEST_LINE = re.compile(r"^Contracts sha256: `([0-9a-f]{64})`$", re.M)
ENTRY = re.compile(r"^## (\d{4}-\d{2}-\d{2}: \S.*)$", re.M)


def versioned_entries(changelog_text):
    """[(heading, version, digest)] for each entry with a Contracts line, newest first."""
    parts = re.split(ENTRY, changelog_text)
    out = []
    for heading, body in zip(parts[1::2], parts[2::2]):
        versions = VERSION_LINE.findall(body)
        digests = DIGEST_LINE.findall(body)
        if versions or digests:
            out.append((heading, versions, digests))
    return out


def check_changelog(repo=REPO):
    """Problems with VERSION and CHANGELOG.md that need no history."""
    root = pathlib.Path(repo) / SHARED
    problems = []
    try:
        version = read_version(repo)
    except (OSError, ValueError) as e:
        return [f"shared/VERSION: {e}"]
    entries = versioned_entries((root / "CHANGELOG.md").read_text(encoding="utf-8"))
    if not entries:
        return ["shared/CHANGELOG.md has no entry with a 'Contracts version:' line"]
    seen = []
    for heading, versions, digests in entries:
        if len(versions) != 1 or len(digests) != 1:
            problems.append(f"entry '{heading}' needs exactly one 'Contracts version:' "
                            "line and one 'Contracts sha256:' line")
            continue
        try:
            seen.append((heading, parse_version(versions[0]), digests[0]))
        except ValueError as e:
            problems.append(f"entry '{heading}': {e}")
    if problems:
        return problems
    for (h1, v1, _), (h2, v2, _) in zip(seen, seen[1:]):
        if not v1 > v2:
            problems.append(f"entry '{h1}' has version {fmt(v1)}, which is not greater "
                            f"than {fmt(v2)} in the older entry '{h2}'")
    digests = [d for _, _, d in seen]
    if len(digests) != len(set(digests)):
        problems.append("a 'Contracts sha256:' digest appears twice in shared/CHANGELOG.md")
    heading, newest, recorded = seen[0]
    if newest != version:
        problems.append(f"shared/VERSION is {fmt(version)}, but the newest entry "
                        f"'{heading}' has {fmt(newest)}")
    actual = digest(repo)
    if recorded != actual:
        problems.append(
            "a contract file in shared/ changed (digest " + actual + "), but the newest "
            f"versioned entry '{heading}' records {recorded}. Add an entry at the top of "
            "shared/CHANGELOG.md, increase shared/VERSION by the rules in shared/README.md "
            "('How a contract changes'), and put the lines of "
            "'python3 shared/ci/contract_version.py' in the entry")
    return problems


def check_against(repo, rev):
    """Problems of the change from rev: a changed contract needs a new entry and a bump."""
    changed = changed_contract_files(repo, rev)
    if not changed:
        return []
    problems = []
    old_text = show(repo, rev, f"{SHARED}/VERSION")
    old = parse_version(old_text) if old_text is not None else (0, 0, 0)
    new = read_version(repo)
    if not new > old:
        problems.append(f"contract files changed ({', '.join(changed)}), but shared/VERSION "
                        f"is {fmt(new)}, not greater than {fmt(old)} on the base")
    old_log = show(repo, rev, f"{SHARED}/CHANGELOG.md") or ""
    entries = versioned_entries((pathlib.Path(repo) / SHARED / "CHANGELOG.md")
                                .read_text(encoding="utf-8"))
    if entries and f"## {entries[0][0]}" in old_log.splitlines():
        problems.append(f"contract files changed ({', '.join(changed)}), but the newest "
                        f"versioned entry '{entries[0][0]}' is already on the base. "
                        "Add a new entry; do not edit an old one")
    return problems


def fmt(v):
    return ".".join(map(str, v))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--changed", action="store_true",
                    help="list the contract files that differ from the base")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 when VERSION, CHANGELOG.md and the base disagree")
    ap.add_argument("--base", help=f"base ref (default ${{SHARED_CONTRACT_BASE}} or {DEFAULT_BASE})")
    ap.add_argument("--repo", default=str(REPO), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    repo = pathlib.Path(args.repo)
    if args.changed:
        rev = base_revision(repo, args.base)
        if rev is None:
            print("no base revision", file=sys.stderr)
            return 2
        for f in changed_contract_files(repo, rev):
            print(f)
        return 0
    if args.check:
        problems = check_changelog(repo)
        ref = args.base or os.environ.get("SHARED_CONTRACT_BASE", DEFAULT_BASE)
        rev = base_revision(repo, ref)
        if rev is None:
            # The history check is the point of --check: no base is an error,
            # never a silent pass. The CI job fetches the base first.
            problems.append(f"no merge base of HEAD and {ref}: fetch it "
                            "(fetch-depth 0) or name another --base")
        else:
            print(f"base: {ref} (merge base {rev[:12]})")
            changed = changed_contract_files(repo, rev)
            print("changed contract files: " + (", ".join(changed) or "none"))
            problems += check_against(repo, rev)
        for p in problems:
            print(f"::error::{p}" if os.environ.get("GITHUB_ACTIONS") else p,
                  file=sys.stderr)
        return 1 if problems else 0
    version = fmt(read_version(repo))
    print(f"Contracts version: `{version}`")
    print(f"Contracts sha256: `{digest(repo)}`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
