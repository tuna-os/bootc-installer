//! The single choke point for translatable text (#300).
//!
//! Every user-facing line of this frontend is either a branding copy key
//! (`branding::text`, `shared/branding/copy-defaults.json`) or a message id
//! from `ui::copy`, and every message id reaches a widget through [`tr`].
//! `ui::tests::no_widget_takes_a_bare_string` fails on a literal or a
//! `copy` constant that goes to a widget any other way.
//!
//! This is a shim, not Fluent, and it stays one now that a catalog ships.
//! libcosmic applications use `fl!` with `i18n-embed` and `rust-embed`.
//! Fluent would add two direct dependencies, a new `cargo-sources.json`
//! and a build-time asset directory, and its message ids are keys, not the
//! English text: every `ui::copy` constant and every catalog would need a
//! second name. The JSON catalog keys on the English text, the same as
//! gettext and Qt, so `shared/i18n/catalogs.py` fills it from the GNOME
//! frontend's `po/<lang>.po` for each identical string. The strings of this
//! frontend have no plural forms and only named `{placeholders}`, which is
//! all the shim does. Change to `fl!` here, in one place, when a string
//! needs Fluent's plurals or selectors.
//!
//! A catalog is one JSON object per language, message id to translation:
//! `<dir>/<lang>.json`, with `<lang>` as in `LANG` ("de_DE", then "de").
//! The catalogs are `i18n/<lang>.json` (written by
//! `shared/i18n/catalogs.py`); the Flatpak installs them in
//! `/app/share/tuna-installer-cosmic/locale`. An operator can put one in
//! `/etc/bootc-installer/locale` to override it. A message with no
//! translation is its own text.

use std::collections::HashMap;
use std::sync::OnceLock;

/// Where a catalog can be, in order. The first file that parses is used.
const CATALOG_DIRS: [&str; 4] = [
    "/run/host/etc/bootc-installer/locale",
    "/etc/bootc-installer/locale",
    "/app/share/tuna-installer-cosmic/locale",
    "/usr/share/tuna-installer-cosmic/locale",
];

/// The language names to try for a locale value: "de_DE.UTF-8" gives
/// "de_DE" and then "de". "C", "POSIX" and an empty value give none.
pub fn language_candidates(locale: &str) -> Vec<String> {
    let base = locale
        .split(['.', '@'])
        .next()
        .unwrap_or("")
        .trim();
    if base.is_empty() || base == "C" || base == "POSIX" {
        return Vec::new();
    }
    let mut out = vec![base.to_string()];
    if let Some((lang, _)) = base.split_once('_') {
        out.push(lang.to_string());
    }
    out
}

/// The catalog for `locale` below the first of `dirs` that has one.
pub fn load_catalog(dirs: &[&str], locale: &str) -> HashMap<String, String> {
    for lang in language_candidates(locale) {
        for dir in dirs {
            let Ok(text) = std::fs::read_to_string(format!("{dir}/{lang}.json")) else {
                continue;
            };
            if let Ok(map) = serde_json::from_str::<HashMap<String, String>>(&text) {
                return map;
            }
        }
    }
    HashMap::new()
}

fn catalog() -> &'static HashMap<String, String> {
    static CATALOG: OnceLock<HashMap<String, String>> = OnceLock::new();
    CATALOG.get_or_init(|| {
        let locale = ["LC_ALL", "LC_MESSAGES", "LANG"]
            .iter()
            .filter_map(|name| std::env::var(name).ok())
            .find(|value| !value.is_empty())
            .unwrap_or_default();
        load_catalog(&CATALOG_DIRS, &locale)
    })
}

/// `msgid` in `catalog`, or `msgid` itself. An empty translation is no
/// translation.
pub fn translate(catalog: &HashMap<String, String>, msgid: &str) -> String {
    match catalog.get(msgid) {
        Some(text) if !text.is_empty() => text.clone(),
        _ => msgid.to_string(),
    }
}

/// The text to show for a message id of `ui::copy`.
pub fn tr(msgid: &str) -> String {
    translate(catalog(), msgid)
}

/// [`tr`], then each `{name}` replaced by its value.
pub fn tr_with(msgid: &str, values: &[(&str, &str)]) -> String {
    let mut text = tr(msgid);
    for (name, value) in values {
        text = text.replace(&format!("{{{name}}}"), value);
    }
    text
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_locale_names_its_language_candidates() {
        assert_eq!(language_candidates("de_DE.UTF-8"), ["de_DE", "de"]);
        assert_eq!(language_candidates("sr_RS@latin"), ["sr_RS", "sr"]);
        assert_eq!(language_candidates("fr"), ["fr"]);
        for none in ["", "C", "C.UTF-8", "POSIX"] {
            assert!(language_candidates(none).is_empty(), "{none:?}");
        }
    }

    #[test]
    fn a_catalog_translates_and_a_missing_message_is_itself() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().to_str().unwrap();
        std::fs::write(
            dir.path().join("de.json"),
            r#"{"Back": "Zurück", "Continue": ""}"#,
        )
        .unwrap();
        // "de_DE" has no file; "de" has.
        let catalog = load_catalog(&["/nonexistent", path], "de_DE.UTF-8");
        assert_eq!(translate(&catalog, "Back"), "Zur\u{fc}ck");
        assert_eq!(translate(&catalog, "Continue"), "Continue", "an empty translation");
        assert_eq!(translate(&catalog, "Exit"), "Exit", "no translation");
        // No catalog for the language, and a file that is not a catalog.
        assert!(load_catalog(&[path], "fr_FR.UTF-8").is_empty());
        std::fs::write(dir.path().join("fr.json"), "[]").unwrap();
        assert!(load_catalog(&[path], "fr_FR.UTF-8").is_empty());
    }

    /// `i18n/` of this frontend: the catalogs the Flatpak ships.
    const SHIPPED: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/i18n");

    #[test]
    fn the_shipped_french_catalog_loads_and_translates() {
        let catalog = load_catalog(&[SHIPPED], "fr_FR.UTF-8");
        assert!(!catalog.is_empty(), "{SHIPPED}/fr.json did not load");
        // A known string, from the GNOME frontend's po/fr.po.
        assert_eq!(translate(&catalog, crate::ui::copy::BACK), "Retour");
        // A string with no French yet is the English text.
        assert_eq!(
            translate(&catalog, crate::ui::copy::DISK_TITLE),
            crate::ui::copy::DISK_TITLE
        );
        // Every message id of the catalog is one of the template.
        let template: HashMap<String, String> = serde_json::from_str(
            &std::fs::read_to_string(format!("{SHIPPED}/template.json")).unwrap(),
        )
        .unwrap();
        for msgid in catalog.keys() {
            assert!(
                template.contains_key(msgid),
                "{msgid:?} is not in template.json"
            );
        }
    }

    #[test]
    fn the_flatpak_installs_each_catalog_where_tr_looks() {
        let manifest: serde_json::Value =
            serde_json::from_str(include_str!("../flatpak/org.tunaos.InstallerCosmic.json"))
                .unwrap();
        let module = manifest["modules"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["name"] == "tuna-installer-cosmic")
            .unwrap();
        let commands: Vec<&str> = module["build-commands"]
            .as_array()
            .unwrap()
            .iter()
            .map(|c| c.as_str().unwrap())
            .collect();
        let install = commands
            .iter()
            .find(|c| c.contains("i18n/"))
            .expect("a build command that installs i18n/<lang>.json");
        assert!(install.contains(CATALOG_DIRS[2]), "{install}");
        assert!(
            install.contains("template.json"),
            "the template is no catalog: {install}"
        );
    }

    #[test]
    fn placeholders_are_filled_after_the_translation() {
        assert_eq!(
            tr_with("Step {n} of {total}", &[("n", "2"), ("total", "9")]),
            "Step 2 of 9"
        );
    }
}
