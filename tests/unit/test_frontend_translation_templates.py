"""Each non-GNOME frontend has a translation template that matches its tree (#300).

shared/i18n/templates.py reads the marked strings of KDE and Niri (qsTr, tr),
XFCE (gettext) and COSMIC (`ui::copy`) and writes one template per frontend
in that toolkit's format. These tests fail when a template is stale, and hold
each extractor to the forms it must read.
"""

import importlib.util
import pathlib
import shutil

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("i18n_templates",
                                               ROOT / "shared" / "i18n" / "templates.py")
templates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(templates)


# ── the templates in the tree ───────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(templates.TARGETS))
def test_the_template_is_current(name):
    problem = templates.TARGETS[name].stale()
    assert problem == "", problem + f"\n  run: python3 shared/i18n/templates.py {name}"


@pytest.mark.parametrize("name, msgid", [
    # The examples #300 names: text that had no translation call.
    ("niri", "Your account"),
    ("niri", "Passwords do not match."),
    ("xfce", "What do you want to install?"),
    ("kde", "User Account"),
    ("cosmic", "Select a disk"),
])
def test_the_template_has_the_strings_the_issue_names(name, msgid):
    target = templates.TARGETS[name]
    have = target._parse((target.base / target.template).read_text(encoding="utf-8"))
    # A .ts entry is (context, source, comment, numerus), a .pot entry
    # (msgid, plural), a JSON entry the message id itself.
    def text_of(entry):
        if isinstance(entry, str):
            return entry
        return entry[1] if len(entry) == 4 else entry[0]
    assert msgid in {text_of(entry) for entry in have}


@pytest.mark.parametrize("name, least", [("kde", 100), ("niri", 100), ("xfce", 60),
                                         ("cosmic", 90)])
def test_the_template_is_not_empty(name, least):
    # Guards the guard: an extractor that finds nothing writes a template
    # that is always "current".
    assert len(templates.TARGETS[name]._parse(templates.TARGETS[name].render())) >= least


def test_the_check_fails_on_a_stale_template_and_write_fixes_it(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "frontends" / "niri" / "ui", tmp_path / "niri" / "ui")
    shutil.copytree(ROOT / "frontends" / "niri" / "i18n", tmp_path / "niri" / "i18n")
    monkeypatch.setattr(templates, "FRONTENDS", tmp_path)
    monkeypatch.setattr(templates, "ROOT", tmp_path)
    target = templates.TARGETS["niri"]
    assert target.stale() == ""
    qml = tmp_path / "niri" / "ui" / "installer.qml"
    qml.write_text(qml.read_text().replace('qsTr("Your account")', 'qsTr("Your new account")'))
    problem = target.stale()
    assert "1 messages missing" in problem and "Your new account" in problem
    assert templates.main(["--check", "niri"]) == 1
    assert templates.main(["niri"]) == 0
    assert templates.main(["--check", "niri"]) == 0


def test_a_missing_template_is_stale(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "frontends" / "xfce" / "tuna_installer_xfce",
                    tmp_path / "xfce" / "tuna_installer_xfce")
    monkeypatch.setattr(templates, "FRONTENDS", tmp_path)
    monkeypatch.setattr(templates, "ROOT", tmp_path)
    assert "does not exist" in templates.TARGETS["xfce"].stale()


# ── QML ─────────────────────────────────────────────────────────────────────

def _qml(text, path="ui/Page.qml"):
    return [m.key() for m in templates.extract_qml(pathlib.Path(path), text)]


def test_qml_context_is_the_file_name():
    assert _qml('Label { text: qsTr("Back") }', "modules/x/main.qml") == [
        ("main", "Back", "", False)]


def test_qml_reads_escapes_disambiguation_plurals_and_glued_literals():
    text = ('Label { text: qsTr("Say \\"hi\\"\\u2026") }\n'
            "Label { text: qsTr('One' + \" two\") }\n"
            'Label { text: qsTr("Open", "verb") }\n'
            'Label { text: qsTr("%n disks", "", count) }\n'
            'Label { text: qsTranslate("Other", "Elsewhere") }\n')
    assert _qml(text) == [
        ("Page", 'Say "hi"…', "", False),
        ("Page", "One two", "", False),
        ("Page", "Open", "verb", False),
        ("Page", "%n disks", "", True),
        ("Other", "Elsewhere", "", False),
    ]


def test_qml_skips_comments():
    assert _qml('// text: qsTr("Old")\n/* qsTr("Older") */\nItem {}') == []


@pytest.mark.parametrize("bad", ['qsTr(name)', 'qsTr("Disk " + name)'])
def test_qml_refuses_what_lupdate_cannot_see(bad):
    with pytest.raises(templates.ExtractError):
        _qml(f"Label {{ text: {bad} }}")


# ── C++ ─────────────────────────────────────────────────────────────────────

def _cpp(text, path="src/x.cpp"):
    return [m.key() for m in templates.extract_cpp(pathlib.Path(path), text)]


def test_cpp_tr_takes_the_class_of_the_member_function():
    text = ("namespace { int helper() { return 1; } }\n"
            "void Controller::start()\n{\n"
            "    auto f = [this] { appendLine(tr(\"Starting\")); };\n"
            "    appendLine(tr(\"Two \" \"parts\"));\n}\n"
            "QString Other::name() const { return tr(\"Name\"); }\n")
    assert _cpp(text) == [("Controller", "Starting", "", False),
                          ("Controller", "Two parts", "", False),
                          ("Other", "Name", "", False)]


def test_cpp_reads_explicit_contexts_and_skips_a_tr_of_a_value():
    text = ('static const char *k = QT_TRANSLATE_NOOP("Controller", "Almost ready");\n'
            'void f() { QCoreApplication::translate("probe", "no %1").arg(x); }\n'
            "void Controller::g() { Controller::tr(source); }\n"
            '// tr("commented out")\n')
    assert _cpp(text) == [("Controller", "Almost ready", "", False),
                          ("probe", "no %1", "", False)]


def test_cpp_tr_outside_a_class_is_an_error():
    with pytest.raises(templates.ExtractError):
        _cpp('int main() { return tr("x").size(); }')


def test_ts_round_trips_markup_characters():
    msgs = [templates.Message("C", "Region & <language> \"x\" 'y'"),
            templates.Message("C", "%n items", numerus=True),
            templates.Message("C", "Open", comment="verb")]
    assert templates.parse_ts(templates.render_ts(msgs)) == {m.key() for m in msgs}


# ── Python / gettext ────────────────────────────────────────────────────────

def test_python_reads_gettext_calls():
    text = ('x = _("Back")\n'
            'y = _("Long " "line")\n'
            'z = ngettext("One disk", "{n} disks", n)\n'
            'label = "not marked"\n')
    assert templates.extract_python("m.py", text) == [
        ("Back", ""), ("Long line", ""), ("One disk", "{n} disks")]


def test_python_refuses_a_value():
    with pytest.raises(templates.ExtractError):
        templates.extract_python("m.py", "_(name)")


def test_pot_round_trips_quotes_newlines_and_plurals():
    msgs = [("Say \"hi\"\\", ""), ("Line one\nLine two\n", ""), ("One", "{n} many")]
    text = templates.render_pot(msgs, "domain")
    assert "#, python-brace-format" in text
    assert templates.parse_pot(text) == set(msgs)
    assert "Plural-Forms" in text
    assert "Plural-Forms" not in templates.render_pot([("A", "")], "domain")


# ── Rust / COSMIC ───────────────────────────────────────────────────────────

def test_rust_copy_reads_escapes_and_line_continuations():
    text = ('pub mod copy {\n'
            '    // a comment\n'
            '    pub const A: &str = "Step {n} \\u{b7} {title}";\n'
            '    pub const B: &str =\n'
            '        "Wrapped";\n'
            '    pub const C: &str = "One \\\n'
            '         two";\n'
            '}\n\nuse copy::*;\n')
    assert templates.extract_rust_copy("ui.rs", text) == [
        "Step {n} · {title}", "Wrapped", "One two"]


@pytest.mark.parametrize("const", ['pub const A: &str = concat!("a", "b");',
                                   'pub const A: &str = r"raw";',
                                   'pub const N: usize = 3;'])
def test_rust_copy_refuses_another_form(const):
    with pytest.raises(templates.ExtractError):
        templates.extract_rust_copy("ui.rs", f"pub mod copy {{\n    {const}\n}}\n\nuse copy::*;\n")
