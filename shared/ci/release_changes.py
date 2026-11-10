#!/usr/bin/env python3
"""Which frontends must this release run publish?

release.yml used to diff against the latest GitHub release. That release is
created BEFORE the publish jobs run, so when a publish failed, the next run
compared against a release that already contained the unpublished change,
found no diff, and skipped the frontend until its files happened to change
again (#319; the symptom is #279).

The baseline here is per frontend: the commit of the newest earlier
release.yml run in which THAT frontend's publish really succeeded, meaning
every job under "Publish (<frontend>) / ..." ended in success. A run that
skipped the frontend, or whose publish failed or was cancelled, is not a
baseline, so whatever it missed is still in the diff of the next run. A
frontend with no such run within the lookback, or whose baseline is not an
ancestor of the commit being released, is published.

The path rule is published_freshness.touches, the one definition both
scripts share: gnome is everything outside frontends/, docs/ and top-level
*.md; the others are frontends/<name>/ and the files in shared/ that their
manifest copies.

    python3 shared/ci/release_changes.py --repo OWNER/REPO --run-id "$GITHUB_RUN_ID" \
        --github-output "$GITHUB_OUTPUT"

It prints one `<frontend>=true|false` line per frontend. If the run history
cannot be read it publishes everything: a redundant publish costs minutes,
a skipped one ships nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import published_freshness as pf  # noqa: E402

FRONTENDS = pf.FRONTENDS
LOOKBACK = 30
WORKFLOW = "release.yml"


# ---------------------------------------------------------------- pure logic


def publish_jobs(frontend, jobs):
    """The jobs of a run that belong to one frontend's publish.

    release.yml calls a reusable workflow from the job "Publish (<name>)", so
    the real jobs are named "Publish (<name>) / publish / Build OCI (x86_64)"
    and so on. A caller job that was skipped appears as the bare name with
    no " / " part, and is not a publish job.
    """
    prefix = f"Publish ({frontend}) / "
    return [job for job in jobs if str(job.get("name", "")).startswith(prefix)]


def published(frontend, jobs):
    """Whether a run really published this frontend."""
    mine = publish_jobs(frontend, jobs)
    return bool(mine) and all(
        job.get("status") == "completed" and job.get("conclusion") == "success" for job in mine
    )


def baselines(runs, jobs_of, is_ancestor, head, current_run_id=None, lookback=LOOKBACK):
    """{frontend: sha or None}: the last commit published for each frontend.

    runs: release.yml runs, newest first ({"id", "head_sha", "status"}).
    jobs_of(run_id) -> the run's jobs ({"name", "status", "conclusion"}).
    is_ancestor(a, b) -> True when commit a is b or an ancestor of b.
    """
    found = {frontend: None for frontend in FRONTENDS}
    looked = 0
    for run in runs:
        if all(found.values()) or looked >= lookback:
            break
        if current_run_id is not None and str(run.get("id")) == str(current_run_id):
            continue
        sha = run.get("head_sha")
        if run.get("status") != "completed" or not sha:
            continue
        if not is_ancestor(sha, head):
            # A run for a commit that is not in this history (a rewritten
            # prod, a tag on another line) says nothing about this one.
            continue
        looked += 1
        jobs = jobs_of(run["id"])
        for frontend in FRONTENDS:
            if found[frontend] is None and published(frontend, jobs):
                found[frontend] = sha
    return found


def decide(found, changed_since, head):
    """{frontend: (publish, reason)}.

    changed_since(sha) -> the paths that differ between sha and head.
    """
    verdicts = {}
    for frontend in FRONTENDS:
        base = found.get(frontend)
        if not base:
            verdicts[frontend] = (True, "no earlier run published it")
            continue
        if base == head:
            verdicts[frontend] = (False, f"already published from {base[:7]}")
            continue
        paths = pf.touches(frontend, changed_since(base))
        if paths:
            sample = ", ".join(paths[:3]) + (" ..." if len(paths) > 3 else "")
            reason = (f"{len(paths)} change(s) since {base[:7]}, "
                      f"the last commit published: {sample}")
            verdicts[frontend] = (True, reason)
        else:
            verdicts[frontend] = (False, f"no change since {base[:7]}, the last commit published")
    return verdicts


def publish_everything(reason):
    return {frontend: (True, reason) for frontend in FRONTENDS}


def render_outputs(verdicts):
    return "".join(f"{frontend}={'true' if verdicts[frontend][0] else 'false'}\n"
                   for frontend in FRONTENDS)


# ------------------------------------------------------------ I/O adapters


def _gh(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def gh_runs(repo):
    return _gh(f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?status=completed&per_page=100"
               ).get("workflow_runs", [])


def gh_jobs(repo, run_id):
    jobs, page = [], 1
    while True:
        batch = _gh(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100&page={page}"
                    ).get("jobs", [])
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "tuna-os/bootc-installer"))
    parser.add_argument("--git-dir", default=".")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"),
                        help="this run, which is never its own baseline")
    parser.add_argument("--github-output", help="append the outputs to this file")
    args = parser.parse_args(argv)

    try:
        history = pf.GitHistory(args.git_dir)
        head = history.rev_parse(args.head)
        found = baselines(gh_runs(args.repo), lambda run_id: gh_jobs(args.repo, run_id),
                          lambda a, b: a == b or history.is_ancestor(a, b) is True,
                          head, args.run_id)
        verdicts = decide(found, lambda sha: history.changed(sha, head), head)
    except Exception as error:  # noqa: BLE001 - any failure means "cannot tell": publish
        print(f"::warning::could not read the release history ({error}); publishing every frontend")
        verdicts = publish_everything("the release history could not be read")

    for frontend in FRONTENDS:
        publish, reason = verdicts[frontend]
        print(f"{frontend}: {'publish' if publish else 'skip'} ({reason})", file=sys.stderr)
    outputs = render_outputs(verdicts)
    sys.stdout.write(outputs)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as stream:
            stream.write(outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
