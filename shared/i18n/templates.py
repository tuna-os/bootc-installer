#!/usr/bin/env python3
"""Write, or check, the translation template of each non-GNOME frontend (#300).

    python3 shared/i18n/templates.py            write every template
    python3 shared/i18n/templates.py --check    exit 1 when one is out of date
    python3 shared/i18n/templates.py kde xfce   only these frontends

Each frontend marks its text in its own toolkit's way, and each template is
in that toolkit's own format:

  kde     qsTr() in QML, tr() and friends in C++   i18n/tuna-installer-kde.ts
  niri    qsTr() in QML                           i18n/tuna-installer-niri.ts
  xfce    _() and ngettext() of gettext           po/tuna-installer-xfce.pot
  cosmic  the message ids of `ui::copy`           i18n/template.json

GNOME has its own template and check: po/update-pot.py.

This script needs only Python. It reads the sources itself, so the check runs
in the plain unit job and gives the same answer on every machine. The check
compares messages, not bytes: a template that lupdate or xgettext wrote
passes when it holds the same messages.

The extractors read the forms the frontends use. A form they do not know (a
qsTr() whose first argument is not a string literal, a Rust constant that is
not a plain string literal) is an error, not a message that goes missing.
"""

import argparse
import ast
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTENDS = ROOT / "frontends"


class ExtractError(Exception):
    """A marked string the extractor cannot read."""


# ── string literals ─────────────────────────────────────────────────────────

_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\",
                   '"': '"', "'": "'", "b": "\b", "f": "\f", "v": "\v"}


def read_c_literal(text, pos, quote='"', where=""):
    """The value of the C, C++, JavaScript or QML string literal that opens at
    text[pos], and the index after its closing quote."""
    assert text[pos] == quote
    out, i = [], pos + 1
    while i < len(text):
        c = text[i]
        if c == quote:
            return "".join(out), i + 1
        if c == "\n":
            raise ExtractError(f"{where}: a string literal runs past the end of the line")
        if c != "\\":
            out.append(c)
            i += 1
            continue
        e = text[i + 1:i + 2]
        if e in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[e])
            i += 2
        elif e == "u" and text[i + 2:i + 3] == "{":
            end = text.index("}", i)
            out.append(chr(int(text[i + 3:end], 16)))
            i = end + 1
        elif e == "u":
            out.append(chr(int(text[i + 2:i + 6], 16)))
            i += 6
        elif e == "x":
            m = re.match(r"[0-9a-fA-F]{1,2}", text[i + 2:])
            out.append(chr(int(m.group(0), 16)))
            i += 2 + len(m.group(0))
        elif e == "\n":
            i += 2
        else:
            raise ExtractError(f"{where}: unknown escape \\{e}")
    raise ExtractError(f"{where}: unterminated string literal")


def read_rust_literal(text, pos, where=""):
    """The value of the Rust string literal at text[pos], and the index after
    it. A backslash at the end of a line drops the line break and the
    leading white space of the next line, as rustc does."""
    if text[pos] != '"':
        raise ExtractError(f"{where}: not a plain string literal")
    out, i = [], pos + 1
    while i < len(text):
        c = text[i]
        if c == '"':
            return "".join(out), i + 1
        if c != "\\":
            out.append(c)
            i += 1
            continue
        e = text[i + 1]
        if e == "\n":
            i += 2
            while i < len(text) and text[i] in " \t\r\n":
                i += 1
        elif e == "u":
            if text[i + 2] != "{":
                raise ExtractError(f"{where}: \\u without braces")
            end = text.index("}", i)
            out.append(chr(int(text[i + 3:end], 16)))
            i = end + 1
        elif e == "x":
            out.append(chr(int(text[i + 2:i + 4], 16)))
            i += 4
        elif e in "nrt0\\\"'":
            out.append(_SIMPLE_ESCAPES[e])
            i += 2
        else:
            raise ExtractError(f"{where}: unknown escape \\{e}")
    raise ExtractError(f"{where}: unterminated string literal")


def _skip_space(text, i):
    while i < len(text):
        if text[i] in " \t\r\n":
            i += 1
        elif text.startswith("//", i):
            i = text.find("\n", i)
            i = len(text) if i < 0 else i
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
        else:
            break
    return i


def _read_concatenated(text, i, where, plus):
    """One string argument: literals glued by `+` (JavaScript) or side by
    side (C++). None when the argument is not a literal."""
    i = _skip_space(text, i)
    if i >= len(text) or text[i] not in "\"'":
        return None, i
    parts = []
    while True:
        value, i = read_c_literal(text, i, text[i], where)
        parts.append(value)
        j = _skip_space(text, i)
        if plus and text.startswith("+", j):
            k = _skip_space(text, j + 1)
            if k < len(text) and text[k] in "\"'":
                i = k
                continue
            raise ExtractError(f"{where}: a translated string is glued to a value; "
                               "use a placeholder (%1) and .arg()")
        if not plus and j < len(text) and text[j] == '"':
            i = j
            continue
        return "".join(parts), j


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def _strip_comments(text):
    """`text` with each comment replaced by blanks of the same length, so the
    positions stay. String literals are left alone."""
    out, i, n = list(text), 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out[i:j] = " " * (j - i)
            i = j
        elif text.startswith("/*", i):
            j = text.index("*/", i) + 2
            out[i:j] = [ch if ch == "\n" else " " for ch in text[i:j]]
            i = j
        else:
            i += 1
    return "".join(out)


# ── Qt: QML and C++ to a .ts file ───────────────────────────────────────────

class Message:
    __slots__ = ("context", "source", "comment", "numerus")

    def __init__(self, context, source, comment="", numerus=False):
        self.context, self.source = context, source
        self.comment, self.numerus = comment, numerus

    def key(self):
        return (self.context, self.source, self.comment, self.numerus)


def _call_args(text, i, where, plus):
    """The arguments of a translation call whose `(` is at text[i]: a list
    of strings (None for an argument that is not a literal) and a count of
    the arguments."""
    args = []
    i += 1
    while True:
        value, i = _read_concatenated(text, i, where, plus)
        args.append(value)
        # Skip the rest of a non-literal argument.
        depth = 0
        while i < len(text):
            c = text[i]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 0:
                break
            elif c in "\"'":
                _, i = read_c_literal(text, i, c, where)
                continue
            i += 1
        if i >= len(text) or text[i] == ")":
            return args
        i += 1


_QML_CALL = re.compile(r"\b(qsTr|qsTranslate|QT_TR_NOOP|QT_TRANSLATE_NOOP)\s*\(")


def extract_qml(path, text):
    """The messages of one QML file. qsTr()'s context is the file name
    without `.qml`, as lupdate and the QML engine both take it."""
    context = pathlib.Path(path).stem
    text = _strip_comments(text)
    found = []
    for m in _QML_CALL.finditer(text):
        where = f"{path}:{_line(text, m.start())}"
        args = _call_args(text, m.end() - 1, where, plus=True)
        if m.group(1) in ("qsTr", "QT_TR_NOOP"):
            ctx, rest = context, args
        else:
            if args[0] is None:
                raise ExtractError(f"{where}: {m.group(1)}() needs a literal context")
            ctx, rest = args[0], args[1:]
        if not rest or rest[0] is None:
            raise ExtractError(f"{where}: {m.group(1)}() of a value; lupdate cannot see it")
        comment = rest[1] if len(rest) > 1 and rest[1] else ""
        found.append(Message(ctx, rest[0], comment, numerus=len(rest) > 2))
    return found


_CPP_CALL = re.compile(
    r"(?:\b(\w+)::)?\b(tr|translate|QT_TR_NOOP|QT_TRANSLATE_NOOP|QT_TRANSLATE_NOOP3)\s*\(")
_CPP_MEMBER = re.compile(r"^[A-Za-z_][\w:<>,*& ]*?\b(\w+)::~?\w+\s*\(", re.M)
_CPP_CLASS = re.compile(r"\b(?:class|struct)\s+(\w+)[^;{]*\{")


def extract_cpp(path, text):
    """The messages of one C++ file. A bare tr() takes the class of the
    member function it is in (an out-of-line `Class::method(` definition
    at the start of a line, or the class a header declares it in)."""
    text = _strip_comments(text)
    members = [(m.start(), m.group(1)) for m in _CPP_MEMBER.finditer(text)]
    classes = [(m.start(), m.group(1)) for m in _CPP_CLASS.finditer(text)]
    found = []
    for m in _CPP_CALL.finditer(text):
        scope, name = m.group(1), m.group(2)
        if name == "translate" and scope not in ("QCoreApplication", "QApplication",
                                                 "QGuiApplication"):
            continue
        where = f"{path}:{_line(text, m.start())}"
        args = _call_args(text, m.end() - 1, where, plus=False)
        if name in ("translate", "QT_TRANSLATE_NOOP", "QT_TRANSLATE_NOOP3"):
            if args[0] is None:
                raise ExtractError(f"{where}: {name}() needs a literal context")
            ctx, rest = args[0], args[1:]
        else:
            ctx, rest = scope, args
            if not ctx:
                before = [c for pos, c in members if pos < m.start()] or \
                         [c for pos, c in classes if pos < m.start()]
                if not before:
                    raise ExtractError(f"{where}: tr() outside a class")
                ctx = before[-1]
        if not rest or rest[0] is None:
            if name == "tr" and scope:
                continue  # Class::tr(variable): the string is marked where it is defined.
            raise ExtractError(f"{where}: {name}() of a value; lupdate cannot see it")
        comment = rest[1] if len(rest) > 1 and rest[1] else ""
        numerus = name == "tr" and len(rest) > 2
        found.append(Message(ctx, rest[0], comment, numerus))
    return found


def _xml(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def unique(messages):
    seen, out = set(), []
    for msg in messages:
        if msg.key() not in seen:
            seen.add(msg.key())
            out.append(msg)
    return out


def render_ts(messages):
    """A Qt Linguist template: every translation unfinished and empty."""
    by_context = {}
    for msg in unique(messages):
        by_context.setdefault(msg.context, []).append(msg)
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<!DOCTYPE TS>", '<TS version="2.1">']
    for context in sorted(by_context):
        lines += ["<context>", f"    <name>{_xml(context)}</name>"]
        for msg in by_context[context]:
            lines.append('    <message numerus="yes">' if msg.numerus else "    <message>")
            lines.append(f"        <source>{_xml(msg.source)}</source>")
            if msg.comment:
                lines.append(f"        <comment>{_xml(msg.comment)}</comment>")
            if msg.numerus:
                lines += ['        <translation type="unfinished">',
                          "            <numerusform></numerusform>",
                          "        </translation>"]
            else:
                lines.append('        <translation type="unfinished"></translation>')
            lines.append("    </message>")
        lines.append("</context>")
    lines.append("</TS>")
    return "\n".join(lines) + "\n"


def parse_ts(text):
    root = ET.fromstring(text)
    found = set()
    for context in root.iter("context"):
        name = context.findtext("name") or ""
        for msg in context.iter("message"):
            found.add((name, msg.findtext("source") or "", msg.findtext("comment") or "",
                       msg.get("numerus") == "yes"))
    return found


# ── gettext: Python to a .pot file ──────────────────────────────────────────

def extract_python(path, text):
    """(msgid, msgid_plural) for each _() and ngettext() call of a module.
    An argument that is not a literal is an error: xgettext would skip it."""
    found = []
    for node in ast.walk(ast.parse(text, str(path))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else "")
        if name not in ("_", "ngettext", "N_"):
            continue
        want = 2 if name == "ngettext" else 1
        args = node.args[:want]
        if len(args) < want or not all(
                isinstance(a, ast.Constant) and isinstance(a.value, str) for a in args):
            raise ExtractError(f"{path}:{node.lineno}: {name}() of a value; "
                               "gettext cannot see it")
        found.append((args[0].value, args[1].value if want == 2 else ""))
    return found


def _po_string(text):
    escaped = (text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
               .replace("\r", "\\r"))
    if "\n" not in text.rstrip("\n") or text == "\n":
        return '"' + escaped.replace("\n", "\\n") + '"'
    # A message of several lines: one PO line per line, as xgettext writes it.
    parts = escaped.split("\n")
    lines = ['""'] + ['"' + p + '\\n"' for p in parts[:-1]]
    if parts[-1]:
        lines.append('"' + parts[-1] + '"')
    return "\n".join(lines)


def render_pot(messages, domain):
    out = [
        f"# Translation template of the {domain} gettext domain.",
        "# Written by shared/i18n/templates.py. Do not edit by hand.",
        "#",
        "#, fuzzy",
        'msgid ""',
        'msgstr ""',
        f'"Project-Id-Version: {domain}\\n"',
        '"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"',
        '"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"',
        '"Language-Team: LANGUAGE <LL@li.org>\\n"',
        '"Language: \\n"',
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
    ]
    if any(plural for _msgid, plural in messages):
        out.append('"Plural-Forms: nplurals=INTEGER; plural=EXPRESSION;\\n"')
    out.append("")
    seen = set()
    for msgid, plural in messages:
        if msgid in seen:
            continue
        seen.add(msgid)
        if re.search(r"\{\w*\}", msgid + plural):
            out.append("#, python-brace-format")
        out.append("msgid " + _po_string(msgid))
        if plural:
            out += ["msgid_plural " + _po_string(plural), 'msgstr[0] ""', 'msgstr[1] ""']
        else:
            out.append('msgstr ""')
        out.append("")
    return "\n".join(out)


_PO_UNESCAPE = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def parse_pot(text):
    """{(msgid, msgid_plural)} of a .pot file, header left out."""
    found, current, field = set(), {}, None

    def flush():
        if current.get("msgid"):
            found.add((current["msgid"], current.get("msgid_plural", "")))

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^(msgid|msgid_plural|msgstr(?:\[\d+\])?)\s+"(.*)"$', line)
        if m:
            if m.group(1) == "msgid":
                flush()
                current = {}
            field, value = m.group(1), m.group(2)
        elif line.startswith('"') and line.endswith('"') and field:
            value = current.get(field, "") + line[1:-1]
            current[field] = value
            continue
        else:
            raise ExtractError(f"cannot read the .pot line {raw!r}")
        current[field] = value
    flush()
    return {(re.sub(r"\\(.)", lambda m: _PO_UNESCAPE.get(m.group(1), m.group(1)), a),
             re.sub(r"\\(.)", lambda m: _PO_UNESCAPE.get(m.group(1), m.group(1)), b))
            for a, b in found}


# ── COSMIC: the `ui::copy` message ids to a JSON template ───────────────────

_RUST_CONST = re.compile(r"\bpub const ([A-Z][A-Z0-9_]*): &str =\s*")


def extract_rust_copy(path, text):
    """The value of each `pub const NAME: &str = "...";` of `pub mod copy`."""
    start = text.find("pub mod copy {")
    end = text.find("\nuse copy::*;", start)
    if start < 0 or end < 0:
        raise ExtractError(f"{path}: no `pub mod copy {{ ... }}` followed by `use copy::*;`")
    module = text[start:end]
    found = []
    for m in _RUST_CONST.finditer(module):
        where = f"{path}:{_line(text, start + m.start())} {m.group(1)}"
        value, i = read_rust_literal(module, m.end(), where)
        if not module[i:].lstrip().startswith(";"):
            raise ExtractError(f"{where}: the value is more than one string literal")
        found.append(value)
    if len(found) != module.count("pub const "):
        raise ExtractError(f"{path}: a `pub const` in mod copy is not a &str literal")
    return found


def render_json_template(messages):
    template = {msgid: "" for msgid in sorted(set(messages))}
    return json.dumps(template, ensure_ascii=False, indent=2) + "\n"


def parse_json_template(text):
    return set(json.loads(text))


# ── the frontends ───────────────────────────────────────────────────────────

class Target:
    def __init__(self, name, template, globs, extract, render, parse, exclude=()):
        self.name, self.template, self.globs = name, template, globs
        self.exclude = exclude
        self._extract, self._render, self._parse = extract, render, parse

    @property
    def base(self):
        return FRONTENDS / self.name

    def sources(self):
        files = set()
        for pattern in self.globs:
            files.update(p for p in self.base.glob(pattern)
                         if p.is_file() and str(p.relative_to(self.base)) not in self.exclude)
        return sorted(files)

    def messages(self):
        found = []
        for path in self.sources():
            rel = path.relative_to(ROOT)
            found += self._extract(rel, path.read_text(encoding="utf-8"))
        return found

    def render(self):
        return self._render(self.messages())

    def stale(self):
        """Why the template on disk is out of date, or "" when it is current."""
        path = self.base / self.template
        if not path.exists():
            return f"{path.relative_to(ROOT)} does not exist"
        want = self._parse(self.render())
        have = self._parse(path.read_text(encoding="utf-8"))
        if want == have:
            return ""
        missing = sorted(want - have, key=str)[:5]
        extra = sorted(have - want, key=str)[:5]
        return (f"{path.relative_to(ROOT)}: {len(want - have)} messages missing "
                f"{missing}, {len(have - want)} no longer in the sources {extra}")

    def write(self):
        path = self.base / self.template
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8")
        return path


def _qt_extract(path, text):
    return extract_qml(path, text) if path.suffix == ".qml" else extract_cpp(path, text)


TARGETS = {
    "kde": Target("kde", "i18n/tuna-installer-kde.ts",
                  ("modules/**/*.qml", "src/**/*.qml", "src/**/*.cpp", "src/**/*.h"),
                  _qt_extract, render_ts, parse_ts),
    "niri": Target("niri", "i18n/tuna-installer-niri.ts", ("ui/*.qml",),
                   _qt_extract, render_ts, parse_ts),
    "xfce": Target("xfce", "po/tuna-installer-xfce.pot", ("tuna_installer_xfce/*.py",),
                   extract_python, lambda m: render_pot(m, "tuna-installer-xfce"), parse_pot,
                   # It defines _() and ngettext(); it marks nothing.
                   exclude=("tuna_installer_xfce/i18n.py",)),
    "cosmic": Target("cosmic", "i18n/template.json", ("src/ui.rs",),
                     extract_rust_copy, render_json_template, parse_json_template),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 when a template is out of date; write nothing")
    parser.add_argument("frontends", nargs="*", metavar="FRONTEND",
                        help="any of: " + ", ".join(TARGETS))
    args = parser.parse_args(argv)
    unknown = [n for n in args.frontends if n not in TARGETS]
    if unknown:
        parser.error(f"unknown frontend {', '.join(unknown)}; pick from {', '.join(TARGETS)}")
    names = args.frontends or list(TARGETS)
    failed = False
    for name in names:
        target = TARGETS[name]
        try:
            if args.check:
                problem = target.stale()
                if problem:
                    failed = True
                    print(f"{name}: {problem}\n  run: python3 shared/i18n/templates.py {name}",
                          file=sys.stderr)
                else:
                    count = len(target._parse(target.render()))
                    print(f"{name}: {target.template} is current ({count} messages)")
            else:
                path = target.write()
                print(f"{name}: wrote {path.relative_to(ROOT)}")
        except ExtractError as e:
            failed = True
            print(f"{name}: {e}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
