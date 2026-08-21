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
thing most likely to be "tidied" later into a regression: `auto-release` and
`publish-tagged-release` both `needs: [production]`, and ONE failing matrix
leg fails the whole job, which would skip the release entirely. x86_64
releases work today and must not become contingent on a newer arch. So the
tests below pin the independence as firmly as the existence.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "flatpak.yml"

X86_BUNDLE = "org.bootcinstaller.Installer.flatpak"
ARM_BUNDLE = "org.bootcinstaller.Installer-aarch64.flatpak"


@pytest.fixture(scope="module")
def jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


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


def test_the_aarch64_build_is_native_not_cross(jobs):
    """The runner is aarch64, so no `arch:` input belongs here. Passing one on
    an x86_64 runner would request a cross-build this manifest is not set up
    for, and would produce a bundle that fails at install rather than at
    build."""
    assert "arch" not in _builder(jobs["production-aarch64"]).get("with", {})


def test_the_two_builds_do_not_share_a_cache_key(jobs):
    """Sharing one key would let an x86_64 cache satisfy the aarch64 build."""
    keys = {
        _builder(jobs[name])["with"]["cache-key"]
        for name in ("production", "production-aarch64")
    }
    assert len(keys) == 2


# ------------------------------------------- and it does not gate the old one


def test_neither_release_job_depends_on_the_aarch64_build(jobs):
    """The regression this guards: making the release contingent on a newer
    arch would stop x86_64 releases the first time that leg breaks."""
    for name in ("auto-release", "publish-tagged-release"):
        assert "production-aarch64" not in jobs[name]["needs"], name
        assert "production" in jobs[name]["needs"], name


def test_the_aarch64_bundle_is_not_a_matrix_leg_of_production(jobs):
    """One failing matrix leg fails the whole job, and both release jobs
    `needs: [production]`."""
    assert "strategy" not in jobs["production"]


def test_both_release_jobs_download_the_aarch64_bundle_optionally(jobs):
    for name in ("auto-release", "publish-tagged-release"):
        step = next(
            s for s in jobs[name]["steps"]
            if ARM_BUNDLE in str(s.get("with", {}).get("name", ""))
        )
        assert step.get("continue-on-error") is True, name


def test_a_missing_aarch64_bundle_still_releases_x86_64(jobs):
    """Absence is a warning and a shorter asset list, never a failure."""
    for name in ("auto-release", "publish-tagged-release"):
        run = "\n".join(s.get("run", "") for s in jobs[name]["steps"])
        assert f"[ -f {ARM_BUNDLE} ]" in run, name
        assert "releasing x86_64 only" in run, name
        assert X86_BUNDLE in run, name


def test_the_x86_64_asset_name_is_unchanged(jobs):
    """Downstreams fetch releases/latest/download/<this exact name>; renaming
    it would break every existing consumer, tunaOS's live ISO included."""
    assert _builder(jobs["production"])["with"]["bundle"] == X86_BUNDLE
    run = "\n".join(s.get("run", "") for s in jobs["auto-release"]["steps"])
    assert f"releases/latest/download/{X86_BUNDLE}" in run
