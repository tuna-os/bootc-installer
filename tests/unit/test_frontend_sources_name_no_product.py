"""No frontend source names a product in a string it runs with.

CLAUDE.md: no "TunaOS", "Bluefin" or other product in any frontend; the
product comes from the branding resolver (shared/branding/README.md).
KDE's main.cpp set the application name to "TunaOS Installer" and no test
saw it. This one reads the runtime sources of all five frontends and fails
on a string literal that holds a product name. Comments, docstrings and
test code are not runtime strings and are skipped.
"""

import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]

PRODUCTS = ("TunaOS", "Bluefin")

# Runtime source trees and the file types read in each.
SOURCES = {
    "bootc_installer": (".py",),
    "frontends/kde/src": (".cpp", ".h", ".qml"),
    "frontends/kde/modules": (".qml", ".js"),
    "frontends/cosmic/src": (".rs",),
    "frontends/niri/installer": (".go",),
    "frontends/niri/ui": (".qml", ".js"),
    "frontends/xfce/tuna_installer_xfce": (".py",),
}

# A string literal in C-like and Python sources: "..." or '...'.
_LITERAL = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')
_COMMENT = {".cpp": "//", ".h": "//", ".qml": "//", ".js": "//", ".rs": "//",
            ".go": "//", ".py": "#"}


def _runtime_lines(path):
    """(number, line) for each line of `path` that runs: no Rust test
    module, no Python docstring, no comment-only line."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if path.suffix == ".rs" and "#[cfg(test)]" in text:
        lines = lines[: next(i for i, text_line in enumerate(lines) if "#[cfg(test)]" in text_line)]
    in_doc = False
    for n, line in enumerate(lines, 1):
        stripped = line.strip()
        if path.suffix == ".py":
            quotes = stripped.count('"""') + stripped.count("'''")
            if in_doc or stripped.startswith(('"""', "'''")):
                if in_doc and quotes % 2 == 1:
                    in_doc = False
                elif not in_doc and quotes % 2 == 1:
                    in_doc = True
                continue
        if stripped.startswith(_COMMENT[path.suffix]):
            continue
        # Drop a trailing comment, unless the marker is inside a string.
        marker = _COMMENT[path.suffix]
        code = line
        idx = code.find(marker)
        if idx >= 0 and not any(m.start() < idx < m.end() for m in _LITERAL.finditer(code)):
            code = code[:idx]
        yield n, code


def _is_test(path):
    name = path.name
    return (name.endswith("_test.go") or name.startswith("test_")
            or "tests" in path.parts or "test" in path.parts)


def offenders():
    found = []
    for tree, suffixes in SOURCES.items():
        root = REPO / tree
        for path in sorted(root.rglob("*")):
            if path.suffix not in suffixes or not path.is_file() or _is_test(path):
                continue
            for n, code in _runtime_lines(path):
                for literal in _LITERAL.findall(code):
                    if any(p in literal for p in PRODUCTS):
                        found.append(f"{path.relative_to(REPO)}:{n}: {literal}")
    return found


class FrontendSourcesNameNoProduct(unittest.TestCase):
    def test_no_runtime_string_names_a_product(self):
        self.assertEqual(offenders(), [], "a frontend source names a product; "
                         "read it from the branding resolver instead")

    def test_the_check_sees_a_product_string(self):
        # The scan must catch the case that slipped through (KDE main.cpp).
        sample = 'app.setApplicationName(u"TunaOS Installer"_s);'
        self.assertTrue(any("TunaOS" in lit for lit in _LITERAL.findall(sample)))


if __name__ == "__main__":
    unittest.main()
