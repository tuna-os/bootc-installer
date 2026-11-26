//! Names for people: languages, keyboard layouts and time zones.
//!
//! The recipe takes "de_DE.UTF-8", "de" and "Europe/Berlin". The pages show
//! these names and keep the ids. A language is shown in its own words, so a
//! person finds it whatever language the session has. An id that the tables
//! do not have is shown as it is.

use std::collections::HashMap;
use std::sync::OnceLock;

/// ISO 639 code and the name of the language in that language.
const LANGUAGES: &[(&str, &str)] = &[
    ("af", "Afrikaans"), ("ar", "العربية"), ("be", "Беларуская"), ("bg", "Български"),
    ("bn", "বাংলা"), ("bs", "Bosanski"), ("ca", "Català"), ("cs", "Čeština"),
    ("cy", "Cymraeg"), ("da", "Dansk"), ("de", "Deutsch"), ("el", "Ελληνικά"),
    ("en", "English"), ("eo", "Esperanto"), ("es", "Español"), ("et", "Eesti"),
    ("eu", "Euskara"), ("fa", "فارسی"), ("fi", "Suomi"), ("fr", "Français"),
    ("ga", "Gaeilge"), ("gl", "Galego"), ("gu", "ગુજરાતી"), ("he", "עברית"),
    ("hi", "हिन्दी"), ("hr", "Hrvatski"), ("hu", "Magyar"), ("hy", "Հայերեն"),
    ("id", "Bahasa Indonesia"), ("is", "Íslenska"), ("it", "Italiano"), ("ja", "日本語"),
    ("ka", "ქართული"), ("kk", "Қазақша"), ("km", "ខ្មែរ"), ("kn", "ಕನ್ನಡ"),
    ("ko", "한국어"), ("lt", "Lietuvių"), ("lv", "Latviešu"), ("mk", "Македонски"),
    ("ml", "മലയാളം"), ("mr", "मराठी"), ("ms", "Bahasa Melayu"), ("nb", "Norsk bokmål"),
    ("ne", "नेपाली"), ("nl", "Nederlands"), ("nn", "Norsk nynorsk"), ("pa", "ਪੰਜਾਬੀ"),
    ("pl", "Polski"), ("pt", "Português"), ("ro", "Română"), ("ru", "Русский"),
    ("sk", "Slovenčina"), ("sl", "Slovenščina"), ("sq", "Shqip"), ("sr", "Српски"),
    ("sv", "Svenska"), ("ta", "தமிழ்"), ("te", "తెలుగు"), ("th", "ไทย"),
    ("tr", "Türkçe"), ("uk", "Українська"), ("ur", "اردو"), ("uz", "Oʻzbekcha"),
    ("vi", "Tiếng Việt"), ("zh", "中文"),
];

/// "Deutsch (DE)" for "de_DE.UTF-8". The territory tells "English (GB)" from
/// "English (US)"; the codeset is for the recipe.
pub fn language(locale: &str) -> String {
    let base = locale.split(['.', '@']).next().unwrap_or(locale);
    let (code, territory) = base.split_once('_').unwrap_or((base, ""));
    match LANGUAGES.iter().find(|(id, _)| *id == code) {
        Some((_, name)) if territory.is_empty() => (*name).to_string(),
        Some((_, name)) => format!("{name} ({territory})"),
        None => locale.to_string(),
    }
}

/// C and POSIX are locales, and no person's language.
pub fn is_language(locale: &str) -> bool {
    !matches!(locale.split('.').next(), Some("C" | "POSIX" | ""))
}

/// The city first, as a person looks for it: "Buenos Aires
/// (America/Argentina)".
pub fn timezone(zone: &str) -> String {
    match zone.rsplit_once('/') {
        Some((area, city)) => format!("{} ({})", city.replace('_', " "), area.replace('_', " ")),
        None => zone.to_string(),
    }
}

/// "German" for "de"; the bare layout when XKB has no name for it.
pub fn keymap(layout: &str) -> String {
    static NAMES: OnceLock<HashMap<String, String>> = OnceLock::new();
    let names = NAMES.get_or_init(|| {
        // The sandbox has its own list; the host's is the second choice.
        [
            "/usr/share/X11/xkb/rules/evdev.lst",
            "/run/host/usr/share/X11/xkb/rules/evdev.lst",
        ]
        .iter()
        .find_map(|path| std::fs::read_to_string(path).ok())
        .map(|text| xkb_layouts(&text))
        .unwrap_or_default()
    });
    names.get(layout).cloned().unwrap_or_else(|| layout.to_string())
}

/// The `! layout` section of an XKB rules list.
fn xkb_layouts(text: &str) -> HashMap<String, String> {
    let mut inside = false;
    let mut names = HashMap::new();
    for line in text.lines() {
        if let Some(section) = line.strip_prefix('!') {
            inside = section.trim() == "layout";
        } else if inside {
            if let Some((code, name)) = line.trim().split_once(char::is_whitespace) {
                names.insert(code.to_string(), name.trim().to_string());
            }
        }
    }
    names
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_language_is_named_in_its_own_words() {
        assert_eq!(language("de_DE.UTF-8"), "Deutsch (DE)");
        assert_eq!(language("en_US.UTF-8"), "English (US)");
        assert_eq!(language("eo"), "Esperanto");
        assert!(!is_language("C.UTF-8") && !is_language("POSIX") && is_language("de_DE.UTF-8"));
    }

    #[test]
    fn a_time_zone_starts_with_its_city() {
        assert_eq!(timezone("America/Argentina/Buenos_Aires"), "Buenos Aires (America/Argentina)");
        assert_eq!(timezone("UTC"), "UTC");
    }

    #[test]
    fn layouts_come_from_the_layout_section_only() {
        let names = xkb_layouts("! model\n  pc104  Generic\n! layout\n  de   German\n! variant\n  x  de: X\n");
        assert_eq!(names.len(), 1);
        assert_eq!(names["de"], "German");
    }
}
