"""release.yml: an SPDX SBOM per frontend and build provenance (#151).

A release carries <frontend>.spdx.json for each of the five frontends and a
GitHub build-provenance attestation for each .flatpak bundle and SBOM. Only a
run on `prod` (or a v* tag) proves the workflow, so these tests hold the
parts that a wrong edit would break without a red check here: the jobs, their
permissions, the pins, the assets, and shared/ci/flatpak_sbom.py against the
manifests that it reads.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "ci"))

import flatpak_manifest  # noqa: E402
import flatpak_sbom as fs  # noqa: E402
import frontend_table  # noqa: E402

RELEASE = os.path.join(REPO, ".github", "workflows", "release.yml")
SBOM = os.path.join(REPO, ".github", "workflows", "sbom.yml")
RELEASE_DOC = os.path.join(REPO, "docs", "RELEASE.md")
TABLE = frontend_table.load()
FRONTENDS = list(TABLE)

# Node 24 releases, each SHA checked as the tag's commit with
# `git ls-remote https://github.com/<repo> refs/tags/<tag>*`. The workflows
# name the exact tag; .github/workflows/actions.lock holds the commit.
SBOM_ACTION = ("anchore/sbom-action", "v0.24.3", "66cbf4bc1f1c0d2edc94016e65bc221b6bb0ad6c")
ATTEST_ACTION = ("actions/attest-build-provenance", "v4.2.2", "4d101475d8b20a2381f78447822ac1eab6504dd8")
ACTIONS_LOCK = os.path.join(REPO, ".github", "workflows", "actions.lock")
SPDX_ID = re.compile(r"^SPDXRef-[A-Za-z0-9.-]+$")


def _text(path=RELEASE):
    with open(path, encoding="utf-8") as stream:
        return stream.read()


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(_text())


@pytest.fixture(scope="module")
def jobs(workflow):
    return workflow["jobs"]


@pytest.fixture(scope="module")
def sbom_wf():
    return yaml.safe_load(_text(SBOM))


@pytest.fixture(scope="module")
def leg(sbom_wf):
    """The one job of sbom.yml: the release legs and the dry run are this."""
    (job,) = sbom_wf["jobs"].values()
    return job


def _uses(job, prefix):
    return [s for s in job["steps"] if str(s.get("uses", "")).startswith(prefix)]


def _step_index(job, predicate):
    return next(i for i, s in enumerate(job["steps"]) if predicate(s))


# ------------------------------------------------------------ the gating


def test_release_runs_only_on_prod_or_a_tag(workflow, jobs):
    """No push to `dev` (or any branch) starts the workflow that publishes."""
    on = workflow.get("on", workflow.get(True))
    assert set(on) == {"workflow_dispatch", "push"}
    assert on["push"] == {"tags": ["v*"]}
    guard = jobs["guard"]["steps"][0]
    assert guard["name"] == "Only prod or a tag"
    assert "refs/heads/prod|refs/tags/v*) ;;" in guard["run"]
    assert "exit 1" in guard["run"]


def test_sbom_and_release_wait_for_the_guard(jobs):
    assert jobs["sbom"]["needs"] == "guard"
    assert set(jobs["release"]["needs"]) == {"guard", "build", "sbom"}
    assert "needs.guard.result == 'success'" in jobs["release"]["if"]


# ------------------------------------------------------------ permissions


def test_only_the_release_job_can_sign(workflow, jobs, sbom_wf, leg):
    assert jobs["release"]["permissions"] == {
        "contents": "write", "id-token": "write", "attestations": "write"}
    for perms in (workflow["permissions"], sbom_wf["permissions"], leg["permissions"]):
        assert "id-token" not in perms and "attestations" not in perms
    for name, job in jobs.items():
        if name == "release":
            continue
        perms = job.get("permissions") or {}
        assert "id-token" not in perms and "attestations" not in perms, name


def test_the_sbom_path_reads_only(jobs, sbom_wf, leg):
    assert jobs["sbom"]["permissions"] == {"contents": "read"}
    assert sbom_wf["permissions"] == {"contents": "read"}
    assert leg["permissions"] == {"contents": "read"}


# ------------------------------------------------------------ one definition


def test_the_release_calls_sbom_yml(jobs):
    """The release legs are sbom.yml itself, not a copy of its steps."""
    job = jobs["sbom"]
    assert job["uses"] == "$/.github/workflows/sbom.yml"
    assert "with" not in job
    assert "steps" not in job


def test_no_other_workflow_copies_the_sbom_steps():
    workflows = os.path.join(REPO, ".github", "workflows")
    for name in os.listdir(workflows):
        if name == "sbom.yml" or name == "actions.lock":
            continue
        text = _text(os.path.join(workflows, name))
        assert "anchore/sbom-action" not in text, name
        assert "flatpak_sbom.py stage" not in text and "flatpak_sbom.py merge" not in text, name


def test_the_dry_run_runs_on_pull_requests_and_dev(sbom_wf):
    on = sbom_wf.get("on", sbom_wf.get(True))
    assert set(on) == {"workflow_call", "pull_request", "push", "workflow_dispatch"}
    assert on["push"]["branches"] == ["dev"]
    assert on["push"]["paths"] == on["pull_request"]["paths"]
    paths = on["pull_request"]["paths"]
    for needed in ("shared/ci/flatpak_sbom.py", "shared/ci/frontends.json", "shared/flatpak/**",
                   "flatpak/*.json", "frontends/*/flatpak/*.json", "fisherman",
                   ".github/workflows/sbom.yml", ".github/workflows/release.yml"):
        assert needed in paths
    for lock in {f for files in fs.LOCKFILES.values() for f in files}:
        if not lock.startswith("fisherman/"):
            assert lock in paths, lock
    assert not (on["workflow_call"] or {}).get("inputs")


def test_the_leg_name_has_only_the_matrix_in_it(leg):
    """Release run: "SBOM / SBOM (<frontend>)"; dry run: "SBOM (<frontend>)"."""
    assert leg["name"] == "SBOM (${{ matrix.frontend }})"


def test_the_promotion_gate_waits_for_the_dry_run():
    promote = yaml.safe_load(_text(os.path.join(REPO, ".github", "workflows", "promote.yml")))
    on = promote.get("on", promote.get(True))
    assert "SBOM" in on["workflow_run"]["workflows"]


# ------------------------------------------------------------ the sbom legs


def test_one_sbom_leg_per_frontend(leg):
    assert leg["strategy"]["matrix"]["frontend"] == FRONTENDS
    assert leg["strategy"]["fail-fast"] is False


def test_the_sbom_leg_uses_syft_in_spdx_and_publishes_nothing(leg):
    checkout = _uses(leg, "actions/checkout@")[0]
    assert checkout["with"]["submodules"] is True  # fisherman's go.mod
    (syft,) = _uses(leg, "anchore/sbom-action@")
    assert syft["with"]["format"] == "spdx-json"
    assert syft["with"]["upload-release-assets"] is False
    assert syft["with"]["upload-artifact"] is False
    assert syft["with"]["path"] == "sbom-src/${{ matrix.frontend }}"
    runs = "\n".join(s.get("run", "") for s in leg["steps"])
    assert "flatpak_sbom.py stage" in runs and "flatpak_sbom.py merge" in runs
    assert 'flatpak_sbom.py check --commit "$SHA"' in runs
    for forbidden in ("gh release", "gh attestation", "skopeo", "cosign", "git push"):
        assert forbidden not in runs
    uses = [str(s.get("uses", "")).split("@")[0] for s in leg["steps"] if s.get("uses")]
    assert uses == ["actions/checkout", "anchore/sbom-action", "actions/upload-artifact"]
    (upload,) = _uses(leg, "actions/upload-artifact@")
    assert upload["with"]["name"] == "sbom-${{ matrix.frontend }}"
    assert upload["with"]["if-no-files-found"] == "error"
    order = [s.get("name") or s["uses"].split("@")[0] for s in leg["steps"]]
    assert order.index("Add the Flatpak manifest") < order.index("Check the SBOM") \
        < order.index("actions/upload-artifact")


# ------------------------------------------------------------ the release job


def test_the_release_attests_before_it_publishes(jobs):
    job = jobs["release"]
    (attest,) = _uses(job, "actions/attest-build-provenance@")
    subjects = attest["with"]["subject-path"].split()
    assert subjects == ["*.flatpak", "*.spdx.json"]
    at = _step_index(job, lambda s: str(s.get("uses", "")).startswith("actions/attest-"))
    sboms = _step_index(job, lambda s: s.get("with", {}).get("pattern") == "sbom-*")
    check = _step_index(job, lambda s: s.get("name") == "Check the SBOMs")
    create = _step_index(job, lambda s: s.get("name") == "Create the release")
    assert sboms < check < at < create


def test_the_release_checks_and_attaches_five_sboms(jobs):
    job = jobs["release"]
    check = next(s for s in job["steps"] if s.get("name") == "Check the SBOMs")["run"]
    # The same check as each sbom.yml leg, on all five downloaded files.
    assert 'flatpak_sbom.py check --commit "$SHA"' in check
    assert check.split("check --commit \"$SHA\"", 1)[1].split() == [
        "\\"] + [f"{f}.spdx.json" for f in FRONTENDS]
    create = next(s for s in job["steps"] if s.get("name") == "Create the release")["run"]
    assets = create.split("assets=(", 1)[1].split(")", 1)[0].split()
    for frontend in FRONTENDS:
        assert f"{frontend}.spdx.json" in assets
    assert "org.bootcinstaller.Installer.flatpak" in assets


def _lock():
    return yaml.safe_load(_text(ACTIONS_LOCK))


@pytest.mark.parametrize("path", [RELEASE, SBOM])
def test_every_action_is_an_exact_tag_in_the_lockfile(path):
    lock = _lock()
    locked = {entry.lower() for entry in lock["workflows"][os.path.relpath(path, REPO)]}
    for line in _text(path).splitlines():
        match = re.match(r"\s*-?\s*uses:\s*(\S+)", line)
        if not match or match.group(1).startswith(("./", "$/")):
            continue
        ref = match.group(1).split("@", 1)[1]
        assert re.fullmatch(r"v\d+\.\d+\.\d+", ref), line
        assert match.group(1).lower() in locked, line


def test_the_new_actions_are_the_node24_pins():
    lock = _lock()
    for path, (action, tag, sha) in ((SBOM, SBOM_ACTION), (RELEASE, ATTEST_ACTION)):
        assert f"uses: {action}@{tag}" in _text(path)
        assert lock["dependencies"][f"{action}@{tag}"]["commit"] == f"sha1-{sha}"


def test_release_doc_says_how_to_verify():
    with open(RELEASE_DOC, encoding="utf-8") as stream:
        doc = stream.read()
    assert "## Verify a release" in doc
    assert "gh attestation verify" in doc
    assert "--repo tuna-os/bootc-installer" in doc
    assert ".spdx.json" in doc


# ------------------------------------------------------------ flatpak_sbom.py


def test_every_frontend_has_a_lock_file_list():
    assert set(fs.LOCKFILES) == set(FRONTENDS)
    for frontend in FRONTENDS:
        assert fs.lockfiles(frontend)


def _build_commands(frontend):
    path = os.path.join(REPO, TABLE[frontend]["manifest-path"])
    return {m.get("name"): " ".join(m.get("build-commands") or [])
            for m, _ in flatpak_manifest.walk(path)}


def test_the_lock_files_are_the_ones_the_manifests_build():
    for frontend in FRONTENDS:
        cmds = _build_commands(frontend)
        assert "go build -C fisherman" in cmds["fisherman"], frontend
        assert "fisherman/fisherman/go.mod" in fs.LOCKFILES[frontend]
    assert "go build -C installer" in _build_commands("niri")["tuna-installer-niri"]
    assert "frontends/niri/installer/go.mod" in fs.LOCKFILES["niri"]
    assert "cargo --offline build" in _build_commands("cosmic")["tuna-installer-cosmic"]
    assert "frontends/cosmic/Cargo.lock" in fs.LOCKFILES["cosmic"]


def test_stage_copies_only_the_lock_files():
    with tempfile.TemporaryDirectory() as into:
        copied = fs.stage("cosmic", into)
        found = sorted(os.path.relpath(os.path.join(d, f), into)
                       for d, _, files in os.walk(into) for f in files)
        assert found == sorted(copied)
        assert "frontends/cosmic/Cargo.lock" in found


def test_an_unknown_frontend_is_an_error():
    with pytest.raises(fs.SbomError):
        fs.lockfiles("nope")


SYFT = {
    "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
    "name": "sbom-src", "documentNamespace": "https://anchore.com/syft/dir/sbom-src",
    "creationInfo": {"creators": ["Tool: syft"], "created": "2026-11-12T00:00:00Z"},
    "packages": [{"SPDXID": "SPDXRef-DocumentRoot-Directory-sbom-src", "name": "sbom-src",
                  "downloadLocation": "NOASSERTION"}],
    "relationships": [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                       "relatedSpdxElement": "SPDXRef-DocumentRoot-Directory-sbom-src"}],
}
REPO_URL = "https://github.com/tuna-os/bootc-installer"
COMMIT = "a" * 40


def _gitlink():
    out = subprocess.run(["git", "-C", REPO, "ls-tree", "HEAD", "fisherman"],
                         capture_output=True, text=True, check=True).stdout.split()
    return out[2]


@pytest.mark.parametrize("frontend", FRONTENDS)
def test_merge_describes_the_flatpak_and_its_manifest(frontend):
    doc = fs.merge(SYFT, frontend, TABLE[frontend], REPO_URL, COMMIT)
    by_id = {p["SPDXID"]: p for p in doc["packages"]}
    assert len(by_id) == len(doc["packages"]), "SPDX ids must be unique"
    for spdxid in by_id:
        assert SPDX_ID.match(spdxid), spdxid
    describes = [r for r in doc["relationships"]
                 if r["spdxElementId"] == "SPDXRef-DOCUMENT" and r["relationshipType"] == "DESCRIBES"]
    assert len(describes) == 1
    app = by_id[describes[0]["relatedSpdxElement"]]
    assert app["name"] == TABLE[frontend]["app-id"]
    assert app["versionInfo"] == COMMIT
    assert app["downloadLocation"] == f"git+{REPO_URL}@{COMMIT}"
    # What Syft found now sits inside the app.
    assert {"spdxElementId": app["SPDXID"], "relationshipType": "CONTAINS",
            "relatedSpdxElement": "SPDXRef-DocumentRoot-Directory-sbom-src"} in doc["relationships"]
    for rel in doc["relationships"]:
        assert rel["spdxElementId"] in by_id or rel["spdxElementId"] == "SPDXRef-DOCUMENT"
        assert rel["relatedSpdxElement"] in by_id

    manifest = json.load(open(os.path.join(REPO, TABLE[frontend]["manifest-path"]),
                              encoding="utf-8"))
    names = {p["name"] for p in doc["packages"]}
    assert manifest["runtime"] in names and manifest["sdk"] in names
    # Every remote source of the manifest and its includes is listed.
    locations = {p["downloadLocation"] for p in doc["packages"]}
    sums = {c["checksumValue"] for p in doc["packages"] for c in p.get("checksums", [])}
    for module, _ in flatpak_manifest.walk(os.path.join(REPO, TABLE[frontend]["manifest-path"])):
        for source in module.get("sources") or []:
            if isinstance(source, dict) and source.get("type") in ("archive", "file") \
                    and source.get("url"):
                assert source["url"] in locations
                if source.get("sha256"):
                    assert source["sha256"] in sums
            if isinstance(source, dict) and source.get("type") == "git":
                assert any(loc.startswith("git+" + source["url"].removesuffix(".git"))
                           for loc in locations), source["url"]
    # fisherman is at the submodule's gitlink, not at the release commit.
    fisherman = next(p for p in doc["packages"] if p["name"] == "fisherman")
    assert fisherman["versionInfo"] == _gitlink()
    assert fisherman["downloadLocation"].startswith("git+https://github.com/tuna-os/fisherman@")


def test_merge_does_not_change_its_input():
    before = json.dumps(SYFT, sort_keys=True)
    fs.merge(SYFT, "kde", TABLE["kde"], REPO_URL, COMMIT)
    assert json.dumps(SYFT, sort_keys=True) == before


def test_merge_refuses_a_document_that_is_not_spdx():
    with pytest.raises(fs.SbomError):
        fs.merge({"bomFormat": "CycloneDX"}, "kde", TABLE["kde"], REPO_URL, COMMIT)


@pytest.mark.parametrize("frontend", FRONTENDS)
def test_check_accepts_what_merge_writes(frontend):
    doc = fs.merge(SYFT, frontend, TABLE[frontend], REPO_URL, COMMIT)
    assert fs.check(doc, frontend, TABLE[frontend], COMMIT) == []


def test_check_refuses_a_broken_sbom():
    row = TABLE["kde"]
    good = fs.merge(SYFT, "kde", row, REPO_URL, COMMIT)
    assert fs.check(good, "cosmic", TABLE["cosmic"], COMMIT)      # another app
    assert fs.check(good, "kde", row, "b" * 40)                   # another commit
    assert fs.check(dict(good, spdxVersion="SPDX-3.0"), "kde", row)
    bad = json.loads(json.dumps(good))
    bad["packages"].append(dict(bad["packages"][1]))
    assert any("more than once" in p for p in fs.check(bad, "kde", row))
    bad = json.loads(json.dumps(good))
    bad["relationships"].append({"spdxElementId": "SPDXRef-DOCUMENT",
                                 "relationshipType": "DESCRIBES",
                                 "relatedSpdxElement": "SPDXRef-nope"})
    problems = fs.check(bad, "kde", row)
    assert any("unknown" in p for p in problems) and any("DESCRIBES 2" in p for p in problems)
    assert fs.check(SYFT, "kde", row)                             # Syft alone is not enough


def test_check_cli_fails_on_a_missing_file():
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "kde.spdx.json")
        with open(good, "w", encoding="utf-8") as stream:
            json.dump(fs.merge(SYFT, "kde", TABLE["kde"], REPO_URL, COMMIT), stream)
        assert fs.main(["check", "--commit", COMMIT, good]) == 0
        assert fs.main(["check", "--commit", COMMIT, good, os.path.join(d, "xfce.spdx.json")]) == 1


# The shape Syft v1.54.0 writes for a directory with a Cargo.lock: the crate
# packages, a File element for the lock file, and an OTHER ("evident by")
# relationship from each crate to that file. The first dry run of
# `SBOM (cosmic)` failed `check` on it: the File element was in the document,
# but `check` counted only packages as elements.
SYFT_CARGO = {
    "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
    "name": "sbom-src/cosmic",
    "documentNamespace": "https://anchore.com/syft/dir/sbom-src/cosmic-0",
    "creationInfo": {"creators": ["Organization: Anchore, Inc", "Tool: syft-1.54.0"],
                     "created": "2026-11-12T00:00:00Z"},
    "packages": [
        {"SPDXID": "SPDXRef-Package-rust-crate-serde-1a2b", "name": "serde",
         "versionInfo": "1.0.228", "downloadLocation": "NOASSERTION",
         "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                           "referenceLocator": "pkg:cargo/serde@1.0.228"}]},
        {"SPDXID": "SPDXRef-Package-rust-crate-libc-3c4d", "name": "libc",
         "versionInfo": "0.2.177", "downloadLocation": "NOASSERTION"},
        {"SPDXID": "SPDXRef-DocumentRoot-Directory-sbom-src-cosmic", "name": "sbom-src/cosmic",
         "downloadLocation": "NOASSERTION", "primaryPackagePurpose": "FILE"},
    ],
    "files": [
        {"fileName": "frontends/cosmic/Cargo.lock",
         "SPDXID": "SPDXRef-File-frontends-cosmic-Cargo.lock-afca095b6ecaa6bf",
         "checksums": [{"algorithm": "SHA1",
                        "checksumValue": "0000000000000000000000000000000000000000"}],
         "licenseConcluded": "NOASSERTION", "copyrightText": ""},
    ],
    "relationships": [
        {"spdxElementId": "SPDXRef-DocumentRoot-Directory-sbom-src-cosmic",
         "relationshipType": "CONTAINS",
         "relatedSpdxElement": "SPDXRef-Package-rust-crate-serde-1a2b"},
        {"spdxElementId": "SPDXRef-DocumentRoot-Directory-sbom-src-cosmic",
         "relationshipType": "CONTAINS",
         "relatedSpdxElement": "SPDXRef-Package-rust-crate-libc-3c4d"},
        {"spdxElementId": "SPDXRef-Package-rust-crate-serde-1a2b", "relationshipType": "OTHER",
         "relatedSpdxElement": "SPDXRef-File-frontends-cosmic-Cargo.lock-afca095b6ecaa6bf",
         "comment": "evident-by: indicates the package's existence is evident by the given file"},
        {"spdxElementId": "SPDXRef-Package-rust-crate-libc-3c4d", "relationshipType": "OTHER",
         "relatedSpdxElement": "SPDXRef-File-frontends-cosmic-Cargo.lock-afca095b6ecaa6bf",
         "comment": "evident-by: indicates the package's existence is evident by the given file"},
        {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
         "relatedSpdxElement": "SPDXRef-DocumentRoot-Directory-sbom-src-cosmic"},
    ],
}


def test_check_accepts_syft_cargo_evidence_files():
    doc = fs.merge(SYFT_CARGO, "cosmic", TABLE["cosmic"], REPO_URL, COMMIT)
    # merge keeps Syft's File elements, so the evident-by links resolve.
    assert doc["files"] == SYFT_CARGO["files"]
    assert fs.check(doc, "cosmic", TABLE["cosmic"], COMMIT) == []
    names = {p["name"] for p in doc["packages"]}
    assert {"serde", "libc"} <= names


def test_check_still_refuses_a_dangling_file_reference():
    doc = fs.merge(SYFT_CARGO, "cosmic", TABLE["cosmic"], REPO_URL, COMMIT)
    del doc["files"]
    problems = fs.check(doc, "cosmic", TABLE["cosmic"], COMMIT)
    assert any("OTHER names unknown 'SPDXRef-File-frontends-cosmic-Cargo.lock" in p
               for p in problems), problems


def test_check_refuses_a_file_id_that_a_package_also_uses():
    doc = fs.merge(SYFT_CARGO, "cosmic", TABLE["cosmic"], REPO_URL, COMMIT)
    doc["files"][0]["SPDXID"] = "SPDXRef-Package-rust-crate-libc-3c4d"
    assert any("more than once" in p for p in fs.check(doc, "cosmic", TABLE["cosmic"], COMMIT))
