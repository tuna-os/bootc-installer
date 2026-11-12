"""shared/README.md and shared/CHANGELOG.md stay true to shared/.

All five frontends read the contracts in shared/ (#226). A change there
changes every frontend at once, so two documents must not go stale:

- shared/README.md has one section for each directory in shared/. A new
  contract directory with no section fails here, and so does a section for
  a directory that is gone.
- shared/CHANGELOG.md has an entry for each change to the recipe schema.
  An entry that changes the schema carries the sha256 of the file. The
  newest hash in the changelog must be the hash of the file. A schema edit
  with no changelog edit thus fails.

The limit of the second check: it has no history. A person can replace the
hash in the newest entry and write nothing else, and the test passes. The
check stops a silent change; a reviewer must judge the text. The test does
refuse a hash that appears twice, which is what a copied entry looks like.

- shared/VERSION is the version of the contracts. A change to a contract
  file needs a new CHANGELOG.md entry with the new version and the digest
  of the contract files. Against the base, the version must increase and
  the entry must be new, so an edit of an old entry fails too
  (shared/ci/contract_version.py). That check needs history: the tests
  here run it on throwaway repositories, and the "Shared contract version"
  job of python-test.yml runs it on the real one.
"""

import hashlib
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SHARED = REPO / "shared"
README = SHARED / "README.md"
CHANGELOG = SHARED / "CHANGELOG.md"
SCHEMA = SHARED / "recipe" / "fisherman-recipe.schema.json"

HASH_LINE = re.compile(r"^Recipe schema sha256: `([0-9a-f]{64})`$", re.M)
ENTRY = re.compile(r"^## (\d{4}-\d{2}-\d{2}): \S.*$", re.M)


def directories():
    return sorted(p.name for p in SHARED.iterdir()
                  if p.is_dir() and not p.name.startswith((".", "__")))


def sections():
    text = README.read_text(encoding="utf-8")
    return re.findall(r"^## `([\w-]+)/`$", text, re.M)


def test_readme_has_a_section_for_each_directory():
    missing = sorted(set(directories()) - set(sections()))
    assert not missing, (
        f"shared/README.md has no section for {missing}. Add a heading "
        "'## `<name>/`' that says what the contract is, which test makes it "
        "true, and how a new frontend adopts it.")
    gone = sorted(set(sections()) - set(directories()))
    assert not gone, f"shared/README.md has a section for {gone}, which is not in shared/"


def test_readme_names_tests_and_links_that_exist():
    text = README.read_text(encoding="utf-8")
    for test in set(re.findall(r"tests/unit/test_\w+\.py", text)):
        assert (REPO / test).is_file(), f"shared/README.md names {test}, which does not exist"
    for link in re.findall(r"\]\(([^)#]+)\)", text):
        if "://" not in link:
            assert (SHARED / link).exists(), f"shared/README.md links to {link}, which does not exist"
    assert "## How a contract changes" in text, "the deprecation rule is gone"


def test_changelog_entries_are_dated_newest_first():
    dates = ENTRY.findall(CHANGELOG.read_text(encoding="utf-8"))
    assert dates, "shared/CHANGELOG.md has no entry of the form '## YYYY-MM-DD: title'"
    assert dates == sorted(dates, reverse=True), (
        "shared/CHANGELOG.md entries are not newest first; add a new entry "
        "at the top")


def test_recipe_schema_change_has_a_changelog_entry():
    actual = hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
    hashes = HASH_LINE.findall(CHANGELOG.read_text(encoding="utf-8"))
    assert hashes, "shared/CHANGELOG.md has no 'Recipe schema sha256:' line"
    assert len(hashes) == len(set(hashes)), (
        "a recipe schema hash appears twice in shared/CHANGELOG.md")
    assert hashes[0] == actual, (
        "shared/recipe/fisherman-recipe.schema.json changed (sha256 "
        f"{actual}), but the newest hash in shared/CHANGELOG.md is "
        f"{hashes[0]}. Add an entry at the top of shared/CHANGELOG.md that "
        "says what changed for the frontends, with the line\n"
        f"Recipe schema sha256: `{actual}`")


def test_recipe_schema_hash_is_in_the_newest_entry_that_has_one():
    """Each hash line belongs to its own entry: one hash for each entry."""
    text = CHANGELOG.read_text(encoding="utf-8")
    for body in re.split(ENTRY, text)[2::2]:
        assert len(HASH_LINE.findall(body)) <= 1, (
            "one shared/CHANGELOG.md entry has two schema hashes; write one "
            "entry for each change")


# The version of the contracts (#226). shared/ci/contract_version.py holds
# the rule: which files are contract files, the digest, and the checks.

import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(SHARED / "ci"))
import contract_version as cv  # noqa: E402


def test_version_file_is_semver():
    assert cv.read_version() >= (1, 0, 0)


def test_readme_states_the_version_rule():
    text = README.read_text(encoding="utf-8")
    assert "no version number" not in text
    assert "`VERSION`" in text and "MAJOR" in text and "PATCH" in text


@pytest.mark.parametrize("path,expected", [
    ("shared/recipe/fisherman-recipe.schema.json", True),
    ("shared/branding/copy-defaults.json", True),
    ("shared/walkthrough/parity_report.py", True),
    ("shared/python/bootc_shared/catalog.py", True),
    ("shared/README.md", False),
    ("shared/recipe/README.md", False),
    ("shared/CHANGELOG.md", False),
    ("shared/VERSION", False),
    ("shared/ci/fisherman_pins.py", False),
    ("shared/e2e/check-recipe.py", False),
    ("shared/browser/run.sh", False),
    ("shared/python/bootc_shared/__pycache__/x.pyc", False),
    ("tests/unit/test_x.py", False),
])
def test_contract_file_classification(path, expected):
    assert cv.is_contract_file(path) is expected


def test_contract_change_has_a_versioned_changelog_entry():
    problems = cv.check_changelog(REPO)
    assert not problems, "\n".join(problems)


def test_ci_runs_the_history_check():
    """The check against the base needs history, so it is not a unit test
    (the suite runs in shallow, fork and packaged checkouts). One job runs
    it: python-test.yml "Shared contract version", with the full history."""
    wf = (REPO / ".github" / "workflows" / "python-test.yml").read_text(encoding="utf-8")
    job = wf[wf.index("  contracts:"):]
    job = job[:job.index("\n  # ──") if "\n  # ──" in job else len(job)]
    assert "name: Shared contract version" in job
    assert "fetch-depth: 0" in job
    assert "shared/ci/contract_version.py --check --base" in job
    assert "if:" not in job.split("steps:")[0], "the job must run on every event"


# The same checks against a throwaway repository: each way to get it wrong.

ENTRY_TEMPLATE = """## {date}: {title}

- Changed: {title}.

Contracts version: `{version}`
Contracts sha256: `{digest}`
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _write_entry(repo, date, title, version, body=""):
    (repo / "shared" / "VERSION").write_text(version + "\n")
    _git(repo, "add", "-A")
    entry = ENTRY_TEMPLATE.format(date=date, title=title, version=version,
                                  digest=cv.digest(repo))
    log = repo / "shared" / "CHANGELOG.md"
    old = log.read_text() if log.exists() else "# shared/ changelog\n\n"
    head, _, rest = old.partition("\n\n")
    log.write_text(head + "\n\n" + entry + "\n" + rest)


@pytest.fixture
def repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    r = tmp_path / "repo"
    (r / "shared" / "recipe").mkdir(parents=True)
    (r / "shared" / "ci").mkdir()
    (r / "shared" / "recipe" / "schema.json").write_text('{"a": 1}\n')
    (r / "shared" / "ci" / "tool.py").write_text("x = 1\n")
    _git(r, "init", "-q", "-b", "main")
    _write_entry(r, "2026-11-01", "first", "1.0.0")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "branch", "base")
    return r


def _problems(r):
    _git(r, "add", "-A")
    return cv.check_changelog(r) + cv.check_against(r, "base")


def test_fixture_base_is_clean(repo):
    assert _problems(repo) == []


def test_contract_change_without_an_entry_fails(repo):
    (repo / "shared" / "recipe" / "schema.json").write_text('{"a": 2}\n')
    problems = _problems(repo)
    assert any("contract file in shared/ changed" in p for p in problems), problems
    assert any("not greater than 1.0.0" in p for p in problems), problems


def test_contract_change_with_entry_but_no_bump_fails(repo):
    (repo / "shared" / "recipe" / "schema.json").write_text('{"a": 2}\n')
    _write_entry(repo, "2026-11-02", "second", "1.0.0")
    problems = _problems(repo)
    assert any("not greater than 1.0.0" in p for p in problems), problems


def test_edited_old_entry_fails(repo):
    """Replacing the digest of the base entry, with a bump, is still caught."""
    (repo / "shared" / "recipe" / "schema.json").write_text('{"a": 2}\n')
    (repo / "shared" / "VERSION").write_text("1.1.0\n")
    _git(repo, "add", "-A")
    log = repo / "shared" / "CHANGELOG.md"
    text = log.read_text()
    text = cv.DIGEST_LINE.sub(f"Contracts sha256: `{cv.digest(repo)}`", text)
    log.write_text(text.replace("`1.0.0`", "`1.1.0`"))
    problems = _problems(repo)
    assert any("already on the base" in p for p in problems), problems


def test_version_file_and_entry_must_agree(repo):
    (repo / "shared" / "recipe" / "schema.json").write_text('{"a": 2}\n')
    _write_entry(repo, "2026-11-02", "second", "1.1.0")
    (repo / "shared" / "VERSION").write_text("1.2.0\n")
    problems = _problems(repo)
    assert any("shared/VERSION is 1.2.0" in p for p in problems), problems


def test_version_must_increase_down_the_changelog(repo):
    (repo / "shared" / "recipe" / "schema.json").write_text('{"a": 2}\n')
    _write_entry(repo, "2026-11-02", "second", "0.9.0")
    problems = _problems(repo)
    assert any("not greater than 1.0.0 in the older entry" in p for p in problems), problems


def test_contract_change_with_entry_and_bump_passes(repo):
    (repo / "shared" / "recipe" / "schema.json").write_text('{"a": 2}\n')
    _write_entry(repo, "2026-11-02", "second", "1.1.0")
    assert _problems(repo) == []


def test_tooling_and_prose_changes_need_no_bump(repo):
    (repo / "shared" / "ci" / "tool.py").write_text("x = 2\n")
    (repo / "shared" / "recipe" / "README.md").write_text("prose\n")
    assert _problems(repo) == []


def test_new_contract_file_needs_a_bump(repo):
    (repo / "shared" / "recipe" / "new.json").write_text("{}\n")
    problems = _problems(repo)
    assert any("shared/recipe/new.json" in p for p in problems), problems


# The command the CI job runs, against the throwaway repository.

def _cli(repo, *args):
    return subprocess.run([sys.executable, str(SHARED / "ci" / "contract_version.py"),
                           "--repo", str(repo), "--check", *args],
                          capture_output=True, text=True)


def test_cli_check_passes_a_clean_change(repo):
    (repo / "shared" / "recipe" / "schema.json").write_text('{"a": 2}\n')
    _write_entry(repo, "2026-11-02", "second", "1.1.0")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    r = _cli(repo, "--base", "base")
    assert r.returncode == 0, r.stderr
    assert "shared/recipe/schema.json" in r.stdout


def test_cli_check_fails_a_change_with_no_bump(repo):
    (repo / "shared" / "recipe" / "schema.json").write_text('{"a": 2}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    r = _cli(repo, "--base", "base")
    assert r.returncode == 1
    assert "not greater than 1.0.0" in r.stderr


def test_cli_check_fails_without_a_base(repo):
    """No base is an error, never a silent pass of the history check."""
    r = _cli(repo, "--base", "no-such-ref")
    assert r.returncode == 1
    assert "no merge base of HEAD and no-such-ref" in r.stderr
