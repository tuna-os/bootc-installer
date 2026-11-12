#!/usr/bin/env python3
"""An SPDX SBOM for each frontend's Flatpak, for the GitHub release (#151).

.github/workflows/sbom.yml runs this once per row of frontends.json, in two
steps around anchore/sbom-action (Syft), then checks the result. release.yml
calls sbom.yml for the release; pull requests and dev run the same workflow
as a dry run:

    python3 shared/ci/flatpak_sbom.py stage --frontend kde --into sbom-src/kde
    # anchore/sbom-action scans sbom-src/kde and writes kde.syft.spdx.json
    python3 shared/ci/flatpak_sbom.py merge --frontend kde \\
        --syft kde.syft.spdx.json --out kde.spdx.json \\
        --repo-url https://github.com/tuna-os/bootc-installer --commit "$GITHUB_SHA"
    python3 shared/ci/flatpak_sbom.py check --commit "$GITHUB_SHA" kde.spdx.json

`stage` copies the lock files that the frontend's Flatpak builds from
(LOCKFILES) into a directory of their own, at their repository paths. Syft
then lists the Go modules and Rust crates of exactly those builds, and not of
the tests, the CI or the other frontends that share this repository.

Syft cannot read a Flatpak manifest. `merge` therefore adds, from the
manifest in frontends.json and its module includes (flatpak_manifest.walk):

    the app          one package for the Flatpak, at the release commit; the
                     document DESCRIBES it, and it CONTAINS what Syft found
    the runtime      `runtime` at `runtime-version` (DEPENDS_ON), and `sdk`
                     and each `sdk-extensions` entry (BUILD_TOOL_OF)
    each module      one package per remote source (archive, file, git) with
                     its URL, sha256, tag or commit; and one package per
                     module that builds from this repository or from a
                     submodule, at the commit that the release builds

A source include (a string in `sources`, such as COSMIC's cargo-sources.json)
is not listed again: it holds the same crates as the Cargo.lock that Syft
reads.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import flatpak_manifest  # noqa: E402
import frontend_table  # noqa: E402

# The lock files that each Flatpak builds from, relative to the repository
# root. The Go builds are `go build -C fisherman` (shared/flatpak/
# fisherman.json, and the GNOME manifest's own fisherman module) and, for
# Niri, `go build -C installer`; COSMIC builds with `cargo --offline build`.
# tests/unit/test_release_sbom.py holds this table to the manifests.
COMMON_LOCKFILES = ("fisherman/fisherman/go.mod",)
LOCKFILES = {
    "gnome": COMMON_LOCKFILES,
    "kde": COMMON_LOCKFILES,
    "cosmic": COMMON_LOCKFILES + ("frontends/cosmic/Cargo.lock",),
    "niri": COMMON_LOCKFILES + ("frontends/niri/installer/go.mod",),
    "xfce": COMMON_LOCKFILES,
}
# Copied when they exist next to a go.mod: a module with no dependency has no
# go.sum.
OPTIONAL_SIBLINGS = {"go.mod": ("go.sum",)}

NOASSERTION = "NOASSERTION"
DOCUMENT = "SPDXRef-DOCUMENT"


class SbomError(Exception):
    """The SBOM cannot be made from what is there."""


def lockfiles(frontend, root=ROOT):
    """The repository paths that `stage` copies for this frontend."""
    if frontend not in LOCKFILES:
        raise SbomError(f"no lock file list for frontend {frontend!r}")
    out = []
    for rel in LOCKFILES[frontend]:
        if not os.path.isfile(os.path.join(root, rel)):
            raise SbomError(f"{frontend}: lock file {rel} does not exist "
                            "(is the fisherman submodule checked out?)")
        out.append(rel)
        for sibling in OPTIONAL_SIBLINGS.get(os.path.basename(rel), ()):
            extra = os.path.join(os.path.dirname(rel), sibling)
            if os.path.isfile(os.path.join(root, extra)):
                out.append(extra)
    return out


def stage(frontend, into, root=ROOT):
    """Copy the frontend's lock files into `into`, at their repository paths."""
    copied = []
    for rel in lockfiles(frontend, root):
        target = os.path.join(into, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(root, rel), target)
        copied.append(rel)
    return copied


def spdx_id(*parts):
    """An SPDX identifier: `SPDXRef-` and only letters, digits, `.` and `-`."""
    text = "-".join(str(p) for p in parts if p)
    return "SPDXRef-" + (re.sub(r"[^A-Za-z0-9.-]+", "-", text).strip("-") or "x")


def _package(spdxid, name, download, version=None, checksums=(), comment=None, purpose=None):
    pkg = {
        "SPDXID": spdxid,
        "name": name,
        "downloadLocation": download or NOASSERTION,
        "filesAnalyzed": False,
        "licenseConcluded": NOASSERTION,
        "licenseDeclared": NOASSERTION,
        "copyrightText": NOASSERTION,
        "supplier": NOASSERTION,
    }
    if version:
        pkg["versionInfo"] = version
    if checksums:
        pkg["checksums"] = list(checksums)
    if comment:
        pkg["comment"] = comment
    if purpose:
        pkg["primaryPackagePurpose"] = purpose
    return pkg


def _git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def submodules(root=ROOT):
    """{absolute path: (url, gitlink commit)} for each submodule of the tree."""
    path = os.path.join(root, ".gitmodules")
    if not os.path.isfile(path):
        return {}
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    out = {}
    for section in parser.sections():
        sub = parser[section].get("path")
        url = parser[section].get("url")
        if not sub or not url:
            continue
        # The gitlink in the release commit: right with or without a checkout.
        entry = _git(root, "ls-tree", "HEAD", sub).split()
        if len(entry) >= 3 and entry[1] == "commit":
            out[os.path.normpath(os.path.join(root, sub))] = (url, entry[2])
    return out


def _git_location(url, ref):
    url = url[:-4] if url.endswith(".git") else url
    return f"git+{url}@{ref}" if ref else f"git+{url}"


def _local_origin(target, root, repo_url, commit, subs):
    """(download location, version) of a local dir or file source."""
    target = os.path.normpath(target)
    for path, (url, gitlink) in subs.items():
        if target == path or target.startswith(path + os.sep):
            return _git_location(url, gitlink), gitlink
    return _git_location(repo_url, commit), commit


def manifest_packages(manifest_path, repo_url, commit, root=ROOT, subs=None):
    """[(package, relationship to the app)] from the manifest and its includes."""
    subs = submodules(root) if subs is None else subs
    manifest = flatpak_manifest._read(manifest_path)
    out = []
    runtime = manifest.get("runtime")
    if runtime:
        out.append((_package(spdx_id("Runtime", runtime), runtime, NOASSERTION,
                             version=manifest.get("runtime-version"), purpose="FRAMEWORK",
                             comment="Flatpak runtime; installed from its remote, not in the bundle"),
                    "DEPENDS_ON"))
    sdk = manifest.get("sdk")
    if sdk:
        out.append((_package(spdx_id("Sdk", sdk), sdk, NOASSERTION,
                             version=manifest.get("runtime-version"), purpose="FRAMEWORK"),
                    "BUILD_TOOL_OF"))
    for ext in manifest.get("sdk-extensions") or []:
        out.append((_package(spdx_id("SdkExtension", ext), ext, NOASSERTION, purpose="FRAMEWORK"),
                    "BUILD_TOOL_OF"))

    seen = set()
    for module, base in flatpak_manifest.walk(manifest_path):
        name = module.get("name", "module")
        local = None
        for index, source in enumerate(module.get("sources") or []):
            if not isinstance(source, dict):
                continue  # a source include (cargo-sources.json): Syft has the lock file
            kind = source.get("type")
            arches = source.get("only-arches")
            note = f"only on {', '.join(arches)}" if arches else None
            if kind in ("archive", "file") and source.get("url"):
                sums = ([{"algorithm": "SHA256", "checksumValue": source["sha256"]}]
                        if source.get("sha256") else [])
                pkg = _package(spdx_id("Module", name, index), name, source["url"],
                               checksums=sums, comment=note, purpose="SOURCE")
                out.append((pkg, "CONTAINS"))
            elif kind == "git" and source.get("url"):
                ref = source.get("commit") or source.get("tag") or source.get("branch")
                pkg = _package(spdx_id("Module", name, index), name,
                               _git_location(source["url"], ref),
                               version=source.get("tag") or source.get("commit"),
                               comment=note, purpose="SOURCE")
                out.append((pkg, "CONTAINS"))
            elif kind in ("dir", "file") and isinstance(source.get("path"), str) and local is None:
                local = os.path.join(base, source["path"])
        if local is not None:
            download, version = _local_origin(local, root, repo_url, commit, subs)
            key = (name, download)
            if key not in seen:
                seen.add(key)
                out.append((_package(spdx_id("Module", name), name, download, version=version,
                                     purpose="SOURCE",
                                     comment="built from this repository or its submodule"),
                            "CONTAINS"))
    return out


def merge(syft_doc, frontend, row, repo_url, commit, root=ROOT, subs=None):
    """The Syft document with the app, its runtime and its modules added."""
    doc = json.loads(json.dumps(syft_doc))
    if doc.get("spdxVersion", "").split("-")[0] != "SPDX":
        raise SbomError("the Syft output is not an SPDX JSON document")
    app_id = row["app-id"]
    app = _package(spdx_id("Flatpak", frontend), app_id, _git_location(repo_url, commit),
                   version=commit, purpose="APPLICATION",
                   comment=f"the {frontend} frontend's Flatpak, built from {row['manifest-path']}")
    packages = doc.setdefault("packages", [])
    relationships = doc.setdefault("relationships", [])

    # What Syft's document described now sits inside the app.
    for rel in relationships:
        if rel.get("spdxElementId") == DOCUMENT and rel.get("relationshipType") == "DESCRIBES":
            rel["spdxElementId"] = app["SPDXID"]
            rel["relationshipType"] = "CONTAINS"
    relationships.append({"spdxElementId": DOCUMENT, "relationshipType": "DESCRIBES",
                          "relatedSpdxElement": app["SPDXID"]})
    if "documentDescribes" in doc:
        doc["documentDescribes"] = [app["SPDXID"]]
    packages.insert(0, app)

    taken = {p.get("SPDXID") for p in packages}
    manifest_path = os.path.join(root, row["manifest-path"])
    for pkg, relation in manifest_packages(manifest_path, repo_url, commit, root, subs):
        base, n = pkg["SPDXID"], 2
        while pkg["SPDXID"] in taken:
            pkg["SPDXID"] = f"{base}-{n}"
            n += 1
        taken.add(pkg["SPDXID"])
        packages.append(pkg)
        if relation == "BUILD_TOOL_OF":
            relationships.append({"spdxElementId": pkg["SPDXID"], "relationshipType": relation,
                                  "relatedSpdxElement": app["SPDXID"]})
        else:
            relationships.append({"spdxElementId": app["SPDXID"], "relationshipType": relation,
                                  "relatedSpdxElement": pkg["SPDXID"]})
    doc["name"] = f"{app_id}-{commit[:12]}"
    return doc


def check(doc, frontend, row, commit=None):
    """Problems with an SBOM that merge() wrote; [] when it is sound.

    Both the dry run on pull requests and dev (sbom.yml) and the release
    job's "Check the SBOMs" step run this, so a pull request proves the
    check that a release applies.
    """
    problems = []
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    if not str(doc.get("spdxVersion", "")).startswith("SPDX-2."):
        problems.append(f"spdxVersion is {doc.get('spdxVersion')!r}, not SPDX-2.x")
    if doc.get("SPDXID") != DOCUMENT:
        problems.append(f"document SPDXID is {doc.get('SPDXID')!r}")
    for key in ("dataLicense", "documentNamespace", "creationInfo", "name"):
        if not doc.get(key):
            problems.append(f"no {key}")
    packages = doc.get("packages") or []
    ids = [p.get("SPDXID") for p in packages if isinstance(p, dict)]
    if len(ids) != len(packages):
        problems.append("a package is not an object")
    for dup in sorted({i for i in ids if ids.count(i) > 1}, key=str):
        problems.append(f"SPDXID {dup} is used more than once")
    for spdxid in ids:
        if not re.fullmatch(r"SPDXRef-[A-Za-z0-9.-]+", str(spdxid)):
            problems.append(f"SPDXID {spdxid!r} is not valid")
    known = set(ids) | {DOCUMENT}
    for rel in doc.get("relationships") or []:
        for end in ("spdxElementId", "relatedSpdxElement"):
            if rel.get(end) not in known:
                problems.append(f"relationship {rel.get('relationshipType')} names unknown {rel.get(end)!r}")
    by_id = {p.get("SPDXID"): p for p in packages if isinstance(p, dict)}
    described = [r.get("relatedSpdxElement") for r in doc.get("relationships") or []
                 if r.get("spdxElementId") == DOCUMENT and r.get("relationshipType") == "DESCRIBES"]
    if len(described) != 1:
        problems.append(f"the document DESCRIBES {len(described)} elements, not 1")
    else:
        app = by_id.get(described[0], {})
        if app.get("name") != row["app-id"]:
            problems.append(f"the document describes {app.get('name')!r}, not {row['app-id']!r} "
                            f"({frontend})")
        if commit and app.get("versionInfo") != commit:
            problems.append(f"the app is at {app.get('versionInfo')!r}, not {commit}")
    if len(packages) < 3:
        problems.append(f"only {len(packages)} packages: no runtime or modules")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("stage", help="copy the frontend's lock files for Syft")
    s.add_argument("--frontend", required=True)
    s.add_argument("--into", required=True)
    m = sub.add_parser("merge", help="add the Flatpak manifest to Syft's SPDX document")
    m.add_argument("--frontend", required=True)
    m.add_argument("--syft", required=True, help="the SPDX JSON that Syft wrote")
    m.add_argument("--out", required=True)
    m.add_argument("--repo-url", required=True)
    m.add_argument("--commit", required=True)
    c = sub.add_parser("check", help="check SBOMs that merge wrote")
    c.add_argument("--commit", help="the commit the app must be at")
    c.add_argument("files", nargs="+", metavar="<frontend>.spdx.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            table = frontend_table.load()
            failed = False
            for path in args.files:
                frontend = os.path.basename(path).split(".", 1)[0]
                if not os.path.isfile(path) or os.path.getsize(path) == 0:
                    problems = ["missing or empty"]
                else:
                    with open(path, encoding="utf-8") as stream:
                        problems = check(json.load(stream), frontend,
                                         frontend_table.row_for(frontend, table), args.commit)
                for problem in problems:
                    print(f"::error::{path}: {problem}")
                failed = failed or bool(problems)
                if not problems:
                    print(f"{path}: ok")
            return 1 if failed else 0
        if args.command == "stage":
            for rel in stage(args.frontend, args.into):
                print(f"staged {rel}")
            return 0
        row = frontend_table.row_for(args.frontend, frontend_table.load())
        with open(args.syft, encoding="utf-8") as stream:
            doc = merge(json.load(stream), args.frontend, row, args.repo_url, args.commit)
        with open(args.out, "w", encoding="utf-8") as stream:
            json.dump(doc, stream, indent=2, sort_keys=False)
            stream.write("\n")
        print(f"{args.out}: {len(doc['packages'])} packages")
        return 0
    except (SbomError, frontend_table.TableError, flatpak_manifest.ManifestError,
            OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"::error::{error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
