#!/usr/bin/env python3
"""Rebuild po/POTFILES and the translation template from the tree.

    python3 po/update-pot.py            write POTFILES and the .pot, merge every .po
    python3 po/update-pot.py --check    exit 1 when either is out of date

POTFILES is not written by hand: it is every Blueprint template, every Python
module and the three data files. The template had gone two years without the
tree it describes (#311), and nothing noticed.

The xgettext arguments are the ones meson's `i18n.gettext(preset: 'glib')`
passes, so `ninja -C build bootc-installer-pot` writes the same messages.
xgettext reads a `.blp` file as C: Blueprint marks strings as `_("...")` and
`C_("context", "...")`, the same as C does.

The check compares messages, not bytes: line numbers, the creation date and
the line wrap of another xgettext version are not a reason to fail.
"""

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

PO_DIR = pathlib.Path(__file__).resolve().parent
ROOT = PO_DIR.parent
POTFILES = PO_DIR / "POTFILES"
MESON = PO_DIR / "meson.build"

DATA_GLOBS = ("data/*.desktop.in", "data/*.appdata.xml.in", "data/*.metainfo.xml.in",
              "data/*.gschema.xml")
# xgettext needs these rule files to read the XML data files. Without them it
# reads the XML as C and silently finds nothing.
ITS_RULES = {"data/*.appdata.xml.in": "metainfo.its", "data/*.metainfo.xml.in": "metainfo.its",
             "data/*.gschema.xml": "gschema.its"}
ITS_DIRS = (pathlib.Path("/usr/share/gettext/its"), pathlib.Path("/app/share/gettext/its"))

XGETTEXT_ARGS = (
    "--from-code=UTF-8", "--add-comments",
    "--keyword=_", "--keyword=N_", "--keyword=C_:1c,2", "--keyword=NC_:1c,2",
    "--keyword=g_dcgettext:2", "--keyword=g_dngettext:2,3", "--keyword=g_dpgettext2:2c,3",
    "--flag=N_:1:pass-c-format", "--flag=C_:2:pass-c-format", "--flag=NC_:2:pass-c-format",
    "--flag=g_dngettext:2:pass-c-format", "--flag=g_strdup_printf:1:c-format",
    "--flag=g_string_printf:2:c-format", "--flag=g_string_append_printf:2:c-format",
    "--flag=g_error_new:3:c-format", "--flag=g_set_error:4:c-format",
    "--flag=g_markup_printf_escaped:1:c-format", "--flag=g_log:3:c-format",
    "--flag=g_print:1:c-format", "--flag=g_printerr:1:c-format",
    "--flag=g_printf:1:c-format", "--flag=g_fprintf:2:c-format",
    "--flag=g_sprintf:2:c-format", "--flag=g_snprintf:3:c-format",
)


def domain():
    """The gettext domain po/meson.build builds."""
    match = re.search(r"i18n\.gettext\(\s*'([^']+)'", MESON.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"{MESON}: no i18n.gettext('<domain>', ...) call")
    return match.group(1)


def source_files():
    """Every file that can hold a translatable string, as repo-relative paths."""
    data = sorted(str(p.relative_to(ROOT)) for glob in DATA_GLOBS for p in ROOT.glob(glob))
    package = ROOT / "bootc_installer"
    blueprints = sorted(str(p.relative_to(ROOT)) for p in package.rglob("*.blp"))
    modules = sorted(str(p.relative_to(ROOT)) for p in package.rglob("*.py")
                     if "__pycache__" not in p.parts)
    return data, blueprints, modules


def potfiles_text():
    return "".join("\n".join(group) + "\n\n" for group in source_files() if group).rstrip("\n") + "\n"


def listed_files(text=None):
    text = POTFILES.read_text(encoding="utf-8") if text is None else text
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def missing_its_rules():
    missing = []
    for glob, rules in ITS_RULES.items():
        if any(ROOT.glob(glob)) and not any((d / rules).exists() for d in ITS_DIRS):
            missing.append(rules)
    return sorted(set(missing))


def extract(files, output):
    """Run xgettext over `files` into `output`."""
    if shutil.which("xgettext") is None:
        raise SystemExit("xgettext not found: install gettext")
    missing = missing_its_rules()
    if missing:
        raise SystemExit(
            "missing gettext ITS rules %s: install appstream and libglib2.0-dev "
            "(the strings of the data files would be lost)" % ", ".join(missing))
    name = domain()
    with tempfile.NamedTemporaryFile("w", suffix=".in", delete=False, encoding="utf-8") as listing:
        listing.write("\n".join(files) + "\n")
    try:
        subprocess.run(
            ["xgettext", f"--package-name={name}", f"--default-domain={name}",
             *XGETTEXT_ARGS, f"--files-from={listing.name}", f"--directory={ROOT}",
             f"--output={output}"],
            check=True, cwd=ROOT,
            # ".blp: unknown extension, will try C" for every template is noise.
            stderr=subprocess.DEVNULL if "--verbose" not in sys.argv else None)
    finally:
        pathlib.Path(listing.name).unlink()


def _unquote(line):
    return bytes(line.strip()[1:-1], "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")


def messages(path):
    """The set of (context, msgid, plural) in a .pot or .po file."""
    found, entry, key = set(), {}, None

    def flush():
        if entry.get("msgid"):
            found.add((entry.get("msgctxt", ""), entry["msgid"], entry.get("msgid_plural", "")))
        entry.clear()

    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            flush()
            key = None
        elif line.startswith("#"):
            continue
        elif line.startswith('"') and key:
            entry[key] += _unquote(line)
        else:
            word, _, rest = line.partition(" ")
            key = word if word in ("msgctxt", "msgid", "msgid_plural") else None
            if key:
                entry[key] = _unquote(rest)
    flush()
    return found


def check():
    problems = []
    if POTFILES.read_text(encoding="utf-8") != potfiles_text():
        want, have = set(listed_files(potfiles_text())), set(listed_files())
        problems.append("po/POTFILES is out of date (missing: %s; stale: %s)" % (
            ", ".join(sorted(want - have)) or "none", ", ".join(sorted(have - want)) or "none"))
    template = PO_DIR / f"{domain()}.pot"
    if not template.exists():
        problems.append(f"po/{template.name} does not exist")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            fresh = pathlib.Path(tmp) / "fresh.pot"
            extract(listed_files(potfiles_text()), fresh)
            want, have = messages(fresh), messages(template)
        for label, items in (("not in the template", want - have), ("no longer in the tree", have - want)):
            for ctxt, msgid, _plural in sorted(items)[:20]:
                problems.append("%s: %r%s" % (label, msgid, f" (context {ctxt!r})" if ctxt else ""))
            if len(items) > 20:
                problems.append(f"... and {len(items) - 20} more {label}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        print("\nRun: python3 po/update-pot.py", file=sys.stderr)
        return 1
    print(f"po/POTFILES and po/{template.name} match the tree ({len(have)} messages)")
    return 0


def update(merge=True):
    POTFILES.write_text(potfiles_text(), encoding="utf-8")
    template = PO_DIR / f"{domain()}.pot"
    extract(listed_files(), template)
    print(f"wrote po/POTFILES ({len(listed_files())} files) and po/{template.name} "
          f"({len(messages(template))} messages)")
    if not merge:
        return 0
    if shutil.which("msgmerge") is None:
        print("msgmerge not found: the .po files were left as they are", file=sys.stderr)
        return 0
    # Existing translations stay. A message that left the tree is kept as an
    # obsolete entry; a changed one is marked fuzzy for a translator to check.
    for po in sorted(PO_DIR.glob("*.po")):
        subprocess.run(["msgmerge", "--quiet", "--update", "--backup=none", str(po), str(template)],
                       check=True)
    print(f"merged {len(list(PO_DIR.glob('*.po')))} .po files")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when POTFILES or the template is out of date")
    parser.add_argument("--no-merge", action="store_true", help="do not msgmerge the .po files")
    parser.add_argument("--verbose", action="store_true", help="show xgettext's warnings")
    args = parser.parse_args()
    return check() if args.check else update(merge=not args.no_merge)


if __name__ == "__main__":
    sys.exit(main())
