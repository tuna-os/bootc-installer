# Translation templates of the frontends

Each frontend marks the text that a person reads in the way of its own
toolkit. Each frontend has a translation template in the format of that
toolkit. `templates.py` writes the templates of KDE, Niri, XFCE and COSMIC
from the sources, and its `--check` fails when a template is out of date.
GNOME has its own script, `po/update-pot.py`.

| Frontend | How a string is marked | Template | Lint for a bare string |
|---|---|---|---|
| GNOME | `_()` (Python, Blueprint) | `po/bootc-installer.pot` | `tests/unit/test_i18n.py` |
| KDE | `qsTr()` (QML), `tr()` and `QCoreApplication::translate()` (C++) | `frontends/kde/i18n/tuna-installer-kde.ts` | `qmlStringsGoThroughQsTr` in `test_backend` |
| Niri | `qsTr()` (QML) | `frontends/niri/i18n/tuna-installer-niri.ts` | `installer/i18n_test.go` |
| XFCE | `_()` and `ngettext()` (gettext) | `frontends/xfce/po/tuna-installer-xfce.pot` | `tests/test_i18n.py` |
| COSMIC | a constant of `ui::copy` that goes through `i18n::tr` | `frontends/cosmic/i18n/template.json` | `no_widget_takes_a_bare_string` in `ui.rs` |

## Commands

```bash
python3 shared/i18n/templates.py            # write every template
python3 shared/i18n/templates.py kde        # write one template
python3 shared/i18n/templates.py --check    # exit 1 when a template is out of date
```

Run the script after you add, change or remove a marked string, and commit
the template with the change. `tests/unit/test_frontend_translation_templates.py`
runs the check in the unit job of `python-test.yml`.

## What the script reads

The script needs only Python. It reads the sources itself, and gives the
same result on each machine. The check compares messages, not bytes. Thus a
template from `lupdate` or `xgettext` also passes when it has the same
messages. The message lists agree with `lupdate` 6.8 (KDE and Niri) and with
`xgettext` (XFCE).

- QML: the context of `qsTr()` is the file name without `.qml`, the same as
  `lupdate` and the QML engine use. All KDE modules are `main.qml`, so they
  share the context `main`.
- C++: a bare `tr()` takes the class of the member function that holds it.
  `Class::tr(value)` marks nothing: mark the literal with
  `QT_TRANSLATE_NOOP("Class", "...")` where you define it.
- Python: each `_()` and `ngettext()` call.
- Rust: each `pub const NAME: &str = "...";` in `pub mod copy` of
  `frontends/cosmic/src/ui.rs`. The COSMIC catalog is a JSON object from the
  message id to its translation (`src/i18n.rs`), so the template is that
  object with each translation empty.
  `the_translation_template_holds_the_compiled_message_ids` in `ui.rs`
  compares the template with the values that rustc compiles.

The script stops with an error on a form that it cannot read. Examples are
a `qsTr()` of a value, a translated string glued to a value with `+`, and a
`copy` constant that is not one plain string literal. A string that a
template cannot hold is a string that no translator sees.

## Branding copy

The lines of `shared/branding/copy-defaults.json` and the `copy` of a
`branding.json` are not in a template. A product owns those lines. See
"Languages" in [../branding/README.md](../branding/README.md).

## What is not done

- No frontend ships a translation yet. Each template is the start for one.
- KDE loads `share/tuna-installer-kde/translations/tuna-installer-kde_<locale>.qm`
  when it exists, but its build does not compile a `.ts` file to a `.qm` file.
- Niri has no code that loads a Qt catalog. Quickshell runs the QML, and a
  `.qm` file has no effect until the frontend installs a translator.
- XFCE loads `tuna-installer-xfce.mo` from `/app/share/locale` or
  `/usr/share/locale`. Its Flatpak installs no `.mo` file yet.
- COSMIC uses a small `tr()` shim, not Fluent (`fl!`). `src/i18n.rs` says why.
