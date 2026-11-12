"""The metadata file of each frontend, and the runner that reads it (#186).

Each frontend has one file with its canonical build and test commands
(shared/ci/frontend-gnome.json, frontends/<name>/frontend.json), and
shared/ci/frontend_tests.py runs them. These tests hold each command to
the workflow step that CI runs, so the file cannot drift from CI, and test
the runner's selection and outcomes without the real toolchains.
"""

import copy
import io
import json
import os
import shlex
import sys
from contextlib import redirect_stdout

import pytest
import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "ci"))

import frontend_table  # noqa: E402
import frontend_tests as ft  # noqa: E402

WORKFLOWS = os.path.join(REPO, ".github", "workflows")
NAMES = list(frontend_table.load())
METAS = {name: ft.load(name) for name in NAMES}
COMMANDS = [(name, section, cmd["id"]) for name in NAMES
            for section in ft.SECTIONS for cmd in METAS[name][section]]


def workflow(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def tokens(line):
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def logical_lines(script):
    """The commands of a `run:` script: continuations joined, no comments."""
    out = []
    for line in script.replace("\\\n", " ").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def steps(wf, job_id):
    """(cwd, env, run) of each run step of a job, as the runner sees them."""
    job = wf["jobs"][job_id]
    default = ((job.get("defaults") or {}).get("run") or {}).get("working-directory") \
        or ((wf.get("defaults") or {}).get("run") or {}).get("working-directory") or "."
    for step in job.get("steps") or []:
        if "run" in step:
            env = {**(wf.get("env") or {}), **(job.get("env") or {}), **(step.get("env") or {})}
            yield (os.path.normpath(step.get("working-directory") or default),
                   {k: str(v) for k, v in env.items()}, step["run"])


def section_cmd(name, section, cid):
    return next(c for c in METAS[name][section] if c["id"] == cid)


def test_every_frontend_has_a_metadata_file():
    assert NAMES == ["gnome", "kde", "cosmic", "niri", "xfce"]
    trees = sorted(d for d in os.listdir(os.path.join(REPO, "frontends"))
                   if os.path.isdir(os.path.join(REPO, "frontends", d)))
    assert trees == sorted(n for n in NAMES if n != "gnome")
    for name in NAMES:
        assert os.path.exists(os.path.join(REPO, ft.meta_path(name))), name
        assert METAS[name]["test"], f"{name} has no test command"
        assert METAS[name]["compliance"], f"{name} has no compliance command"


@pytest.mark.parametrize("name,section,cid", COMMANDS)
def test_each_command_is_a_command_that_ci_runs(name, section, cid):
    """The named job has a step in the same directory, with the same
    variables, and a line of that step starts with the command."""
    cmd = section_cmd(name, section, cid)
    wf = workflow(cmd["workflow"])
    assert cmd["job"] in wf["jobs"], f"{cmd['workflow']} has no job {cmd['job']}"
    want = tokens(cmd["run"])
    found = []
    for cwd, env, script in steps(wf, cmd["job"]):
        if cwd != os.path.normpath(cmd["cwd"]):
            continue
        if any(tokens(line)[:len(want)] == want for line in logical_lines(script)):
            found.append(env)
    assert found, (f"{ft.meta_path(name)} {section} {cid}: no step of {cmd['workflow']} "
                   f"job {cmd['job']} in {cmd['cwd']} runs {cmd['run']!r}")
    assert any(cmd.get("env", {}).items() <= env.items() for env in found), \
        f"{name} {section} {cid}: the step does not set {cmd.get('env')}"


@pytest.mark.parametrize("name", NAMES)
def test_compliance_is_the_job_of_recipe_compliance(name):
    """The last compliance command is the last step of the frontend's job in
    recipe-compliance.yml: the step that runs the fixture."""
    last = METAS[name]["compliance"][-1]
    assert (last["workflow"], last["job"]) == ("recipe-compliance.yml", name)
    *_, (_cwd, _env, script) = steps(workflow("recipe-compliance.yml"), name)
    assert any(tokens(line)[:len(tokens(last["run"]))] == tokens(last["run"])
               for line in logical_lines(script))


@pytest.mark.parametrize("name", NAMES)
def test_cwd_is_in_the_frontend_tree(name):
    root = "." if name == "gnome" else f"frontends/{name}"
    for section in ft.SECTIONS:
        for cmd in METAS[name][section]:
            path = os.path.normpath(cmd["cwd"])
            assert os.path.isdir(os.path.join(REPO, path)), cmd
            if name != "gnome":
                assert path == root or path.startswith(root + "/"), cmd
            else:
                assert not path.startswith("frontends"), cmd


def test_no_product_names():
    for name in NAMES:
        with open(os.path.join(REPO, ft.meta_path(name)), encoding="utf-8") as fh:
            text = fh.read().lower()
        assert "bluefin" not in text and "tunaos" not in text, name


# ── The schema ───────────────────────────────────────────────────────────

def broken(change):
    meta = copy.deepcopy(METAS["kde"])
    change(meta)
    with pytest.raises(ft.MetaError):
        ft.validate(meta, "kde", "kde.json")


def test_validate_refuses_a_bad_file():
    broken(lambda m: m.update(frontend="cosmic"))
    broken(lambda m: m.update(extra=1))
    broken(lambda m: m.pop("test"))
    broken(lambda m: m["test"][0].pop("workflow"))
    broken(lambda m: m["test"][0].update(surprise=True))
    broken(lambda m: m["test"][0].update(requires="cmake"))
    broken(lambda m: m["test"][0].update(run=" "))
    broken(lambda m: m["test"][0].update(cwd="../elsewhere"))
    broken(lambda m: m["test"][0].update(needs=["nope"]))
    broken(lambda m: m["test"][0].update(env={"A": 1}))
    broken(lambda m: m["build"][0].update(needs=[]))
    broken(lambda m: m["build"].append(dict(m["build"][0])))


def test_validate_accepts_each_file():
    for name in NAMES:
        assert ft.validate(copy.deepcopy(METAS[name]), name, name) == METAS[name]


# ── Selection ────────────────────────────────────────────────────────────

def plan_ids(plan):
    return [(f, [(kind, c["id"]) for kind, c in s]) for f, s in plan]


def test_select_everything_in_table_order():
    plan = ft.select(METAS, [])
    assert [f for f, _ in plan] == NAMES
    for frontend, chosen in plan:
        assert [c["id"] for k, c in chosen if k == "test"] == \
            [c["id"] for c in METAS[frontend]["test"]]


def test_select_one_test_brings_its_builds_first():
    assert plan_ids(ft.select(METAS, ["gnome:ui"])) == [
        ("gnome", [("build", "configure"), ("build", "compile"), ("test", "ui")])]
    assert plan_ids(ft.select(METAS, ["gnome:unit"])) == [("gnome", [("test", "unit")])]


def test_select_frontend_and_test_merge():
    plan = plan_ids(ft.select(METAS, ["niri:vet", "kde", "niri:progress"]))
    assert [f for f, _ in plan] == ["kde", "niri"]  # table order, not argument order
    assert plan[1] == ("niri", [("test", "vet"), ("test", "progress")])
    assert plan_ids(ft.select(METAS, ["niri:vet", "niri"]))[0][1] == \
        plan_ids(ft.select(METAS, ["niri"]))[0][1]


def test_select_compliance():
    plan = plan_ids(ft.select(METAS, ["kde"], compliance=True))
    assert plan == [("kde", [("compliance", "configure"), ("compliance", "compile"),
                             ("compliance", "recipe")])]
    assert all(k == "compliance" for _f, s in ft.select(METAS, [], compliance=True)
               for k, _c in s)


@pytest.mark.parametrize("names", [["bogus"], ["kde:bogus"], ["gnome:"  "nope"]])
def test_select_refuses_an_unknown_name(names):
    with pytest.raises(ft.MetaError):
        ft.select(METAS, names)


# ── Toolchains ───────────────────────────────────────────────────────────

def test_missing_reads_each_kind_of_entry():
    which = {"cmake", "go"}.__contains__
    gone = ft.missing(
        ["cmake", "ctest", "go|golang", "gcc|clang", "pkg-config:Qt6Quick",
         "pkg-config:xkbcommon", "python:gi", "python:yaml"],
        which=lambda n: n if which(n) else None,
        pkg_config={"xkbcommon"}.__contains__,
        find_spec={"yaml"}.__contains__)
    assert gone == ["ctest", "gcc|clang", "pkg-config:Qt6Quick", "python:gi"]


# ── Running ──────────────────────────────────────────────────────────────

def fake_meta():
    meta = {"frontend": "x", "build": [
        {"id": "b", "run": "make", "cwd": ".", "workflow": "w.yml", "job": "j",
         "requires": ["make"]}],
        "test": [
            {"id": "t1", "run": "check one", "cwd": ".", "workflow": "w.yml", "job": "j",
             "requires": []},
            {"id": "t2", "run": "check two", "cwd": ".", "workflow": "w.yml", "job": "j",
             "requires": [], "needs": ["b"], "env": {"V": "1"}}],
        "compliance": []}
    return {"x": ft.validate(meta, "x", "x.json")}


def run(plan, results=None, gone=(), **kw):
    ran = []

    def execute(cmd, cwd, env):
        ran.append((cmd["id"], env.get("V")))
        return (results or {}).get(cmd["id"], 0)
    lines = []
    res, rc = ft.run_plan(plan, check=lambda req: [r for r in req if r in gone],
                          execute=execute, out=lines.append, **kw)
    return {k[1]: v for k, v in res.items()}, rc, ran, "\n".join(lines)


def test_run_passes_and_prints_each_command():
    res, rc, ran, text = run(ft.select(fake_meta(), []))
    assert rc == 0 and set(res.values()) == {ft.PASSED}
    assert ran == [("b", None), ("t1", None), ("t2", "1")]
    assert "RUN: x:t2 (test, in ., as in w.yml job j): V=1 check two" in text


def test_a_failure_exits_non_zero_and_others_still_run():
    res, rc, ran, text = run(ft.select(fake_meta(), ["x:t1", "x:t2"]), results={"t1": 3})
    assert rc == 1 and res["t1"] == ft.FAILED and res["t2"] == ft.PASSED
    assert "FAILED (exit 3): x:t1" in text


def test_a_failed_build_stops_its_tests():
    res, rc, ran, text = run(ft.select(fake_meta(), []), results={"b": 1})
    assert rc == 1
    assert res == {"b": ft.FAILED, "t1": ft.PASSED, "t2": ft.SKIPPED}
    assert "t2" not in [r[0] for r in ran]
    assert "build 'b' failed" in text


def test_a_missing_toolchain_is_a_skip_with_the_reason():
    res, rc, ran, text = run(ft.select(fake_meta(), []), gone={"make"})
    assert rc == 0
    assert res == {"b": ft.SKIPPED, "t1": ft.PASSED, "t2": ft.SKIPPED}
    assert "missing make" in text
    assert "build 'b' did not run: missing make" in text


def test_require_all_turns_a_skip_into_a_failure():
    res, rc, _ran, _text = run(ft.select(fake_meta(), []), gone={"make"}, require_all=True)
    assert rc == 1 and res["b"] == ft.FAILED


def test_unless_exists_does_not_rebuild(tmp_path):
    metas = fake_meta()
    metas["x"]["build"][0]["unless_exists"] = "done.stamp"
    (tmp_path / "done.stamp").write_text("")
    res, rc, ran, text = run(ft.select(metas, ["x:t2"]), repo=str(tmp_path))
    assert rc == 0 and [r[0] for r in ran] == ["t2"]
    assert "done.stamp exists" in text


def test_a_failed_compliance_step_stops_the_next():
    metas = fake_meta()
    metas["x"]["compliance"] = copy.deepcopy(metas["x"]["build"]) + [
        dict(metas["x"]["test"][0], id="c")]
    res, rc, ran, _text = run(ft.select(metas, [], compliance=True), results={"b": 2})
    assert rc == 1 and res == {"b": ft.FAILED, "c": ft.SKIPPED}


def test_main_list_and_bad_names():
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert ft.main(["--list", "kde"]) == 0
    assert "ctest --test-dir build --output-on-failure" in buf.getvalue()
    assert ft.main(["nope"]) == 2


def test_the_docstring_names_each_key():
    for key in {**ft.COMMAND_KEYS, **ft.OPTIONAL_KEYS}:
        assert f"    {key} " in ft.__doc__, key
    assert json.dumps(sorted(ft.SECTIONS)) == '["build", "compliance", "test"]'
