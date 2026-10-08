"""shared/ci/published_freshness.py — is the served Flatpak what prod released?

Issue #158: kde, cosmic, niri and xfce were served from the orphaned
pre-migration index entries tuna-os/tuna-installer-*, and nothing failed.
The fixtures below use the index's real shape (Results[].Name,
Images[].Tags/Architecture/Digest/Labels).
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "shared", "ci"))
import published_freshness as pf  # noqa: E402

REL = "1" * 40  # head of the last successful release.yml run on prod
OLD = "2" * 40  # an older prod commit
HEAD = "3" * 40  # prod HEAD
FOREIGN = "9" * 40  # a commit from a deleted pre-migration repo
BRANCH = "4" * 40  # a commit in this repository that never reached prod


def image(arch, tags, app_id, commit=REL, ts=1_790_000_000):
    flatpak_arch = {"amd64": "x86_64", "arm64": "aarch64"}[arch]
    labels = {
        "org.flatpak.ref": f"app/{app_id}/{flatpak_arch}/master",
        "org.flatpak.timestamp": str(ts),
    }
    if commit:
        labels["org.flatpak.subject"] = f"Built from {commit}"
    return {"Digest": "sha256:" + "0" * 64, "Architecture": arch, "Tags": tags, "Labels": labels}


def entry(name, *images):
    return {"Name": name, "Images": list(images)}


def current(frontend, commit=REL, archs=("amd64", "arm64"), app_id=None, ts=1_790_000_000):
    app = app_id or pf.APP_IDS[frontend]
    return [image(a, [frontend], app, commit, ts) for a in archs]


def index(*results):
    return {"Registry": "https://ghcr.io", "Results": list(results)}


class FakeHistory:
    """Commits OLD -> REL -> HEAD on prod; FOREIGN is unknown here."""

    def __init__(self, changes=None, last_change=None):
        # (a, b) -> changed paths
        self.changes = changes or {}
        self.last_change = last_change

    def is_ancestor(self, a, b):
        order = [OLD, REL, HEAD]
        if BRANCH in (a, b):
            return a == b
        if a not in order or b not in order:
            return None
        return order.index(a) <= order.index(b)

    def changed(self, a, b):
        return self.changes.get((a, b), [])

    def last_change_time(self, frontend, sha):
        return self.last_change


def released(sha=REL, head=REL, run=None):
    return {
        "sha": sha,
        "prod_head": head,
        "latest_run": run or {"head_sha": sha, "status": "completed", "conclusion": "success"},
    }


def check(frontend, idx, rel=None, history=None):
    return pf.evaluate(frontend, pf.parse_index(idx), rel or released(), history or FakeHistory())


# ── parsing the real index shape ──────────────────────────────────────────


def test_parse_reads_commit_ref_and_time_from_labels():
    imgs = pf.parse_index(index(entry(pf.PACKAGE, *current("kde"))))
    assert len(imgs) == 2
    assert imgs[0].commit == REL and imgs[0].app_id == "org.tunaos.InstallerKde"
    assert imgs[0].timestamp == 1_790_000_000 and imgs[0].tags == ["kde"]


def test_parse_tolerates_a_subject_without_a_sha():
    img = image("amd64", ["kde"], "org.tunaos.InstallerKde", commit=None)
    img["Labels"]["org.flatpak.subject"] = "Export org.tunaos.InstallerKde"
    assert pf.parse_index(index(entry(pf.PACKAGE, img)))[0].commit is None


# ── the release.yml path rule ─────────────────────────────────────────────


def test_touches_mirrors_release_yml():
    paths = ["frontends/kde/main.qml", "docs/x.md", "README.md", "AGENTS.md",
             "bootc_installer/main.py", "fisherman", "shared/recipe/x.json"]
    assert pf.touches("kde", paths) == ["frontends/kde/main.qml"]
    assert pf.touches("gnome", paths) == ["bootc_installer/main.py", "fisherman", "shared/recipe/x.json"]
    assert pf.touches("niri", paths) == []


# ── verdicts ──────────────────────────────────────────────────────────────


def test_issue_158_state_is_stale():
    idx = index(
        entry(pf.PACKAGE, *[image(a, ["gnome", "latest"], pf.APP_IDS["gnome"]) for a in ("amd64", "arm64")]),
        entry("tuna-os/tuna-installer-kde",
              image("amd64", ["latest"], "org.tunaos.InstallerKde", FOREIGN),
              image("arm64", ["latest"], "org.tunaos.InstallerKde", FOREIGN)),
    )
    assert not check("gnome", idx).stale
    kde = check("kde", idx)
    assert kde.stale
    assert any("tuna-os/tuna-installer-kde" in r and "orphaned" in r for r in kde.reasons)
    assert any("no `tuna-os/bootc-installer` entry tagged `kde`" in r for r in kde.reasons)


def test_legacy_entry_fails_even_next_to_a_current_one():
    idx = index(
        entry(pf.PACKAGE, *current("xfce")),
        entry("tuna-os/tuna-installer-xfce", image("amd64", ["latest"], "org.tunaos.InstallerXfce", FOREIGN)),
    )
    v = check("xfce", idx)
    assert v.stale and len(v.reasons) == 1 and "tuna-installer-xfce" in v.reasons[0]


def test_exact_release_commit_is_fresh():
    v = check("cosmic", index(entry(pf.PACKAGE, *current("cosmic"))))
    assert not v.stale and v.reasons == []


def test_older_build_with_no_frontend_change_since_is_fresh():
    # release.yml skips an unchanged frontend, so an older build is correct.
    hist = FakeHistory({(OLD, REL): ["frontends/kde/x.qml", "docs/a.md"]})
    assert not check("niri", index(entry(pf.PACKAGE, *current("niri", OLD))), history=hist).stale


def test_older_build_with_unpublished_changes_is_stale():
    hist = FakeHistory({(OLD, REL): ["frontends/niri/src/main.rs"]})
    v = check("niri", index(entry(pf.PACKAGE, *current("niri", OLD))), history=hist)
    assert v.stale and "frontends/niri/src/main.rs" in v.reasons[0]


def test_build_from_outside_prod_is_stale():
    v = check("kde", index(entry(pf.PACKAGE, *current("kde", FOREIGN))))
    assert v.stale and "not in this repository" in v.reasons[0]
    v = check("kde", index(entry(pf.PACKAGE, *current("kde", BRANCH))), released(head=HEAD))
    assert v.stale and "not on prod" in v.reasons[0]


def test_build_newer_than_the_last_release_is_fresh():
    # The release for HEAD is still publishing (or someone republished by
    # hand on prod): the build already covers HEAD's changes.
    idx = index(entry(pf.PACKAGE, *current("niri", HEAD)))
    hist = FakeHistory({(REL, HEAD): ["frontends/niri/a.rs"]})
    failed = released(head=HEAD, run={"head_sha": HEAD, "status": "completed", "conclusion": "failure"})
    v = check("niri", idx, failed, hist)
    assert not v.stale and v.reasons == [] and v.notes == []


def test_missing_arch_and_wrong_app_are_stale():
    v = check("kde", index(entry(pf.PACKAGE, *current("kde", archs=("amd64",)))))
    assert v.stale and "no arm64 image" in v.reasons[0]
    v = check("kde", index(entry(pf.PACKAGE, *current("kde", app_id="org.example.Other"))))
    assert v.stale and "expected app id" in v.reasons[0]


def test_no_successful_release_is_stale():
    v = check("gnome", index(entry(pf.PACKAGE, *current("gnome"))), rel=released(sha=None))
    assert v.stale and "no successful release.yml" in v.reasons[0]


def test_timestamp_fallback_without_a_commit():
    idx = index(entry(pf.PACKAGE, *current("kde", commit=None, ts=100)))
    assert check("kde", idx, history=FakeHistory(last_change=50)).stale is False
    v = check("kde", idx, history=FakeHistory(last_change=200))
    assert v.stale and "time comparison" in v.reasons[0]


def test_unreleased_prod_changes():
    idx = index(entry(pf.PACKAGE, *current("kde")))
    hist = FakeHistory({(REL, HEAD): ["frontends/kde/a.qml"]})
    # Release for HEAD still running: noted, not failed.
    running = released(head=HEAD, run={"head_sha": HEAD, "status": "in_progress", "conclusion": None})
    v = check("kde", idx, running, hist)
    assert not v.stale and "in_progress" in v.notes[0]
    # Release for HEAD failed: stale.
    failed = released(head=HEAD, run={"head_sha": HEAD, "status": "completed", "conclusion": "failure"})
    v = check("kde", idx, failed, hist)
    assert v.stale and "`failure`" in v.reasons[0]
    # Nothing ever ran for HEAD: stale.
    never = released(head=HEAD, run={"head_sha": REL, "status": "completed", "conclusion": "success"})
    assert check("kde", idx, never, hist).stale
    # HEAD changed only other frontends: fresh.
    assert not check("kde", idx, failed, FakeHistory({(REL, HEAD): ["frontends/niri/a"]})).stale


def test_render_names_each_stale_frontend():
    idx = index(entry(pf.PACKAGE, *current("gnome")),
                entry("tuna-os/tuna-installer-kde", image("amd64", ["latest"], "org.tunaos.InstallerKde", FOREIGN)))
    verdicts = [check(fe, idx) for fe in pf.FRONTENDS]
    md = pf.render(verdicts, released(), pf.INDEX_URL)
    assert "| gnome | fresh |" in md and "| kde | **stale** |" in md
    assert "**4 of 5 frontends stale**: kde, cosmic, niri, xfce" in md
