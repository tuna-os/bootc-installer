"""promote.yml names other workflows and their jobs. The names must be real.

`.github/workflows/promote.yml` is the gate between `dev` and `prod`
(docs/RELEASE.md). It holds two lists of names that nothing else checks:

- `on.workflow_run.workflows`: the workflows whose completion on `dev`
  fires the gate. GitHub ignores a name that matches no workflow. A renamed
  workflow thus leaves the list without an error.
- `REQUIRED_CHECKS`: the check-run names that must be present and green on
  the candidate. A name that no job produces blocks every promotion. A job
  that was renamed leaves its old name in the list for the same result.

The gate reads every check run on the candidate, so a red or pending run
of a workflow that is not in the first list still holds the promotion. But
only the last workflow to finish sees "everything complete". If that
workflow is not in the list, no firing promotes, and the commit waits for
the hourly catch-up, which GitHub delivers hours late. So every workflow
that a push to `dev` can start must be in the trigger list.

A workflow with a path filter does not run on every commit, so its jobs
cannot be required by name. A workflow with no path filter runs on every
push to `dev`. If it never starts (a disabled workflow, a syntax error), the
"nothing failed, nothing pending" rule sees nothing. Each such workflow
must thus have a job in `REQUIRED_CHECKS`.

The limits of this test: it reads the workflow files only. It does not know
whether a job's `if:` skips it, and it does not see the check runs of
scheduled workflows.
"""

import fnmatch
import itertools
import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
PROMOTE = WORKFLOWS / "promote.yml"
DEV = "dev"

# Workflows that a push to `dev` starts, but whose completion must not fire
# the gate. Map the workflow `name:` to the reason. The gate reads the check
# runs of every workflow, so there is no reason at this time and the set is
# empty. An entry here needs a reason that survives review.
NOT_A_TRIGGER = {}

# Workflows that run on every push to `dev` (no path filter), but have no
# job in REQUIRED_CHECKS. Map the workflow `name:` to the reason.
NOT_REQUIRED = {}


def load(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 reads the key `on` as the boolean true.
    doc["on"] = doc.pop(True, doc.get("on"))
    if isinstance(doc["on"], str):
        doc["on"] = {doc["on"]: None}
    elif isinstance(doc["on"], list):
        doc["on"] = {event: None for event in doc["on"]}
    return doc


def workflows():
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    return {path.name: load(path) for path in files}


def push_to_dev(doc):
    """The `push` trigger config when a push to `dev` starts the workflow.

    Returns None when it does not. An empty dict means "every push".
    """
    if "push" not in doc["on"]:
        return None
    cfg = doc["on"]["push"] or {}
    if "branches" in cfg:
        if not any(fnmatch.fnmatchcase(DEV, pat) for pat in cfg["branches"]):
            return None
    elif "branches-ignore" in cfg:
        if any(fnmatch.fnmatchcase(DEV, pat) for pat in cfg["branches-ignore"]):
            return None
    elif "tags" in cfg or "tags-ignore" in cfg:
        # Only tag filters: a push of a branch does not start the workflow.
        return None
    return cfg


def path_filtered(cfg):
    return "paths" in cfg or "paths-ignore" in cfg


def check_names(doc):
    """Patterns for the check-run names that the jobs of one workflow make.

    A job that calls a reusable workflow makes "<job> / <inner job>" names,
    which this test does not expand; those jobs are left out. A `${{ }}`
    expression that the matrix does not resolve becomes a wildcard.
    """
    patterns = []
    for job_id, job in doc["jobs"].items():
        if "uses" in job:
            continue
        template = str(job.get("name", job_id))
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        axes = {k: v for k, v in matrix.items()
                if isinstance(v, list) and k not in ("include", "exclude")} \
            if isinstance(matrix, dict) else {}
        combos = [dict(zip(axes, values))
                  for values in itertools.product(*axes.values())] or [{}]
        for combo in combos:
            parts = re.split(r"(\$\{\{.*?\}\})", template)
            regex = ""
            for part in parts:
                expr = re.fullmatch(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}", part)
                if expr and expr.group(1) in combo:
                    regex += re.escape(str(combo[expr.group(1)]))
                elif part.startswith("${{"):
                    regex += ".+"
                else:
                    regex += re.escape(part)
            patterns.append(regex)
    return patterns


def produces(doc, check):
    return any(re.fullmatch(pattern, check) for pattern in check_names(doc))


def triggers():
    return load(PROMOTE)["on"]["workflow_run"]["workflows"]


def required_checks():
    block = load(PROMOTE)["env"]["REQUIRED_CHECKS"]
    return [line.strip() for line in block.splitlines() if line.strip()]


def names():
    return {doc["name"]: doc for doc in workflows().values()}


def test_every_workflow_has_a_unique_name():
    """workflow_run matches on `name:`, so two workflows must not share one."""
    seen = [doc.get("name") for doc in workflows().values()]
    assert None not in seen, "a workflow has no `name:`"
    assert len(seen) == len(set(seen)), sorted(n for n in seen if seen.count(n) > 1)


def test_helpers_read_the_shapes_the_workflows_use():
    assert push_to_dev({"on": {"push": None}}) == {}
    assert push_to_dev({"on": {"push": {"branches": ["main"]}}}) is None
    assert push_to_dev({"on": {"push": {"tags": ["v*"]}}}) is None
    assert push_to_dev({"on": {"pull_request": None}}) is None
    assert push_to_dev({"on": {"push": {"branches": ["d*"], "paths": ["x"]}}})
    doc = {"jobs": {
        "plain": {},
        "named": {"name": "E2E (${{ matrix.f }})",
                  "strategy": {"matrix": {"f": ["a", "b"]}}},
        "dynamic": {"name": "OCI (${{ matrix.arch }})",
                    "strategy": {"matrix": {"arch": "${{ fromJSON(inputs.a) }}"}}},
        "called": {"uses": "./x.yml"},
    }}
    assert produces(doc, "plain")
    assert produces(doc, "E2E (a)") and produces(doc, "E2E (b)")
    assert not produces(doc, "E2E (c)")
    assert produces(doc, "OCI (x86_64)")
    assert not produces(doc, "called")


def test_every_trigger_names_a_workflow():
    listed = triggers()
    assert len(listed) == len(set(listed)), "a workflow is in the list twice"
    unknown = [name for name in listed if name not in names()]
    assert not unknown, (
        f"promote.yml waits for {unknown}, but no file in .github/workflows "
        "has that `name:`. GitHub ignores the entry, so the gate does not "
        "fire when that workflow completes.")


def test_every_trigger_can_run_on_dev():
    """A listed workflow that never runs on `dev` never fires the gate."""
    for name in triggers():
        doc = names()[name]
        assert push_to_dev(doc) is not None or "workflow_run" in doc["on"], (
            f"'{name}' is in promote.yml's workflow_run list, but a push to "
            "dev does not start it")


def test_every_workflow_on_dev_fires_the_gate():
    listed = set(triggers())
    on_dev = {doc["name"] for doc in workflows().values()
              if push_to_dev(doc) is not None}
    missing = sorted(on_dev - listed - set(NOT_A_TRIGGER))
    assert not missing, (
        f"a push to dev starts {missing}, but promote.yml does not wait for "
        "them. Add each one to on.workflow_run.workflows, or to "
        "NOT_A_TRIGGER in this test with the reason.")
    stale = sorted(n for n in NOT_A_TRIGGER if n in listed or n not in on_dev)
    assert not stale, f"NOT_A_TRIGGER has entries that no longer apply: {stale}"


def test_every_required_check_is_a_job_that_runs_on_dev():
    required = required_checks()
    assert len(required) == len(set(required)), "a required check is listed twice"
    on_dev = {doc["name"]: doc for doc in workflows().values()
              if push_to_dev(doc) is not None}
    for check in required:
        makers = sorted(name for name, doc in on_dev.items() if produces(doc, check))
        assert makers, (
            f"REQUIRED_CHECKS has '{check}', but no job of a workflow that "
            "runs on a push to dev has that name. The gate would refuse "
            "every promotion.")
        # The gate matches by name only. Two workflows with one job name
        # would let a green run of one hide a missing run of the other.
        assert len(makers) == 1, (
            f"'{check}' is a job name in more than one workflow: {makers}")
        assert not path_filtered(push_to_dev(on_dev[makers[0]])), (
            f"'{check}' comes from '{makers[0]}', which has a path filter. "
            "It is absent on most commits, so the gate cannot require it.")


def test_every_unfiltered_workflow_has_a_required_check():
    required = required_checks()
    missing = []
    for doc in workflows().values():
        cfg = push_to_dev(doc)
        if cfg is None or path_filtered(cfg):
            continue
        if not any(produces(doc, check) for check in required):
            missing.append(doc["name"])
    unexplained = sorted(set(missing) - set(NOT_REQUIRED))
    assert not unexplained, (
        f"{unexplained} run on every push to dev, but no job of theirs is in "
        "REQUIRED_CHECKS. If one of them does not start, the gate does not "
        "see it. Add a job name, or add the workflow to NOT_REQUIRED in "
        "this test with the reason.")
    stale = sorted(set(NOT_REQUIRED) - set(missing))
    assert not stale, f"NOT_REQUIRED has entries that no longer apply: {stale}"


def test_release_doc_names_this_test():
    text = (REPO / "docs" / "RELEASE.md").read_text(encoding="utf-8")
    assert "tests/unit/test_promote_gate.py" in text
