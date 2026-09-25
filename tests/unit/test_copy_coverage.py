"""Who actually renders the branding copy contract.

shared/branding/copy-defaults.json says "Every frontend renders every key".
Nothing checked that, and it was not true: five of the twenty-two keys reach
no frontend at all, and Niri's QML carried its own hand-written copy of the
table that had been missing `welcome_install_subtitle` since the key was
added.

Two checks live here.

1. The generated table in frontends/niri/ui/installer.qml must match
   shared/branding/copy-defaults.json exactly. QML cannot read the file, and
   the backend that would send `branding.copy` is stubbed during every
   capture run, so that table is what the walkthrough renders. Regenerate it
   with shared/branding/generate-qml-defaults.py.

2. Every contract key must be named by some source file in every frontend,
   or be listed in KNOWN_GAPS with the reason. The scan is deliberately
   crude -- a key counts as rendered if a non-resolver source mentions it --
   because the five frontends are in five languages with five different call
   helpers (`copy_text.text`, `BRANDING.text`, `t_line`, `t_disk`,
   `InstallerController.text`, `root.text`). It catches the failure that
   matters: a key on the contract that a frontend has simply never wired up.

KNOWN_GAPS is the real parity backlog, and it is meant to shrink. Closing a
row means rendering the key in that frontend and deleting the row; the test
fails if a row is listed but the key is in fact rendered, so a stale
exemption cannot linger.
"""

import json
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
CANONICAL = REPO / "shared" / "branding" / "copy-defaults.json"
NIRI_QML = REPO / "frontends" / "niri" / "ui" / "installer.qml"
PARITY = REPO / "docs" / "PARITY.md"
GENERATOR = REPO / "shared" / "branding" / "generate-qml-defaults.py"

BEGIN = "// COPY-DEFAULTS-BEGIN"
END = "// COPY-DEFAULTS-END"

# Where each frontend's user-facing code lives. Resolver files are excluded
# by name below: they embed the whole table, so they would answer "yes" for
# every key and the scan would prove nothing.
SOURCES = {
    "gnome": [("bootc_installer", ("*.py", "*.blp"))],
    "kde": [("frontends/kde/src", ("*.cpp", "*.h", "*.qml")),
            ("frontends/kde/modules", ("*.qml",))],
    "cosmic": [("frontends/cosmic/src", ("*.rs",))],
    "niri": [("frontends/niri/ui", ("*.qml",))],
    "xfce": [("frontends/xfce/tuna_installer_xfce", ("*.py",))],
}

RESOLVERS = re.compile(r"^(branding\.(py|rs|cpp|h|go)|branding_defaults\.h\.in|copy-defaults\.json)$")

# frontend -> {key: why it is not rendered there}. Every row is a parity gap,
# not an exemption on principle.
KNOWN_GAPS = {
    "gnome": {
        "welcome_button": "bootc_installer/gtk/default-welcome.blp hardcodes the button label",
        "confirm_warning": "bootc_installer/gtk/dialog-disk-confirm.blp hardcodes the warning",
        "progress_note": "bootc_installer/gtk/progress.blp hardcodes the do-not-power-off line",
    },
    "kde": {
        "welcome_install": "modules/welcome hardcodes its two body sentences",
        "welcome_install_subtitle": "modules/welcome hardcodes its two body sentences",
    },
    "cosmic": {
        "welcome_install": "the welcome page has no install row to label",
        "welcome_install_subtitle": "the welcome page has no install row to label",
    },
    "niri": {
        "welcome_install": "the welcome page has no install row to label",
        "welcome_install_subtitle": "the welcome page has no install row to label",
    },
    "xfce": {
    },
}


def contract_keys():
    raw = json.loads(CANONICAL.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def qml_table():
    """The generated defaults object, parsed back out of installer.qml."""
    text = NIRI_QML.read_text()
    body = text.split(BEGIN, 1)[1].split(END, 1)[0]
    out = {}
    for line in body.splitlines():
        m = re.match(r'\s*([a-z_][a-z0-9_]*):\s*(".*?"),?\s*$', line)
        if m:
            out[m.group(1)] = json.loads(m.group(2))
    return out


def sources_for(frontend):
    for subdir, patterns in SOURCES[frontend]:
        root = REPO / subdir
        for pattern in patterns:
            for path in root.rglob(pattern):
                if RESOLVERS.match(path.name) or "__pycache__" in path.parts:
                    continue
                yield path


def strip_comments(text, marker):
    """Drop line comments, skipping any marker that sits inside a string.

    Comments name keys all the time -- this file's own neighbours explain
    which key a widget renders -- and a comment is not a render. Nothing
    here needs to be a real parser: over-stripping can only turn a rendered
    key into a reported gap, which is a visible failure, never a silent pass.
    """
    out = []
    for line in text.splitlines():
        quote = ""
        for i, ch in enumerate(line):
            if quote:
                if ch == quote and line[i - 1:i] != "\\":
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif line.startswith(marker, i):
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


COMMENT_MARKERS = {".py": "#", ".qml": "//", ".rs": "//", ".cpp": "//",
                   ".h": "//", ".blp": "//"}


def rendered_keys(frontend, keys):
    """Keys named anywhere in this frontend's non-resolver, non-comment code.

    Niri's generated table is stripped first: it names every key by
    construction, so leaving it in would mark every key rendered.
    """
    blobs = []
    for path in sources_for(frontend):
        text = path.read_text(errors="replace")
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            text = head + rest.split(END, 1)[1]
        blobs.append(strip_comments(text, COMMENT_MARKERS[path.suffix]))
    joined = "\n".join(blobs)
    # As a quoted literal, not a bare substring: GNOME's
    # __on_recovery_key_acknowledged contains "recovery_key_ack", and a
    # method name is not a render.
    return {k for k in keys if f'"{k}"' in joined or f"'{k}'" in joined}


class NiriTableMatchesTheContract(unittest.TestCase):
    def test_keys_and_values_are_identical(self):
        self.assertEqual(
            qml_table(), contract_keys(),
            "frontends/niri/ui/installer.qml's defaults table has drifted from "
            "shared/branding/copy-defaults.json; regenerate it with "
            "shared/branding/generate-qml-defaults.py",
        )

    def test_the_table_is_marked_as_generated(self):
        # Without the markers the generator rewrites nothing and this test
        # parses an empty table, which would then match nothing.
        text = NIRI_QML.read_text()
        self.assertIn(BEGIN, text)
        self.assertIn(END, text)
        self.assertIn("generate-qml-defaults.py", text,
                      "the table must say what regenerates it")
        self.assertTrue(GENERATOR.is_file())

    def test_the_parser_would_notice_a_changed_value(self):
        # Guards the guard: a parser that silently returned {} would make
        # the comparison above pass against an emptied contract.
        table = qml_table()
        self.assertGreater(len(table), 10)
        self.assertEqual(table["progress_note"], "Do not power off the computer.")


def parity_table():
    """docs/PARITY.md's copy-key table: {key: {frontend: cell}}.

    Only rows naming exactly one contract key are returned; the table also
    carries rows for `confirm_quotes` and the asset keys, which are not copy
    keys and are not scanned here.
    """
    rows = {}
    columns = None
    for line in PARITY.read_text().splitlines():
        if not line.startswith("|"):
            columns = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] == "Key":
            columns = [c.lower() for c in cells[1:]]
            continue
        if columns is None or set(cells[0]) <= set("-: "):
            continue
        name = cells[0].strip("`")
        if len(cells) == len(columns) + 1:
            rows[name] = dict(zip(columns, cells[1:]))
    return rows


class ParityPageMatchesTheGaps(unittest.TestCase):
    """docs/PARITY.md is the page a product reads before rebranding, so a
    cell that claims a render there has to be one. Four of them were not."""

    def setUp(self):
        self.keys = contract_keys()
        self.table = parity_table()

    def test_the_table_lists_every_contract_key(self):
        missing = sorted(set(self.keys) - set(self.table))
        self.assertEqual(missing, [], "docs/PARITY.md has no row for these keys")

    def test_every_no_cell_is_a_listed_gap(self):
        for key, row in self.table.items():
            if key not in self.keys:
                continue
            for frontend, cell in row.items():
                if frontend not in SOURCES:
                    continue
                says_no = cell.lower().startswith("no")
                is_gap = key in KNOWN_GAPS.get(frontend, {})
                self.assertEqual(
                    says_no, is_gap,
                    f"docs/PARITY.md {key}/{frontend} says {cell!r} but "
                    f"KNOWN_GAPS {'lists' if is_gap else 'does not list'} it",
                )

    def test_the_parser_found_a_real_table(self):
        self.assertGreater(len(self.table), 15)
        self.assertEqual(sorted(self.table["done_title"]),
                         ["cosmic", "gnome", "kde", "niri", "xfce"])


class CommentStripping(unittest.TestCase):
    def test_a_comment_is_not_a_render(self):
        self.assertNotIn("done_title",
                         strip_comments('// renders done_title', "//"))
        self.assertNotIn("done_title",
                         strip_comments('x = 1  # done_title lives here', "#"))

    def test_code_before_the_comment_survives(self):
        self.assertIn("done_title",
                      strip_comments('text("done_title")  // the heading', "//"))

    def test_a_marker_inside_a_string_is_not_a_comment(self):
        self.assertIn("store_label",
                      strip_comments('url = "https://x"; t("store_label")', "//"))


class EveryFrontendRendersEveryKey(unittest.TestCase):
    def setUp(self):
        self.keys = contract_keys()

    def test_no_unlisted_gaps(self):
        for frontend in SOURCES:
            with self.subTest(frontend=frontend):
                missing = set(self.keys) - rendered_keys(frontend, self.keys)
                unlisted = sorted(missing - set(KNOWN_GAPS.get(frontend, {})))
                self.assertEqual(
                    unlisted, [],
                    f"{frontend} renders no copy for {unlisted}. Wire the keys up, "
                    "or add them to KNOWN_GAPS with the reason.",
                )

    def test_no_stale_gaps(self):
        """A gap that has been closed must lose its row, or the backlog lies."""
        for frontend, gaps in KNOWN_GAPS.items():
            with self.subTest(frontend=frontend):
                rendered = rendered_keys(frontend, self.keys)
                stale = sorted(set(gaps) & rendered)
                self.assertEqual(
                    stale, [],
                    f"{frontend} does render {stale}; delete those rows from KNOWN_GAPS.",
                )

    def test_gaps_name_real_keys(self):
        for frontend, gaps in KNOWN_GAPS.items():
            for key, why in gaps.items():
                self.assertIn(key, self.keys, f"{frontend}: {key} is not on the contract")
                self.assertTrue(why.strip(), f"{frontend}: {key} needs a reason")

    def test_the_scan_finds_something(self):
        """Guards the guard: a broken glob would report every key as a gap,
        and every gap is listed, so both checks above would pass."""
        for frontend in SOURCES:
            with self.subTest(frontend=frontend):
                self.assertGreater(len(list(sources_for(frontend))), 2)
                self.assertGreaterEqual(len(rendered_keys(frontend, self.keys)), 10)


if __name__ == "__main__":
    unittest.main()
