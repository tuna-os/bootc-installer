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
