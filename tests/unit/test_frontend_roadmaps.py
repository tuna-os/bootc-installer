"""The four frontend ROADMAP.md files cite only this repository's issues.

kde, cosmic, niri and xfce were separate repositories until 2026-09-17
(docs/MIGRATION.md). Their roadmaps came in with them and kept the old
issue numbers. A bare `#33` in `frontends/kde/ROADMAP.md` then pointed at
bootc-installer#33, an unrelated issue (#112).

The check has no network, so it cannot ask GitHub whether an issue exists.
It uses what docs/MIGRATION.md records instead. That page lists every pull
request and issue that was open at the move, for this repository and for
each old one. An issue about one frontend can exist in this repository only
after the move, so its number is above every number in the bootc-installer
list. A number at or below that floor, or at or below the highest number of
the frontend's old repository, can be an old reference, and the test
refuses it. The limit of this check: it does not prove that a number above
the floor is an open issue, or the correct one.

The test also refuses the two marks of the old plans (a reference of the
form `tuna-installer-<name>#N`, and the "Current Quarter (2026 Q3)"
heading), and it makes sure that each file points at the documents that
hold the plan now.
"""

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTENDS = ("kde", "cosmic", "niri", "xfce")
MIGRATION = REPO / "docs" / "MIGRATION.md"

# Each roadmap must link to these, relative to frontends/<name>/.
POINTERS = (
    "../../ROADMAP.md",
    "../../docs/MIGRATION.md",
    "../../docs/RELEASE.md",
    "../../shared/",
    "../../docs/walkthrough/",
)


def highest_recorded(repo_name):
    """Highest PR or issue number in the MIGRATION.md section of `repo_name`."""
    text = MIGRATION.read_text(encoding="utf-8")
    match = re.search(
        r"^## tuna-os/%s\n(.*?)(?=^## |\Z)" % re.escape(repo_name),
        text, re.S | re.M)
    assert match, f"docs/MIGRATION.md has no section for tuna-os/{repo_name}"
    numbers = [int(n) for n in re.findall(r"^\| \[#(\d+)\]", match.group(1), re.M)]
    assert numbers, f"docs/MIGRATION.md lists no numbers for tuna-os/{repo_name}"
    return max(numbers)


def roadmap(name):
    return (REPO / "frontends" / name / "ROADMAP.md").read_text(encoding="utf-8")


def cited(text):
    """Bare `#N` references. `owner/repo#N` names its repository, so skip it."""
    return sorted({int(n) for n in re.findall(r"(?<![\w/-])#(\d+)\b", text)})


def test_migration_record_gives_a_floor_for_every_frontend():
    assert highest_recorded("bootc-installer") >= 89
    for name in FRONTENDS:
        assert highest_recorded(f"tuna-installer-{name}") > 0


def test_cited_finds_bare_references_only():
    assert cited("see #12, (#300) and tuna-os/fisherman#405") == [12, 300]


@pytest.mark.parametrize("name", FRONTENDS)
def test_every_issue_number_is_from_after_the_move(name):
    floor = max(highest_recorded("bootc-installer"),
                highest_recorded(f"tuna-installer-{name}"))
    old = [n for n in cited(roadmap(name)) if n <= floor]
    assert not old, (
        f"frontends/{name}/ROADMAP.md cites {['#%d' % n for n in old]}. A number "
        f"at or below #{floor} can be an issue of the deleted "
        f"tuna-installer-{name} repository. Cite the issue that tracks the "
        "work in this repository.")


@pytest.mark.parametrize("name", FRONTENDS)
def test_no_mark_of_the_old_plan(name):
    text = roadmap(name)
    assert not re.search(r"tuna-installer-\w+#\d+", text), (
        f"frontends/{name}/ROADMAP.md cites an issue of a deleted repository")
    assert "Current Quarter (2026 Q3)" not in text, (
        f"frontends/{name}/ROADMAP.md still has the 2026 Q3 plan of the old "
        "repository; the plan is the root ROADMAP.md")


@pytest.mark.parametrize("name", FRONTENDS)
def test_points_at_the_monorepo_documents(name):
    text = roadmap(name)
    base = REPO / "frontends" / name
    for target in POINTERS:
        assert f"]({target}" in text, (
            f"frontends/{name}/ROADMAP.md has no link to {target}")
    for link in re.findall(r"\]\(([^)#]+)\)", text):
        if "://" in link:
            continue
        assert (base / link).exists(), (
            f"frontends/{name}/ROADMAP.md links to {link}, which does not exist")
