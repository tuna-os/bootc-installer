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

## Catalogs

A catalog is a template with translations. `catalogs.py` writes the
catalog of a language for each frontend, and its `--check` fails when the
messages of a catalog are not the messages of its template, or when a
translation drops or adds a placeholder.

```bash
python3 shared/i18n/catalogs.py fr          # write the French catalog of each frontend
python3 shared/i18n/catalogs.py fr niri     # write one catalog
python3 shared/i18n/catalogs.py --check     # exit 1 when a catalog is out of date
```

Run the script for each language after you run `templates.py`.
`tests/unit/test_frontend_translation_catalogs.py` runs the check.

Each message gets its translation in this order:

1. The translation that the catalog has. The script keeps the work of a
   translator.
2. The translation of the same English text in `po/<lang>.po` of GNOME,
   if that entry is translated and is not fuzzy.
3. No translation. The script does not make up a translation. A message
   with no translation shows the English text.

| Frontend | Catalog | Build | Load |
|---|---|---|---|
| KDE | `i18n/tuna-installer-kde_<lang>.ts` | CMake compiles it to `.qm` and installs it in `share/tuna-installer-kde/translations` | `src/translations.cpp`, from `main.cpp` |
| Niri | `i18n/tuna-installer-niri_<lang>.ts` | `translations/CMakeLists.txt` compiles it to `.qm` and installs it in `share/tuna-installer-niri/translations` | the QML module `TunaInstaller.Translations` (`translations/catalog.cpp`), from `ui/i18n.js` |
| XFCE | `po/<lang>.po` | the Flatpak compiles it to `share/locale/<lang>/LC_MESSAGES/tuna-installer-xfce.mo` | `tuna_installer_xfce/i18n.py` |
| COSMIC | `i18n/<lang>.json` | the Flatpak installs it in `share/tuna-installer-cosmic/locale` | `src/i18n.rs` |

Each frontend has a test that loads its catalog and translates a known
string: `shippedCatalogLoadsAndTranslates` in KDE `test_backend`,
`translations/tests/test_catalog.cpp` for Niri (the `Translations (niri)`
job of `ci-niri.yml`), `tests/test_catalogs.py` for XFCE and
`the_shipped_french_catalog_loads_and_translates` in COSMIC `i18n.rs`.
The tests prove the catalog and the code that loads it. Only the
`<frontend> / publish / Build OCI` job of each frontend proves that the
Flatpak installs the catalog.

Quickshell runs the Niri QML in a plain `QQmlEngine`, and that engine
loads no catalog. Thus the Niri frontend has a small QML module in C++
that loads the `.qm` file for the locale and retranslates the engine. The
launcher of the Flatpak puts the module on `QML_IMPORT_PATH`. Where the
module is not there (the screenshot harness, the wasm preview), the text
stays English.

The XFCE Flatpak sets `separate-locales` to `false`. Otherwise
`flatpak-builder` moves `share/locale` to a `.Locale` extension, and the
OCI bundle does not hold that extension.

### The first language

Each frontend ships French first. French is one of the most complete
languages in `po/` of GNOME. On 2026-11-12, twelve languages had the same
number of translated messages (71 of 269), and each one gave the same
strings to the frontends. French is the choice from that group. The test
`test_the_seed_is_one_of_the_most_complete_gnome_languages` holds it. Only
the strings that GNOME has translated have a French translation. The other
strings show English until a translator adds them.

COSMIC keeps its `tr()` shim and does not use Fluent (`fl!`). The JSON
catalog uses the English text as the key, the same as gettext and Qt, so
the script fills it from `po/` of GNOME. Fluent uses a second name for each
message, and it adds two dependencies and a new `cargo-sources.json`.
`src/i18n.rs` gives the full reason.
