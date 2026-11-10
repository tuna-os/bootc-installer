//! The recovery key stays out of the install log (#337).
//!
//! fisherman sends the LUKS recovery key once, in a `recovery_key` event.
//! The done page shows it and holds Restart until the user says that it is
//! saved, and the log pane shows it to the same user. install.log outlives
//! the window, and Copy log puts the log on the clipboard: a user attaches
//! either to a bug report, so both get the redacted form. The form is the
//! same in every frontend that keeps a log, byte for byte:
//! `shared/progress/recovery-key-cases.json`.

/// What replaces a key.
pub const PLACEHOLDER: &str = "[redacted]";

/// `text` (one line or many) without a recovery key. Three forms go: the
/// `key` value of a `recovery_key` event, the text after "Recovery key:",
/// and `known_key` wherever a later line repeats it.
pub fn recovery_key(text: &str, known_key: &str) -> String {
    if text.is_empty() {
        return String::new();
    }
    let mut out = text
        .split('\n')
        .map(|line| {
            let line = if line.contains("\"recovery_key\"") {
                redact_key_values(line)
            } else {
                line.to_string()
            };
            redact_rendered(&line)
        })
        .collect::<Vec<_>>()
        .join("\n");
    let known = known_key.trim();
    if !known.is_empty() {
        out = out.replace(known, PLACEHOLDER);
    }
    out
}

/// Each `"key": "<value>"` in the line, with the value replaced. A value
/// with no closing quote stays as it is.
fn redact_key_values(line: &str) -> String {
    const NAME: &str = "\"key\"";
    let mut out = String::with_capacity(line.len());
    let mut rest = line;
    while let Some(at) = rest.find(NAME) {
        let after_name = &rest[at + NAME.len()..];
        let Some(value) = value_start(after_name) else {
            out.push_str(&rest[..at + NAME.len()]);
            rest = after_name;
            continue;
        };
        let opened = &after_name[..value];
        match closing_quote(&after_name[value..]) {
            Some(len) => {
                out.push_str(&rest[..at + NAME.len()]);
                out.push_str(opened);
                out.push_str(PLACEHOLDER);
                out.push('"');
                rest = &after_name[value + len + 1..];
            }
            None => {
                out.push_str(&rest[..at + NAME.len()]);
                rest = after_name;
            }
        }
    }
    out.push_str(rest);
    out
}

/// The byte offset after `\s*:\s*"`, when `s` starts with that.
fn value_start(s: &str) -> Option<usize> {
    let t = s.trim_start();
    let t = t.strip_prefix(':')?;
    let t = t.trim_start();
    let t = t.strip_prefix('"')?;
    Some(s.len() - t.len())
}

/// The length of a JSON string body up to its closing quote, escapes
/// included.
fn closing_quote(s: &str) -> Option<usize> {
    let mut chars = s.char_indices();
    while let Some((i, c)) = chars.next() {
        match c {
            '"' => return Some(i),
            '\\' => {
                chars.next()?;
            }
            _ => {}
        }
    }
    None
}

/// "Recovery key: <anything>" with the rest of the line replaced.
fn redact_rendered(line: &str) -> String {
    const LABEL: &str = "Recovery key:";
    let Some(at) = line.find(LABEL) else {
        return line.to_string();
    };
    let after = &line[at + LABEL.len()..];
    let value = after.trim_start();
    if value.is_empty() {
        return line.to_string();
    }
    let head = at + LABEL.len() + (after.len() - value.len());
    format!("{}{}", &line[..head], PLACEHOLDER)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::progress::Progress;

    const SHARED: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../shared/progress");

    fn spec() -> Option<serde_json::Value> {
        let text = std::fs::read_to_string(format!("{SHARED}/recovery-key-cases.json")).ok()?;
        Some(serde_json::from_str(&text).expect("recovery-key-cases.json is JSON"))
    }

    #[test]
    fn the_shared_cases() {
        let Some(spec) = spec() else { return };
        assert_eq!(spec["placeholder"], PLACEHOLDER);
        let key = spec["key"].as_str().unwrap();
        let lines = spec["lines"].as_array().unwrap();
        assert!(lines.len() >= 5);
        for case in lines {
            let known = if case["known_key"].as_bool().unwrap() {
                key
            } else {
                ""
            };
            assert_eq!(
                recovery_key(case["line"].as_str().unwrap(), known),
                case["redacted"].as_str().unwrap(),
                "{}",
                case["name"]
            );
        }
        assert_eq!(recovery_key("", key), "");
    }

    /// The transcript through the same steps a real install takes: each
    /// line through Progress::consume into the pane's log, then the log
    /// into install.log. The key is in the pane and not in the file.
    #[test]
    fn the_key_is_not_in_install_log() {
        let Some(spec) = spec() else { return };
        let key = spec["key"].as_str().unwrap();
        let transcript =
            std::fs::read_to_string(format!("{SHARED}/{}", spec["transcript"].as_str().unwrap()))
                .unwrap();
        let mut progress = Progress::new("Linux");
        let mut log = String::new();
        for line in transcript.lines() {
            if let Some(shown) = progress.consume(line) {
                log.push_str(&shown);
                log.push('\n');
            }
        }
        log.push_str(&format!("[stderr] enrolled slot 1 with {key}.\n"));
        assert_eq!(progress.recovery_key, key, "the done page keeps the key");
        assert!(log.contains(key), "the pane shows the key");

        let dir = tempfile::tempdir().unwrap();
        crate::offline::write_install_log(dir.path(), &log, &progress.recovery_key);
        let written = std::fs::read_to_string(dir.path().join("install.log")).unwrap();
        assert!(
            !written.contains(key),
            "the recovery key is in install.log:\n{written}"
        );
        assert!(written.contains("Recovery key: [redacted]\n"), "{written}");
        assert!(
            written.contains("enrolled slot 1 with [redacted]."),
            "{written}"
        );
        assert_eq!(written, recovery_key(&log, key));
    }
}
