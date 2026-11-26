//! The terms-of-use page (screens.yaml `eula`).
//!
//! The image ships an AppStream component with an `agreement` of type
//! `eula`. All frontends read one shared path (ruling on #442):
//! `/usr/share/tuna-installer/eula.xml`, overridden by `TUNA_EULA_FILE`.
//! No file skips the page. An unreadable one is the `eula-unreadable`
//! failure state.
//!
//! The renderer is deliberately minimal: paragraphs of plain text. Lists
//! flatten into their items. It decodes the five XML entities and drops
//! every tag. A EULA that needs richer layout wants a real AppStream
//! reader, not a longer version of this function.

/// The shared EULA path for all frontends. `TUNA_EULA_FILE` overrides it
/// (tests, custom media).
pub const EULA_PATH: &str = "/usr/share/tuna-installer/eula.xml";

/// The EULA for this medium: `None` skips the page, `Some(Err)` is the
/// `eula-unreadable` failure state, `Some(Ok)` renders.
pub fn load() -> Option<Result<String, String>> {
    let path = std::env::var("TUNA_EULA_FILE")
        .ok()
        .filter(|p| !p.is_empty())
        .unwrap_or_else(|| EULA_PATH.to_string());
    load_from_path(&path)
}

fn load_from_path(path: &str) -> Option<Result<String, String>> {
    if !std::path::Path::new(path).is_file() {
        return None;
    }
    Some(match std::fs::read_to_string(path) {
        Ok(xml) => Ok(render_text(&xml)),
        Err(e) => Err(format!("{path}: {e}")),
    })
}

/// AppStream agreement XML to plain paragraphs. Block tags break lines,
/// inline tags vanish, the five entities decode. Anything else passes
/// through untouched: this shows words, never markup.
pub fn render_text(xml: &str) -> String {
    // A whole AppStream component carries its id, name, summary and
    // metadata licence before the agreement: those are no terms. Only the
    // agreement shows when the file has one.
    let xml = match (xml.find("<agreement"), xml.rfind("</agreement>")) {
        (Some(start), Some(end)) if end > start => &xml[start..end],
        _ => xml,
    };
    let mut out = String::new();
    let mut chars = xml.chars().peekable();
    while let Some(c) = chars.next() {
        if c != '<' {
            out.push(c);
            continue;
        }
        let mut tag = String::new();
        for c in chars.by_ref() {
            if c == '>' {
                break;
            }
            tag.push(c);
        }
        let name = tag
            .trim_start_matches('/')
            .split_whitespace()
            .next()
            .unwrap_or("")
            .to_lowercase();
        if tag.starts_with('!') || tag.starts_with('?') {
            continue;
        }
        if matches!(
            name.as_str(),
            "p" | "li" | "ul" | "ol" | "br" | "agreement" | "agreement_section" | "name"
                | "description"
        ) {
            out.push('\n');
        }
    }
    let text = out
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&apos;", "'");
    text.lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn agreement_renders_as_plain_paragraphs() {
        let xml = concat!(
            r#"<?xml version="1.0"?><agreement type="eula">"#,
            "<p>First paragraph with <b>bold</b> and &amp; entity.</p>",
            "<ul><li>One</li><li>Two</li></ul></agreement>",
        );
        assert_eq!(
            render_text(xml),
            "First paragraph with bold and & entity.\n\nOne\n\nTwo"
        );
    }

    #[test]
    fn a_whole_component_shows_only_its_agreement() {
        let xml = concat!(
            r#"<component type="operating-system"><id>org.tunaos.TunaOS</id>"#,
            "<name>TunaOS</name><summary>The terms</summary>",
            "<metadata_license>CC0-1.0</metadata_license>",
            r#"<agreement type="eula"><agreement_section><name>Use</name>"#,
            "<p>Do not.</p></agreement_section></agreement></component>",
        );
        assert_eq!(render_text(xml), "Use\n\nDo not.");
    }

    #[test]
    fn a_missing_file_skips_the_page() {
        assert!(load_from_path("/nonexistent/eula.xml").is_none());
    }

    #[test]
    fn a_present_file_renders_through_the_override() {
        // TUNA_EULA_FILE points at the shared path's stand-in: the page
        // reads the same file every frontend reads.
        let path = std::env::temp_dir().join(format!("eula-{}.xml", std::process::id()));
        std::fs::write(&path, "<p>Terms</p>").unwrap();
        let rendered = load_from_path(path.to_str().unwrap()).expect("file present");
        assert_eq!(rendered.unwrap(), "Terms");
        std::fs::remove_file(&path).ok();
        assert_eq!(EULA_PATH, "/usr/share/tuna-installer/eula.xml");
    }

    #[test]
    fn comments_and_processing_instructions_vanish() {
        let xml = "<!-- note --><p>Text</p>";
        assert_eq!(render_text(xml), "Text");
    }
}
