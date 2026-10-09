"""shared/ci/fisherman_bump.py — when fisherman-bump.yml may move the pin.

The workflow only ever bumps to a fisherman `dev` commit whose CI finished
green and that is strictly ahead of the current pin. These tests pin that
decision without touching the network.
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "shared", "ci"))
import fisherman_bump as fb  # noqa: E402

OLD = "a" * 40
NEW = "b" * 40


def run(name, conclusion="success", status="completed", id=1):
    return {"id": id, "name": name, "status": status, "conclusion": conclusion}


# ── ci_verdict ────────────────────────────────────────────────────────────


def test_all_success_is_green():
    ok, reason = fb.ci_verdict([{"context": "ci", "state": "success"}], [run("Go")])
    assert ok and "2 check(s) green" in reason


def test_skipped_check_runs_do_not_block():
    ok, _ = fb.ci_verdict([], [run("Go"), run("Publish", "skipped")])
    assert ok


def test_failed_check_run_blocks():
    ok, reason = fb.ci_verdict([], [run("Go"), run("E2E", "failure")])
    assert not ok and "E2E (failure)" in reason


def test_neutral_and_cancelled_are_not_green():
    for conclusion in ("neutral", "cancelled", "timed_out", "action_required"):
        ok, _ = fb.ci_verdict([], [run("Go"), run("X", conclusion)])
        assert not ok, conclusion


def test_running_check_run_waits():
    ok, reason = fb.ci_verdict([], [run("Go"), run("Gate", None, "queued")])
    assert not ok and "still running: Gate" in reason


def test_failed_or_pending_status_blocks():
    assert not fb.ci_verdict([{"context": "c", "state": "failure"}], [run("Go")])[0]
    assert not fb.ci_verdict([{"context": "c", "state": "error"}], [run("Go")])[0]
    assert not fb.ci_verdict([{"context": "c", "state": "pending"}], [run("Go")])[0]


def test_commit_without_any_ci_is_not_green():
    ok, reason = fb.ci_verdict([], [])
    assert not ok and "no CI" in reason
    # Only skipped runs prove nothing either.
    assert not fb.ci_verdict([], [run("Publish", "skipped")])[0]


def test_newest_run_of_a_name_wins():
    # A re-run that went green supersedes the earlier failure...
    ok, _ = fb.ci_verdict([], [run("Go", "failure", id=1), run("Go", "success", id=2)])
    assert ok
    # ...and a newer firing still queued holds the bump back.
    ok, reason = fb.ci_verdict([], [run("Gate", id=5), run("Gate", None, "queued", id=9)])
    assert not ok and "Gate" in reason


# ── decide ────────────────────────────────────────────────────────────────


def test_same_commit_is_current():
    assert fb.decide(OLD, OLD, "identical", True, "")[0] == "current"


def test_ahead_and_green_bumps():
    action, reason = fb.decide(OLD, NEW, "ahead", True, "3 check(s) green")
    assert action == "bump" and "aaaaaaa..bbbbbbb" in reason


def test_ahead_but_red_waits():
    assert fb.decide(OLD, NEW, "ahead", False, "CI not green: X")[0] == "wait"


def test_never_moves_backwards_or_sideways():
    for status in ("behind", "diverged"):
        assert fb.decide(OLD, NEW, status, True, "")[0] == "skip"


# ── title and body ────────────────────────────────────────────────────────


def test_title_matches_the_manual_convention():
    assert fb.title(OLD, NEW) == "chore: update fisherman submodule (aaaaaaa..bbbbbbb)"


def commit(sha, message, login="someone"):
    return {"sha": sha, "commit": {"message": message, "author": {"name": "x"}}, "author": {"login": login}}


def test_body_lists_every_commit_with_a_link():
    commits = [commit("c" * 40, "fix(disk): thing (#12)\n\nlong text"), commit(NEW, "feat: other")]
    md = fb.body(OLD, NEW, commits, "2 check(s) green", "bot")
    assert f"https://github.com/tuna-os/fisherman/commit/{'c' * 40}" in md
    assert f"https://github.com/tuna-os/fisherman/commit/{NEW}" in md
    assert "long text" not in md
    # fisherman PR numbers point at fisherman, not this repository.
    assert "(tuna-os/fisherman#12)" in md
    # No @mentions: the body is rewritten on every bump.
    assert "@" not in md.replace("tuna-os/fisherman@dev", "")
    assert "does not start on its own" not in md


def test_body_says_when_ci_will_not_run_by_itself():
    md = fb.body(OLD, NEW, [commit(NEW, "x")], "ok", "default")
    assert "does not start on its own" in md
    assert "FISHERMAN_BUMP_TOKEN" in md


def test_body_notes_truncated_commit_lists():
    md = fb.body(OLD, NEW, [commit(NEW, "x")], "ok", "bot", total=300)
    assert "### Commits (300)" in md and "299 more" in md
