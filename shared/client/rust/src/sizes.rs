//! Size text from a toolkit, made comparable (projectbluefin/utah#1437).
//! GLib's `g_format_size` puts U+00A0 between the number and the unit. Some
//! locales use U+202F. Same cases as `shared/client/fixtures/sizes.json`.

fn is_space_like(c: char) -> bool {
    c.is_whitespace()
        || matches!(c, '\u{00a0}' | '\u{1680}' | '\u{2000}'..='\u{200a}' | '\u{202f}' | '\u{205f}' | '\u{3000}')
}

fn is_invisible(c: char) -> bool {
    matches!(c, '\u{200b}'..='\u{200f}' | '\u{2060}' | '\u{2066}'..='\u{2069}' | '\u{feff}' | '\u{00ad}')
}

/// One plain space for each run of space-like characters; trimmed; no
/// invisible marks.
pub fn normalize_size_text(text: &str) -> String {
    let mut out = String::new();
    let mut pending = false;
    for c in text.chars() {
        if is_invisible(c) {
            continue;
        }
        if is_space_like(c) {
            pending = !out.is_empty();
            continue;
        }
        if pending {
            out.push(' ');
            pending = false;
        }
        out.push(c);
    }
    out
}

fn unit_factor(unit: &str) -> Option<f64> {
    Some(match unit.to_ascii_lowercase().as_str() {
        "b" | "byte" | "bytes" => 1.0,
        "kb" => 1e3,
        "mb" => 1e6,
        "gb" => 1e9,
        "tb" => 1e12,
        "pb" => 1e15,
        "kib" => 1024.0,
        "mib" => 1048576.0,
        "gib" => 1073741824.0,
        "tib" => 1099511627776.0,
        "pib" => 1125899906842624.0,
        _ => return None,
    })
}

fn number(raw: &str) -> Option<f64> {
    let cleaned = if raw.contains('.') && raw.contains(',') {
        raw.replace(',', "")
    } else if let Some(i) = raw.rfind(',') {
        let (head, tail) = (raw[..i].replace(',', ""), &raw[i + 1..]);
        if tail.len() == 3 { format!("{head}{tail}") } else { format!("{head}.{tail}") }
    } else {
        raw.to_string()
    };
    cleaned.parse().ok()
}

/// Bytes, or `None` when the text is not one size. SI units are powers of
/// 1000, as `g_format_size` writes them. IEC units are powers of 1024.
pub fn parse_size(text: &str) -> Option<i64> {
    let text = normalize_size_text(text);
    let split = text.find(|c: char| !(c.is_ascii_digit() || c == '.' || c == ','))?;
    let (num, unit) = text.split_at(split);
    if !num.starts_with(|c: char| c.is_ascii_digit()) {
        return None;
    }
    let unit = unit.strip_prefix(' ').unwrap_or(unit);
    if unit.is_empty() || !unit.chars().all(|c| c.is_ascii_alphabetic()) {
        return None;
    }
    Some((number(num)? * unit_factor(unit)?).round() as i64)
}
