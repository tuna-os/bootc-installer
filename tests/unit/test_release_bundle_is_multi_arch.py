"""The release bundle must exist for aarch64, and must not gate x86_64.

A flatpak bundle carries refs for ONE architecture. The production bundle was
x86_64-only, so an aarch64 live ISO downloaded it, imported
`app/org.bootcinstaller.Installer/x86_64/master`, and then found nothing for
its own arch:

    error: Nothing matches org.bootcinstaller.Installer in remote installer-local

(tuna-os/tunaOS gurnard run 32495176056, iso:pantheon linux-arm64 — issue #25.)
The arm64 ISO could therefore never carry the installer, and nothing
downstream of it was exercisable on that arch.

The fix is a separate job, not a matrix leg, and that distinction is the
thing most likely to be "tidied" later into a regression: ONE failing matrix
leg fails the whole job, which would skip the release entirely. x86_64
releases work today and must not become contingent on a newer arch. So the
tests below pin the independence as firmly as the existence.

Since the promote/release flow, the bundles are built by flatpak.yml and the
release is cut by release.yml's `release` job, which calls flatpak.yml as a
reusable workflow. That call's result is red whenever the aarch64 leg is red,
so the independence now lives in the `release` job's `if:` (it runs on
`!cancelled()`) plus the optional aarch64 download, and the tests read both
files.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "flatpak.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"

X86_BUNDLE = "org.bootcinstaller.Installer.flatpak"
ARM_BUNDLE = "org.bootcinstaller.Installer-aarch64.flatpak"


@pytest.fixture(scope="module")
def jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


@pytest.fixture(scope="module")
def release_job() -> dict:
    return yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"]["release"]


def _builder(job: dict) -> dict:
    return next(s for s in job["steps"]
                if str(s.get("uses", "")).startswith("flatpak/flatpak-github-actions"))


# ------------------------------------------------------------------ it exists


def test_an_aarch64_production_bundle_is_built(jobs):
    job = jobs["production-aarch64"]
    assert job["runs-on"] == "ubuntu-24.04-arm"
    assert _builder(job)["with"]["bundle"] == ARM_BUNDLE


def test_both_arches_build_the_same_manifest(jobs):
    """Different arch, same app — not a divergent second application."""
    manifests = {
        _builder(jobs[name])["with"]["manifest-path"]
        for name in ("production", "production-aarch64")
    }
    assert manifests == {"flatpak/org.bootcinstaller.Installer.json"}


def test_the_aarch64_build_asks_for_aarch64_refs(jobs):
    """`arch:` is required, and the first version of this file asserted the
    opposite.

    The action does NOT default to the runner's architecture — its default is
    the literal x86_64. Omitting it on an arm64 runner installed
    org.gnome.Sdk/x86_64/50 and then tried to run those binaries under bwrap:

        bwrap: execvp /bin/sh: Exec format error
        Error: module mutter-schemas: Child process exited with code 1

    (run 32534151231.) The test that asserted the absence of the input
    encoded that wrong assumption and would have blocked the fix, which is
    why this one asserts the value instead."""
    assert _builder(jobs["production-aarch64"])["with"]["arch"] == "aarch64"


def test_the_aarch64_job_blocks_now_that_it_passes(jobs):
    """The inverse of what this test asserted until #27, and deliberately not
    a deletion.

    It was continue-on-error while libbge installed bge.h without the headers
    bge.h #includes, so libpastry could not compile. That was NOT
    arch-specific, which is what the old version of this docstring claimed on
    the strength of x86_64 passing: x86_64 omits the same headers and passed
    only because libbge's .pc lands in /app/lib64/pkgconfig while the manifest
    symlinks into /app/lib/pkgconfig — a dangling link, so meson never found
    libbge as a system dependency and fell back to the vendored bazaar
    subproject instead. aarch64 has no lib64, the link resolved, and the real
    gap surfaced.

    #27 installs the headers; run 32550801038 built the bundle green at
    623f61f4 and release v2026.08.22-623f61f4 carries the aarch64 asset. An
    arch that is shipping must fail loudly, so this asserts the absence rather
    than being deleted — deleting it would let the line drift back in
    unnoticed."""
    assert "continue-on-error" not in jobs["production-aarch64"]


def test_the_x86_64_build_never_becomes_non_blocking(jobs):
    """It never was non-blocking, and must not become so. When aarch64 was
    the knowingly-broken arch, the exemption was scoped to it alone;
    now that neither is exempt, both of these assertions say the same
    thing and both are meant to keep saying it."""
    assert "continue-on-error" not in jobs["production"]


def test_the_x86_64_build_is_left_alone(jobs):
    """It works today on the action's default; adding an explicit arch there
    would be an unrelated change to a working path."""
    assert "arch" not in _builder(jobs["production"]).get("with", {})


def test_the_two_builds_do_not_share_a_cache_key(jobs):
    """Sharing one key would let an x86_64 cache satisfy the aarch64 build."""
    keys = {
        _builder(jobs[name])["with"]["cache-key"]
        for name in ("production", "production-aarch64")
    }
    assert len(keys) == 2


# ------------------------------------------- and it does not gate the old one


def test_the_release_job_does_not_wait_for_a_green_aarch64_build(release_job):
    """The regression this guards: making the release contingent on a newer
    arch would stop x86_64 releases the first time that leg breaks. The
    `build` dependency is the whole reusable flatpak.yml, so a red aarch64 leg
    makes it red; the job must run anyway and let the required x86_64
    download decide."""
    assert "build" in release_job["needs"]
    assert "!cancelled()" in str(release_job.get("if", "")), release_job.get("if")


def test_the_aarch64_bundle_is_not_a_matrix_leg_of_production(jobs):
    """One failing matrix leg fails the whole job, and both release jobs
    `needs: [production]`."""
    assert "strategy" not in jobs["production"]


def test_the_release_job_downloads_the_aarch64_bundle_optionally(release_job):
    step = next(
        s for s in release_job["steps"]
        if ARM_BUNDLE in str(s.get("with", {}).get("name", ""))
    )
    assert step.get("continue-on-error") is True


def test_the_x86_64_and_devel_downloads_are_not_optional(release_job):
    """The inverse: the assets every downstream fetches must fail the job
    when absent, not silently drop out of the asset list."""
    for name in (X86_BUNDLE, "org.bootcinstaller.Installer.Devel.flatpak"):
        step = next(
            s for s in release_job["steps"]
            if str(s.get("with", {}).get("name", "")) == name
        )
        assert not step.get("continue-on-error"), name


def test_a_missing_aarch64_bundle_still_releases_x86_64(release_job):
    """Absence is a warning and a shorter asset list, never a failure."""
    run = "\n".join(s.get("run", "") for s in release_job["steps"])
    assert f"[ -f {ARM_BUNDLE} ]" in run
    assert "releasing x86_64 only" in run
    assert X86_BUNDLE in run


def test_the_x86_64_asset_name_is_unchanged(jobs, release_job):
    """Downstreams fetch releases/latest/download/<this exact name>; renaming
    it would break every existing consumer, tunaOS's live ISO included."""
    assert _builder(jobs["production"])["with"]["bundle"] == X86_BUNDLE
    run = "\n".join(s.get("run", "") for s in release_job["steps"])
    assert f"releases/latest/download/{X86_BUNDLE}" in run


def test_releases_are_never_cut_from_dev(jobs):
    """flatpak.yml builds and keeps the dev PRE-release current; the real,
    --latest release is release.yml's job on prod (docs/RELEASE.md)."""
    for job in jobs.values():
        run = "\n".join(s.get("run", "") for s in job.get("steps", []))
        assert "--latest" not in run
        assert "gh release create latest-dev" in run or "gh release create" not in run
