"""Relative-link and doc-path resolver for changed Markdown files.

Only ``*.md`` files changed against the PR base are checked, so existing debt
in untouched files does not fail unrelated PRs. Base ref comes from
``DOC_REFS_BASE`` (default ``origin/dev``). No network calls.

Check 1: relative Markdown links resolve from the containing file's directory.
Check 2: backticked repo-relative paths whose first segment is a top-level
entry of the repo resolve from the repo root.
Exceptions go in tests/unit/doc_references_allowlist.txt, one reason each.
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).with_name("doc_references_allowlist.txt")

LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)")
TICK_RE = re.compile(r"`([^`\n]+)`")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "ftp://", "data:")
NOT_A_PATH = set("*?<>{}$|=\\ ")


def load_allowlist(path=ALLOWLIST):
    """Return {reference: reason}. An entry without a reason is an error."""
    entries = {}
    if not Path(path).exists():
        return entries
    for n, raw in enumerate(Path(path).read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ref, sep, reason = line.partition(" | ")
        if not sep or not reason.strip():
            raise ValueError(f"{path}:{n}: allowlist entry needs ' | <reason>'")
        entries[ref.strip()] = reason.strip()
    return entries


def _prose_lines(text):
    """Yield (lineno, line) outside fenced code blocks."""
    fence = None
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r"\s*(`{3,}|~{3,})", line)
        if m:
            marker = m.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is None:
            yield n, line


def find_problems(md_file, repo_root, allowlist=None):
    """Return a list of 'file:line: reference does not resolve' strings."""
    repo_root = Path(repo_root)
    md_file = Path(md_file)
    allowlist = allowlist or {}
    rel = md_file.relative_to(repo_root).as_posix()
    problems = []
    top = {p.name for p in repo_root.iterdir() if p.name != ".git"}

    for n, line in _prose_lines(md_file.read_text(errors="replace")):
        for m in LINK_RE.finditer(line):
            target = (m.group(1) or m.group(2)).strip("<>")
            if target.startswith("#") or target.lower().startswith(SKIP_SCHEMES):
                continue
            if target in allowlist:
                continue
            path = target.split("#", 1)[0].split("?", 1)[0]
            if not path:
                continue
            base = repo_root if path.startswith("/") else md_file.parent
            if not (base / path.lstrip("/")).exists():
                problems.append(f"{rel}:{n}: link '{target}' does not resolve")

        for m in TICK_RE.finditer(line):
            token = m.group(1).strip()
            if "/" not in token or any(c in NOT_A_PATH for c in token):
                continue
            if token.startswith(("./", "../", "/", "~")) or "://" in token or "..." in token:
                continue
            if token in allowlist:
                continue
            path = re.sub(r":\d+(-\d+)?$", "", token).rstrip("/.,;")
            if path.split("/", 1)[0] not in top:
                continue
            if not (repo_root / path).exists():
                problems.append(f"{rel}:{n}: path '{token}' does not resolve")
    return problems


def changed_markdown(repo_root=REPO_ROOT):
    """Changed *.md files vs the base; None when the base is unavailable."""
    base = os.environ.get("DOC_REFS_BASE", "origin/dev")
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=d", f"{base}...HEAD", "--", "*.md"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [repo_root / f for f in out.split() if (repo_root / f).is_file()]


class TestChangedDocReferences(unittest.TestCase):
    def test_changed_markdown_references_resolve(self):
        files = changed_markdown()
        if files is None:
            self.skipTest("base ref unavailable; set DOC_REFS_BASE")
        allow = load_allowlist()
        problems = []
        for f in files:
            problems += find_problems(f, REPO_ROOT, allow)
        self.assertEqual(problems, [], "\n" + "\n".join(problems))


class TestResolverSelfTest(unittest.TestCase):
    def _repo(self, doc):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "docs").mkdir()
        (root / "docs" / "real.md").write_text("ok\n")
        (root / "scripts").mkdir()
        (root / "scripts" / "real.sh").write_text("")
        md = root / "docs" / "page.md"
        md.write_text(doc)
        return root, md

    def test_fail_fixture(self):
        root, md = self._repo(
            "[gone](missing.md) and `scripts/missing.sh`\n"
            "```\n[ignored](nope.md)\n```\n"
        )
        problems = find_problems(md, root)
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("docs/page.md:1: link 'missing.md'", problems[0])
        self.assertIn("docs/page.md:1: path 'scripts/missing.sh'", problems[1])

    def test_pass_fixture(self):
        root, md = self._repo(
            "[a](real.md#x) [b](#top) [c](https://x.invalid/y) "
            "`scripts/real.sh` `unknowndir/file` `a/*.md`\n"
        )
        self.assertEqual(find_problems(md, root), [])

    def test_allowlist(self):
        root, md = self._repo("[gone](missing.md)\n")
        self.assertEqual(find_problems(md, root, {"missing.md": "build-time"}), [])

    def test_allowlist_requires_reason(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("some/path\n")
        self.addCleanup(os.unlink, f.name)
        with self.assertRaises(ValueError):
            load_allowlist(f.name)


if __name__ == "__main__":
    unittest.main()
