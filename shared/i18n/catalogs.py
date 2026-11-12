#!/usr/bin/env python3
"""Write, or check, the translation catalogs of the non-GNOME frontends (#300).

    python3 shared/i18n/catalogs.py fr             write the French catalog of each frontend
    python3 shared/i18n/catalogs.py fr kde xfce    only these frontends
    python3 shared/i18n/catalogs.py --check        exit 1 when a catalog is out of date

A catalog is a template (templates.py) with translations, in the format of
that frontend's toolkit:

  kde     i18n/tuna-installer-kde_<lang>.ts     compiled to .qm by CMake
  niri    i18n/tuna-installer-niri_<lang>.ts    compiled to .qm by translations/CMakeLists.txt
  xfce    po/<lang>.po                          compiled to .mo by the Flatpak
  cosmic  i18n/<lang>.json                      read as it is by src/i18n.rs

Each message gets, in this order:
  1. the translation the catalog already has (a translator's work is kept);
  2. the translation of the identical msgid in the GNOME frontend's
     po/<lang>.po, when that entry is translated and not fuzzy;
  3. no translation. Nothing is invented: an untranslated message shows the
     English text.

`--check` fails when the messages of a catalog are not the messages of its
template (run the script for that language after the template changes), and
when a translation drops or adds a placeholder.
"""

import argparse
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import templates

ROOT = templates.ROOT
GNOME_PO = ROOT / "po"
LANGUAGE = re.compile(r"^[a-z]{2,3}(?:_[A-Z]{2}|_[A-Z][a-z]{3})?$")


# ── GNOME's po/<lang>.po ────────────────────────────────────────────────────

_PO_UNESCAPE = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unescape(text):
    return re.sub(r"\\(.)", lambda m: _PO_UNESCAPE.get(m.group(1), m.group(1)), text)


def read_po(text):
    """The entries of a .po file: a list of dicts with msgctxt, msgid,
    msgid_plural, msgstr (a list: one item, or one per plural form) and
    fuzzy. The header is the entry whose msgid is "". Obsolete (#~) entries
    are left out."""
    entries, cur, field, flags = [], None, None, set()

    def flush():
        if cur is not None and "msgid" in cur:
            forms = [cur[k] for k in sorted(cur, key=lambda k: int(k[7:-1]) if k.startswith("msgstr[") else -1)
                     if k.startswith("msgstr")]
            entries.append({"msgctxt": cur.get("msgctxt"), "msgid": cur["msgid"],
                            "msgid_plural": cur.get("msgid_plural", ""),
                            "msgstr": forms, "fuzzy": "fuzzy" in cur["flags"]})

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#~"):
            continue
        if not line:
            continue
        if line.startswith("#"):
            if cur is not None and any(k.startswith("msgstr") for k in cur):
                flush()
                cur, field = None, None
            if line.startswith("#,"):
                flags |= {f.strip() for f in line[2:].split(",")}
            continue
        m = re.match(r'^(msgctxt|msgid|msgid_plural|msgstr(?:\[\d+\])?)\s+"(.*)"$', line)
        if m:
            key = m.group(1)
            if key in ("msgctxt", "msgid") and cur is not None and \
                    any(k.startswith("msgstr") for k in cur):
                flush()
                cur = None
            if cur is None:
                cur, flags = {"flags": flags}, set()
            field = key
            cur[field] = _unescape(m.group(2))
        elif line.startswith('"') and line.endswith('"') and cur is not None and field:
            cur[field] += _unescape(line[1:-1])
        else:
            raise templates.ExtractError(f"cannot read the .po line {raw!r}")
    flush()
    return entries


def po_header(entries):
    for e in entries:
        if e["msgid"] == "" and not e["msgctxt"]:
            fields = {}
            for line in (e["msgstr"][0] if e["msgstr"] else "").split("\n"):
                if ":" in line:
                    name, value = line.split(":", 1)
                    fields[name.strip()] = value.strip()
            return fields
    return {}


def gnome_translations(lang):
    """{(msgid, msgid_plural): [forms]} of the translated, not fuzzy, entries
    without a context of po/<lang>.po. Empty when there is no such file."""
    path = GNOME_PO / f"{lang}.po"
    if not path.exists():
        return {}, {}
    entries = read_po(path.read_text(encoding="utf-8"))
    found = {}
    for e in entries:
        if not e["msgid"] or e["msgctxt"] or e["fuzzy"]:
            continue
        if e["msgstr"] and all(e["msgstr"]):
            found[(e["msgid"], e["msgid_plural"])] = e["msgstr"]
    return found, po_header(entries)


# ── placeholders ────────────────────────────────────────────────────────────

_BRACE = re.compile(r"\{\w*\}")
_QT_ARG = re.compile(r"%L?\d+|%n")


def placeholders(text, kind):
    pattern = _QT_ARG if kind == "qt" else _BRACE
    return sorted(pattern.findall(text))


# ── one format each ─────────────────────────────────────────────────────────
#
# Each format has: read(text) -> {key: translation}, where a translation is
# a str (a list of str for a plural); and write(messages, translations, lang,
# header) -> text, where messages are the template's keys in order.

def ts_messages(target):
    return [m for m in templates.unique(target.messages())]


def read_ts(text):
    root = ET.fromstring(text)
    found = {}
    for context in root.iter("context"):
        name = context.findtext("name") or ""
        for msg in context.iter("message"):
            key = (name, msg.findtext("source") or "", msg.findtext("comment") or "",
                   msg.get("numerus") == "yes")
            tr = msg.find("translation")
            if tr is None or tr.get("type") in ("unfinished", "obsolete", "vanished"):
                value = [] if key[3] else ""
            elif key[3]:
                value = [f.text or "" for f in tr.findall("numerusform")]
            else:
                value = tr.text or ""
            found[key] = value
    return found


def ts_language(text):
    return ET.fromstring(text).get("language", "")


def write_ts(messages, translations, lang, _header):
    x = templates._xml
    by_context = {}
    for msg in messages:
        by_context.setdefault(msg.context, []).append(msg)
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<!DOCTYPE TS>",
             f'<TS version="2.1" language="{x(lang)}">']
    for context in sorted(by_context):
        lines += ["<context>", f"    <name>{x(context)}</name>"]
        for msg in by_context[context]:
            value = translations.get(msg.key())
            lines.append('    <message numerus="yes">' if msg.numerus else "    <message>")
            lines.append(f"        <source>{x(msg.source)}</source>")
            if msg.comment:
                lines.append(f"        <comment>{x(msg.comment)}</comment>")
            if msg.numerus:
                forms = value or []
                done = bool(forms) and all(forms)
                lines.append("        <translation>" if done
                             else '        <translation type="unfinished">')
                for form in forms or [""]:
                    lines.append(f"            <numerusform>{x(form)}</numerusform>")
                lines.append("        </translation>")
            elif value:
                lines.append(f"        <translation>{x(value)}</translation>")
            else:
                lines.append('        <translation type="unfinished"></translation>')
            lines.append("    </message>")
        lines.append("</context>")
    lines.append("</TS>")
    return "\n".join(lines) + "\n"


def read_frontend_po(text):
    found = {}
    for e in read_po(text):
        if not e["msgid"]:
            continue
        key = (e["msgid"], e["msgid_plural"])
        if e["fuzzy"] or not e["msgstr"] or not all(e["msgstr"]):
            found[key] = [] if e["msgid_plural"] else ""
        else:
            found[key] = e["msgstr"] if e["msgid_plural"] else e["msgstr"][0]
    return found


def po_language(text):
    return po_header(read_po(text)).get("Language", "")


def write_po(messages, translations, lang, header, domain):
    plural_forms = header.get("Plural-Forms", "nplurals=2; plural=(n != 1);")
    nplurals = int(re.search(r"nplurals\s*=\s*(\d+)", plural_forms).group(1))
    out = [
        f"# {lang} translation of the {domain} gettext domain.",
        "# Written by shared/i18n/catalogs.py; a translator may edit the msgstr lines.",
        f"# The first translations came from the GNOME frontend's po/{lang}.po;",
        "# its translators are credited there.",
        "#",
        'msgid ""',
        'msgstr ""',
        f'"Project-Id-Version: {domain}\\n"',
        # The date of the GNOME translations; the translators are credited there.
        f'"PO-Revision-Date: {header.get("PO-Revision-Date", "2026-11-12 00:00+0000")}\\n"',
        '"Last-Translator: none\\n"',
        '"Language-Team: none\\n"',
        f'"Language: {lang}\\n"',
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        f'"Plural-Forms: {plural_forms}\\n"',
        "",
    ]
    seen = set()
    for msgid, plural in messages:
        if msgid in seen:
            continue
        seen.add(msgid)
        value = translations.get((msgid, plural))
        if re.search(r"\{\w*\}", msgid + plural):
            out.append("#, python-brace-format")
        out.append("msgid " + templates._po_string(msgid))
        if plural:
            out.append("msgid_plural " + templates._po_string(plural))
            forms = value if value and len(value) == nplurals else [""] * nplurals
            out += [f"msgstr[{i}] " + templates._po_string(f) for i, f in enumerate(forms)]
        else:
            out.append("msgstr " + templates._po_string(value or ""))
        out.append("")
    return "\n".join(out)


def read_json(text):
    data = json.loads(text)
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise templates.ExtractError("a COSMIC catalog is one object of strings")
    return data


def write_json(messages, translations, _lang, _header):
    data = {msgid: translations.get(msgid) or "" for msgid in sorted(set(messages))}
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


class Catalogs:
    def __init__(self, name, path, kind, messages, read, write, language, gnome_key):
        self.name, self.path, self.kind = name, path, kind
        self._messages, self.read, self._write = messages, read, write
        self.language, self._gnome_key = language, gnome_key

    @property
    def target(self):
        return templates.TARGETS[self.name]

    def file(self, lang):
        return self.target.base / self.path.format(lang=lang)

    def languages(self):
        """The languages that have a catalog in the tree."""
        pattern = re.compile("^" + re.escape(self.path).replace(r"\{lang\}", "(.+)") + "$")
        found = []
        for path in self.target.base.glob(self.path.format(lang="*")):
            m = pattern.match(str(path.relative_to(self.target.base)))
            if m and LANGUAGE.match(m.group(1)):
                found.append(m.group(1))
        return sorted(found)

    def messages(self):
        return self._messages(self.target)

    def key(self, message):
        return message.key() if self.kind == "qt" else message

    def build(self, lang):
        """The text of the catalog for `lang`: what it has, then GNOME's."""
        path = self.file(lang)
        have = self.read(path.read_text(encoding="utf-8")) if path.exists() else {}
        gnome, header = gnome_translations(lang)
        translations = {}
        for message in self.messages():
            key = self.key(message)
            if have.get(key):
                translations[key] = have[key]
                continue
            found = gnome.get(self._gnome_key(message))
            if found:
                translations[key] = found if self._plural(message) else found[0]
        return self._write(self.messages(), translations, lang, header)

    def _plural(self, message):
        if self.kind == "qt":
            return message.numerus
        return self.kind == "po" and bool(message[1])

    def write(self, lang):
        path = self.file(lang)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.build(lang), encoding="utf-8")
        return path

    def problems(self, lang):
        """Why the catalog for `lang` is out of date: a list, empty when current."""
        path = self.file(lang)
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        found = []
        if self.language and self.language(text) != lang:
            found.append(f"{rel}: the file says its language is "
                         f"{self.language(text)!r}, its name says {lang!r}")
        have = self.read(text)
        want = {self.key(m) for m in self.messages()}
        if set(have) != want:
            missing = sorted(want - set(have), key=str)[:5]
            extra = sorted(set(have) - want, key=str)[:5]
            found.append(f"{rel}: {len(want - set(have))} messages missing {missing}, "
                         f"{len(set(have) - want)} no longer in the template {extra}")
        for key, value in have.items():
            source = key[1] if self.kind == "qt" else (key[0] if self.kind == "po" else key)
            for form in (value if isinstance(value, list) else [value]):
                if form and placeholders(form, self.kind) != placeholders(source, self.kind) \
                        and not (self.kind == "qt" and "%n" in source):
                    found.append(f"{rel}: the translation of {source!r} has the "
                                 f"placeholders {placeholders(form, self.kind)}, "
                                 f"the message {placeholders(source, self.kind)}")
        return found


CATALOGS = {
    "kde": Catalogs("kde", "i18n/tuna-installer-kde_{lang}.ts", "qt", ts_messages,
                    read_ts, write_ts, ts_language, lambda m: (m.source, "")),
    "niri": Catalogs("niri", "i18n/tuna-installer-niri_{lang}.ts", "qt", ts_messages,
                     read_ts, write_ts, ts_language, lambda m: (m.source, "")),
    "xfce": Catalogs("xfce", "po/{lang}.po", "po",
                     lambda t: list(dict.fromkeys(t.messages())), read_frontend_po,
                     lambda m, t, lang, h: write_po(m, t, lang, h, "tuna-installer-xfce"),
                     po_language, lambda m: m),
    "cosmic": Catalogs("cosmic", "i18n/{lang}.json", "brace",
                       lambda t: sorted(set(t.messages())), read_json, write_json,
                       None, lambda m: (m, "")),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 when a catalog is out of date; write nothing")
    parser.add_argument("names", nargs="*", metavar="LANG|FRONTEND",
                        help="a language (fr, pt_BR) to write, and any of: " + ", ".join(CATALOGS))
    args = parser.parse_args(argv)
    langs = [n for n in args.names if n not in CATALOGS]
    names = [n for n in args.names if n in CATALOGS] or list(CATALOGS)
    bad = [n for n in langs if not LANGUAGE.match(n)]
    if bad:
        parser.error(f"not a language or a frontend: {', '.join(bad)}")
    if args.check and langs:
        parser.error("--check reads every catalog in the tree; name no language")
    if not args.check and not langs:
        parser.error("name the language to write, e.g. fr")
    failed = False
    for name in names:
        catalogs = CATALOGS[name]
        try:
            if args.check:
                for lang in catalogs.languages():
                    problems = catalogs.problems(lang)
                    for problem in problems:
                        print(f"{name}: {problem}\n  run: python3 shared/i18n/catalogs.py "
                              f"{lang} {name}", file=sys.stderr)
                    failed = failed or bool(problems)
                    if not problems:
                        print(f"{name}: {catalogs.path.format(lang=lang)} is current")
            else:
                for lang in langs:
                    path = catalogs.write(lang)
                    print(f"{name}: wrote {path.relative_to(ROOT)}")
        except templates.ExtractError as e:
            failed = True
            print(f"{name}: {e}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
