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
    # progress.js is the QML's JavaScript library: the receipt lines (#269)
    # are joined there.
    "niri": [("frontends/niri/ui", ("*.qml", "*.js"))],
    "xfce": [("frontends/xfce/tuna_installer_xfce", ("*.py",))],
}

RESOLVERS = re.compile(r"^(branding\.(py|rs|cpp|h|go)|branding_defaults\.h\.in|copy-defaults\.json"
                       r"|fisherman_validate\.py)$")

# frontend -> {key: why it is not rendered there}. Every row is a parity gap,
# not an exemption on principle. A key ending in "*" names every contract key
# with that prefix (the validate_* family is rendered, or not, as one).
KNOWN_GAPS = {
    "gnome": {
        "welcome_button": "bootc_installer/gtk/default-welcome.blp hardcodes the button label",
        "encryption_none_description": "the encryption page is an on/off switch, not a list of choices, so no row describes no encryption",
        "encryption_tpm2_luks_description": "the page cannot produce tpm2-luks: its TPM switch always keeps the passphrase",
    },
    "kde": {
        "welcome_install": "modules/welcome hardcodes its two body sentences",
        "welcome_install_subtitle": "modules/welcome hardcodes its two body sentences",
        "filesystem_zfs_label": "the disk step offers no ZFS (src/recipe.cpp has no zfs choice)",
        "confirm_plan_*": "no install plan on the confirm page yet (tuna-os/fisherman#371)",
    },
    "cosmic": {
        "welcome_install": "the welcome page has no install row to label",
        "welcome_install_subtitle": "the welcome page has no install row to label",
    },
    "niri": {
        "confirm_plan_*": "no install plan on the confirm page yet (tuna-os/fisherman#371)",
    },
    "xfce": {},
}


def expand(keys, names):
    """`names` with any "prefix*" entry replaced by the contract keys it
    covers."""
    out = set()
    for name in names:
        if name.endswith("*"):
            out |= {k for k in keys if k.startswith(name[:-1])}
        else:
            out.add(name)
    return out


def gaps(frontend, keys):
    return expand(keys, KNOWN_GAPS.get(frontend, {}))


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


COMMENT_MARKERS = {".py": "#", ".qml": "//", ".js": "//", ".rs": "//", ".cpp": "//",
                   ".h": "//", ".blp": "//"}


SCHEMA = REPO / "shared" / "recipe" / "fisherman-recipe.schema.json"
CHOICE_SUFFIXES = ("_label", "_description")


def encryption_types():
    """The recipe's encryption types in display order: the schema enum, less
    the "" that fisherman also reads as none."""
    schema = json.loads(SCHEMA.read_text())
    enum = schema["properties"]["encryption"]["properties"]["type"]["enum"]
    return [t for t in enum if t]


def encryption_key(enc_type, suffix):
    return "encryption_" + enc_type.replace("-", "_") + suffix


def rendered_encryption_keys(text):
    """Choice keys a frontend builds from the recipe id at run time.

    No source names encryption_tpm2_luks_label whole: every frontend joins
    "encryption_", the id and a suffix. So a line that passes a "_label" or
    "_description" literal renders that suffix for the id literal on the same
    line, or, with no id literal there, for every id (the type is a variable).
    tests/unit/test_encryption_choices.py checks which ids each frontend
    actually offers.
    """
    types = encryption_types()
    found = set()
    for line in text.splitlines():
        for suffix in CHOICE_SUFFIXES:
            if f'"{suffix}"' not in line and f"'{suffix}'" not in line:
                continue
            named = [t for t in types if f'"{t}"' in line or f"'{t}'" in line]
            found |= {encryption_key(t, suffix) for t in (named or types)}
    return found


STEP_PREFIX = "step_"


def rendered_step_keys(text, keys):
    """Step-label keys a frontend builds from fisherman's step_id at run time.

    fisherman owns the step ids and puts one on every step event; no frontend
    keeps the list, so none names step_install_os whole. A frontend that
    joins a "step_" literal with the event's id renders every step key
    (shared/branding/README.md, "Install steps").
    tests/unit/test_shared_progress.py holds the keys to fisherman's ids.
    """
    if f'"{STEP_PREFIX}"' in text or f"'{STEP_PREFIX}'" in text:
        return {k for k in keys if k.startswith(STEP_PREFIX)}
    return set()


VALIDATE_PREFIX = "validate_"
# The shared Python reader's render(): it joins the prefix with the code, so
# a Python frontend that calls it renders every validate_* key.
VALIDATE_RENDER = "fisherman_validate.render("


def rendered_validate_keys(text, keys):
    """Problem keys a frontend builds from fisherman's error code at run time.

    `fisherman validate --json` owns the codes (fisherman/docs/VALIDATE.md)
    and no frontend keeps the list, so none names validate_hostname_required
    whole. A frontend that joins a "validate_" literal with the code, or
    calls the shared reader's render(), renders every validate_* key.
    tests/unit/test_shared_validate.py holds the keys to fisherman's codes.
    """
    if (f'"{VALIDATE_PREFIX}"' in text or f"'{VALIDATE_PREFIX}'" in text
            or VALIDATE_RENDER in text):
        return {k for k in keys if k.startswith(VALIDATE_PREFIX)}
    return set()


SOURCE_FAMILIES = ("source_check_", "bootc_store_kind_", "done_receipt_", "progress_reuse_")
# The shared Python reader's rows(): it builds every source_check_*,
# bootc_store_* and source_* line, so a Python frontend that calls it
# renders all of them.
SOURCE_RENDER = "source_check.rows("
# The shared Python done-page lines (#269): receipt_text() names
# done_verification and every done_receipt_* line; reuse_rows() the
# install-source choice (#267).
RECEIPT_RENDER = "completion.receipt_text("
REUSE_RENDER = "source_check.reuse_rows("
# The failure page's lines for fisherman's `error` event (fisherman#449):
# bootc_shared.progress.failure_text() names every done_failed_disk_* and
# done_failed_cleanup_* line.
FAILURE_RENDER = "failure_text("
FAILURE_FAMILIES = ("done_failed_disk_", "done_failed_cleanup_")
# The progress page's lines for the copy of this computer's system (#267):
# bootc_shared.progress.source_reuse_text() names every progress_reuse_*
# line but the cancel question, which a frontend names itself.
COPY_PROGRESS_RENDER = "source_reuse_text("
COPY_CANCEL_KEY = "progress_reuse_cancel"
# The confirm page's install plan (tuna-os/fisherman#371):
# bootc_shared.plan.rows() names every confirm_plan_* line but the group
# title, which a frontend names itself.
PLAN_RENDER = "install_plan.rows("
PLAN_PREFIX = "confirm_plan_"


def rendered_source_keys(text, keys):
    """Source-check keys a frontend builds at run time (#266, #267).

    fisherman owns the states and reason codes; the shared readers turn
    them into `source_check_<state>`, `source_check_reason_<code>` and
    `source_check_default_<name>` (shared/probe/README.md, "Source
    check"), and an item of the bootc storage into `bootc_store_kind_<kind>`.
    A frontend that joins the prefix renders the family; a Python frontend
    that calls the shared rows() renders every source and store key.
    """
    found = set()
    if SOURCE_RENDER in text:
        found |= {k for k in keys if k.startswith(("source_", "bootc_store_"))}
    if RECEIPT_RENDER in text:
        found |= {k for k in keys if k.startswith("done_receipt_") or k == "done_verification"}
    if FAILURE_RENDER in text:
        found |= {k for k in keys if k.startswith(FAILURE_FAMILIES)}
    if REUSE_RENDER in text:
        found |= {k for k in keys if k.startswith("source_reuse_")}
    if COPY_PROGRESS_RENDER in text:
        found |= {k for k in keys if k.startswith("progress_reuse_") and k != COPY_CANCEL_KEY}
    if PLAN_RENDER in text:
        found |= {k for k in keys if k.startswith(PLAN_PREFIX) and k != PLAN_PREFIX + "title"}
    for prefix in SOURCE_FAMILIES:
        if f'"{prefix}"' in text or f"'{prefix}'" in text:
            found |= {k for k in keys if k.startswith(prefix) and k != COPY_CANCEL_KEY}
    return found


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
    named = {k for k in keys if f'"{k}"' in joined or f"'{k}'" in joined}
    return (named | (rendered_encryption_keys(joined) & set(keys))
            | rendered_step_keys(joined, keys) | rendered_validate_keys(joined, keys)
            | rendered_source_keys(joined, keys))


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
            row = dict(zip(columns, cells[1:]))
            # One row stands for a family of keys: `validate_*`.
            for key in (expand(contract_keys(), [name]) if name.endswith("*") else [name]):
                rows[key] = row
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
                is_gap = key in gaps(frontend, self.keys)
                self.assertEqual(
                    says_no, is_gap,
                    f"docs/PARITY.md {key}/{frontend} says {cell!r} but "
                    f"KNOWN_GAPS {'lists' if is_gap else 'does not list'} it",
                )

    def test_the_parser_found_a_real_table(self):
        self.assertGreater(len(self.table), 15)
        self.assertEqual(sorted(self.table["done_title"]),
                         ["cosmic", "gnome", "kde", "niri", "xfce"])


class StepKeys(unittest.TestCase):
    def test_a_step_prefix_literal_renders_every_step_key(self):
        keys = {"step_install_os": "", "step_mount": "", "done_title": ""}
        self.assertEqual(rendered_step_keys('text("step_" + id)', keys),
                         {"step_install_os", "step_mount"})

    def test_a_key_name_alone_is_not_the_prefix(self):
        keys = {"step_install_os": ""}
        self.assertEqual(rendered_step_keys('"step_install_os"', keys), set())
        self.assertEqual(rendered_step_keys("step_ = 1", keys), set())


class ValidateKeys(unittest.TestCase):
    def test_a_validate_prefix_literal_renders_every_validate_key(self):
        keys = {"validate_hostname_required": "", "validate_username_reserved": "",
                "done_title": ""}
        both = {"validate_hostname_required", "validate_username_reserved"}
        self.assertEqual(rendered_validate_keys('text("validate_" + code)', keys), both)
        self.assertEqual(rendered_validate_keys(
            "fisherman_validate.render(problem, text)", keys), both)

    def test_a_key_name_alone_is_not_the_prefix(self):
        keys = {"validate_hostname_required": ""}
        self.assertEqual(rendered_validate_keys('"validate_hostname_required"', keys), set())

    def test_a_wildcard_gap_expands_to_the_family(self):
        keys = {"validate_a": "", "validate_b": "", "done_title": ""}
        self.assertEqual(expand(keys, ["validate_*", "done_title"]),
                         {"validate_a", "validate_b", "done_title"})


class SourceKeys(unittest.TestCase):
    def test_a_prefix_literal_renders_its_family(self):
        keys = {"source_check_ready": "", "source_check_reason_live_root": "",
                "bootc_store_kind_booted": "", "source_install_from": "", "done_title": ""}
        self.assertEqual(rendered_source_keys('text("source_check_" + state)', keys),
                         {"source_check_ready", "source_check_reason_live_root"})
        self.assertEqual(rendered_source_keys('text("bootc_store_kind_" + kind)', keys),
                         {"bootc_store_kind_booted"})

    def test_the_shared_rows_render_every_source_key(self):
        keys = {"source_check_ready": "", "bootc_store_listed": "",
                "source_install_from": "", "done_title": ""}
        self.assertEqual(rendered_source_keys("source_check.rows(view, store, text)", keys),
                         {"source_check_ready", "bootc_store_listed", "source_install_from"})

    def test_a_key_name_alone_is_not_the_prefix(self):
        self.assertEqual(rendered_source_keys('"source_check_ready"',
                                              {"source_check_ready": ""}), set())


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
                unlisted = sorted(missing - gaps(frontend, self.keys))
                self.assertEqual(
                    unlisted, [],
                    f"{frontend} renders no copy for {unlisted}. Wire the keys up, "
                    "or add them to KNOWN_GAPS with the reason.",
                )

    def test_no_stale_gaps(self):
        """A gap that has been closed must lose its row, or the backlog lies."""
        for frontend in KNOWN_GAPS:
            with self.subTest(frontend=frontend):
                rendered = rendered_keys(frontend, self.keys)
                stale = sorted(gaps(frontend, self.keys) & rendered)
                self.assertEqual(
                    stale, [],
                    f"{frontend} does render {stale}; delete those rows from KNOWN_GAPS.",
                )

    def test_gaps_name_real_keys(self):
        for frontend, listed in KNOWN_GAPS.items():
            for key, why in listed.items():
                self.assertTrue(expand(self.keys, [key]) & set(self.keys),
                                f"{frontend}: {key} is not on the contract")
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
