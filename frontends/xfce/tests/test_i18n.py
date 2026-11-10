"""Every user-facing literal goes through gettext (#300).

This frontend had one translatable string. The scan below reads the UI
modules as syntax trees and fails on a string literal that a person would
read and that is not the argument of `_()`:

  * a literal that starts like a label ("Back", "Hostname") or holds two
    words ("this live system"), anywhere in a UI module, unless it is in a
    place a person never reads (a log line, an exception, print);
  * a literal passed as a label, title, text or tooltip;
  * an f-string with words in it: gettext needs the template, so those are
    `_("... {x} ...").format(x=...)`.

It also fails when a module that imports `_` reuses the name for a
parameter or a variable, which would hide the function.
"""

import ast
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import i18n  # noqa: E402

PACKAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tuna_installer_xfce")

# The modules that build what a person sees.
UI_MODULES = ("app.py", "pages.py", "gates.py", "tour.py", "logo.py", "trawlline.py")

# A literal a person would read: it starts like a label, or has two words.
LABEL = re.compile(r"^\s*[A-Z][a-z]")
TWO_WORDS = re.compile(r"[A-Za-z]{2,}[,.:;]? [A-Za-z]{2,}")

# Keyword arguments and methods that put a string on the screen.
TEXT_KEYWORDS = {"label", "title", "text", "placeholder_text", "tooltip_text",
                 "secondary_text", "subtitle"}
TEXT_METHODS = {"set_text", "set_label", "set_markup", "set_title", "set_placeholder_text",
                "set_tooltip_text", "set_icon_tooltip_text", "append_text", "add_button"}

# Calls whose strings are for a log, a developer or the toolkit, not a reader.
NOT_SHOWN = {"print", "write", "require_version", "exit", "getattr", "hasattr",
             "get", "environ", "add_class", "remove_class", "has_class",
             "connect", "FontDescription", "StageError", "ValueError"}


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _docstrings(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)):
                found.add(id(body[0].value))
    return found


def _parents(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _enclosing_calls(node, parents):
    """The names of the calls `node` is an argument of, innermost first."""
    names = []
    while id(node) in parents:
        node = parents[id(node)]
        if isinstance(node, ast.Call):
            names.append(_call_name(node))
        if isinstance(node, ast.Raise):
            names.append("raise")
    return names


def _in_text_position(node, parents):
    """Whether `node` is handed straight to a label, title or text."""
    parent = parents.get(id(node))
    if isinstance(parent, ast.keyword) and parent.arg in TEXT_KEYWORDS:
        return True
    if isinstance(parent, ast.Call) and node in parent.args:
        return _call_name(parent) in TEXT_METHODS
    if isinstance(parent, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "title"
            for target in parent.targets):
        return True
    return False


def bare_literals(source):
    """(line, text) for each literal of `source` a person would read that is
    not the argument of `_()`."""
    tree = ast.parse(source)
    docstrings, parents = _docstrings(tree), _parents(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(part.value for part in node.values
                           if isinstance(part, ast.Constant) and isinstance(part.value, str))
            calls = _enclosing_calls(node, parents)
            if (LABEL.search(text) or TWO_WORDS.search(text)) and not (
                    set(calls) & (NOT_SHOWN | {"raise"})):
                found.append((node.lineno, "f-string: " + text))
            continue
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings or isinstance(parents.get(id(node)), ast.JoinedStr):
            continue
        text = node.value
        calls = _enclosing_calls(node, parents)
        if calls[:1] == ["_"]:
            continue
        reads_like_text = bool(LABEL.search(text) or TWO_WORDS.search(text))
        if _in_text_position(node, parents) and re.search(r"[A-Za-z]{2,}", text):
            found.append((node.lineno, text))
        elif reads_like_text and not (set(calls) & (NOT_SHOWN | {"raise"})):
            found.append((node.lineno, text))
    return sorted(found)


def rebinds_underscore(source):
    """Lines where `_` is a parameter or an assignment target."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.arg) and node.arg == "_":
            lines.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id == "_" and isinstance(node.ctx, ast.Store):
            lines.append(node.lineno)
    return lines


def _read(name):
    with open(os.path.join(PACKAGE, name), encoding="utf-8") as stream:
        return stream.read()


def test_no_bare_string_literal_reaches_the_screen():
    problems = []
    for name in UI_MODULES:
        for line, text in bare_literals(_read(name)):
            problems.append(f"{name}:{line}: {text!r}")
    assert problems == [], (
        "wrap these in _() from tuna_installer_xfce.i18n "
        "(a sentence with a value is _('... {x}').format(x=...)):\n  "
        + "\n  ".join(problems))


def test_no_module_hides_the_translation_function():
    problems = []
    for name in sorted(os.listdir(PACKAGE)):
        if not name.endswith(".py"):
            continue
        source = _read(name)
        if not re.search(r"^from \.i18n import .*\b_\b|^from tuna_installer_xfce\.i18n import",
                         source, re.M):
            continue
        problems += [f"{name}:{line}" for line in rebinds_underscore(source)]
    assert problems == [], "`_` is rebound here, which hides gettext: " + ", ".join(problems)


def test_every_ui_module_with_text_imports_the_function():
    for name in ("app.py", "pages.py", "gates.py", "tour.py"):
        assert re.search(r"^from \.i18n import _\b", _read(name), re.M), name


# ─── the scan itself ────────────────────────────────────────────────────────

def test_the_scan_finds_a_bare_label_title_and_text():
    source = (
        "class P:\n"
        "    title = 'Disk encryption'\n"
        "    def build(self):\n"
        "        Gtk.Button(label='Back')\n"
        "        self.body.set_text('Nothing is written yet.')\n"
        "        rows = [('Hostname', 1)]\n"
        "        self.x.set_text(f'Everything on {disk} will be erased.')\n"
        "        Gtk.Label(label='ok')\n"
    )
    assert [line for line, _text in bare_literals(source)] == [2, 4, 5, 6, 7, 8]


def test_the_scan_accepts_wrapped_text_and_what_nobody_reads():
    source = (
        "'''Module docstring With Words.'''\n"
        "class P:\n"
        "    title = _('Disk encryption')\n"
        "    def build(self):\n"
        "        '''Docstring With Words.'''\n"
        "        Gtk.Button(label=_('Back'))\n"
        "        self.x.set_text(_('Everything on {disk} will be erased.').format(disk=d))\n"
        "        gi.require_version('Gtk', '3.0')\n"
        "        print(f'Failed to read {path}')\n"
        "        log.write('=== install started ===')\n"
        "        raise ValueError('Not a recipe')\n"
        "        box.get_style_context().add_class('dim-label')\n"
        "        Gtk.Image.new_from_icon_name('dialog-warning', 1)\n"
        "        self.pager.set_text('<')\n"
    )
    assert bare_literals(source) == []


def test_the_scan_sees_the_real_modules():
    wrapped = 0
    for name in UI_MODULES:
        for node in ast.walk(ast.parse(_read(name))):
            if isinstance(node, ast.Call) and _call_name(node) == "_":
                wrapped += 1
    assert wrapped > 60, f"only {wrapped} strings are marked for translation"


def test_rebinding_is_found():
    assert rebinds_underscore("def f(*_):\n    pass\n") == [1]
    assert rebinds_underscore("_, x = pair\n") == [1]
    assert rebinds_underscore("lambda *_args: _('x')\n") == []


# ─── gettext is real ────────────────────────────────────────────────────────

def test_without_a_catalog_the_text_is_unchanged():
    assert i18n._("Back") == "Back"
    assert i18n.DOMAIN == "tuna-installer-xfce"


def test_a_compiled_catalog_is_used(tmp_path):
    """Build a .mo by hand (no msgfmt needed) and read it in a new process."""
    import struct

    def mo(messages):
        keys = sorted(messages)
        ids = b"".join(key.encode() + b"\0" for key in keys)
        strs = b"".join(messages[key].encode() + b"\0" for key in keys)
        count = len(keys)
        table = 28
        ids_at = table + count * 16
        strs_at = ids_at + len(ids)
        out = struct.pack("<Iiiiiii", 0x950412DE, 0, count, table, table + count * 8, 0, 0)
        offset, rows = 0, b""
        for key in keys:
            rows += struct.pack("<ii", len(key.encode()), ids_at + offset)
            offset += len(key.encode()) + 1
        offset = 0
        for key in keys:
            value = messages[key].encode()
            rows += struct.pack("<ii", len(value), strs_at + offset)
            offset += len(value) + 1
        return out + rows + ids + strs

    folder = tmp_path / "de" / "LC_MESSAGES"
    folder.mkdir(parents=True)
    (folder / (i18n.DOMAIN + ".mo")).write_bytes(mo({
        "": "Content-Type: text/plain; charset=UTF-8\n", "Back": "Zur\u00fcck"}))
    env = dict(os.environ, TUNA_INSTALLER_LOCALEDIR=str(tmp_path), LANGUAGE="de",
               PYTHONPATH=os.path.dirname(PACKAGE))
    out = subprocess.run(
        [sys.executable, "-c",
         "from tuna_installer_xfce.i18n import _; print(_('Back')); print(_('Next'))"],
        env=env, capture_output=True, text=True, check=True)
    assert out.stdout.splitlines() == ["Zur\u00fcck", "Next"]
