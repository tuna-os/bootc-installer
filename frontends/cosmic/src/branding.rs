//! Product branding: a branding.json first, os-release second, neutral last.
//!
//! The contract, the key table and the fixtures are in `shared/branding/`
//! at the monorepo root; every frontend resolves the same way and this is
//! the Rust copy, tested against the shared fixtures below. Nothing in this
//! file names a product.
//!
//! Resolved once, on first use, and cached: the value cannot change while the
//! installer is running, and `view()` runs every frame.

use std::collections::HashMap;
use std::sync::OnceLock;

const ENV_FILE: &str = "BOOTC_INSTALLER_BRANDING";
/// Overrides `name` only. Exists for the screenshot harness: the CI runner's
/// `PRETTY_NAME` is "Ubuntu 24.04 LTS", and the committed docs walkthrough
/// should not read "Install Ubuntu". Not a user-facing knob.
const ENV_NAME: &str = "BOOTC_INSTALLER_PRODUCT_NAME";

pub const NEUTRAL_NAME: &str = "Linux";
pub const NEUTRAL_ID: &str = "linux";

/// Host first: this ships as a Flatpak, where `/etc` is the runtime's and the
/// host's is bind-mounted under `/run/host`. First readable file wins.
const BRANDING_PATHS: [&str; 4] = [
    "/run/host/etc/bootc-installer/branding.json",
    "/run/host/usr/share/bootc-installer/branding.json",
    "/etc/bootc-installer/branding.json",
    "/usr/share/bootc-installer/branding.json",
];
const OS_RELEASE_PATHS: [&str; 4] = [
    "/run/host/etc/os-release",
    "/run/host/usr/lib/os-release",
    "/etc/os-release",
    "/usr/lib/os-release",
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Branding {
    pub name: String,
    pub id: String,
    pub vendor: String,
    pub home_url: String,
    pub docs_url: String,
    pub support_url: String,
    pub logo: String,
    pub default_hostname: String,
    pub default_image: String,
}

/// The branding for this machine, resolved once.
pub fn get() -> &'static Branding {
    static BRANDING: OnceLock<Branding> = OnceLock::new();
    BRANDING.get_or_init(resolve)
}

/// The product name to show the user, e.g. "Skipjack".
pub fn name() -> &'static str {
    &get().name
}

fn resolve() -> Branding {
    let file_paths: Vec<String> = match std::env::var(ENV_FILE) {
        Ok(p) if !p.trim().is_empty() => vec![p.trim().to_string()],
        _ => BRANDING_PATHS.iter().map(|s| s.to_string()).collect(),
    };
    let file = file_paths.iter().find_map(|p| {
        let text = std::fs::read_to_string(p).ok()?;
        serde_json::from_str::<serde_json::Value>(&text)
            .ok()
            .and_then(|v| v.as_object().cloned())
    });
    let os_release = OS_RELEASE_PATHS.iter().find_map(|p| {
        std::fs::read_to_string(p)
            .ok()
            .filter(|t| !t.trim().is_empty())
    });
    let override_name = std::env::var(ENV_NAME).unwrap_or_default();
    from_sources(file.as_ref(), os_release.as_deref(), &override_name)
}

/// The pure merge rule from `shared/branding/README.md`.
pub fn from_sources(
    file: Option<&serde_json::Map<String, serde_json::Value>>,
    os_release_text: Option<&str>,
    name_override: &str,
) -> Branding {
    let osr = os_release_text.map(parse_os_release).unwrap_or_default();
    let pick = |key: &str, os_keys: &[&str], default: &str| -> String {
        if let Some(v) = file
            .and_then(|f| f.get(key))
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|v| !v.is_empty())
        {
            return v.to_string();
        }
        for k in os_keys {
            if let Some(v) = osr.get(*k).map(|v| v.trim()).filter(|v| !v.is_empty()) {
                return v.to_string();
            }
        }
        default.to_string()
    };
    let mut b = Branding {
        name: pick("name", &["PRETTY_NAME", "NAME"], NEUTRAL_NAME),
        id: pick("id", &["ID"], NEUTRAL_ID),
        vendor: pick("vendor", &["VENDOR_NAME", "NAME"], ""),
        home_url: pick("home_url", &["HOME_URL"], ""),
        docs_url: pick("docs_url", &["DOCUMENTATION_URL"], ""),
        support_url: pick("support_url", &["SUPPORT_URL"], ""),
        logo: pick("logo", &["LOGO"], ""),
        default_hostname: pick("default_hostname", &["DEFAULT_HOSTNAME", "ID"], NEUTRAL_ID),
        default_image: pick("default_image", &[], ""),
    };
    let o = name_override.trim();
    if !o.is_empty() {
        b.name = o.to_string();
    }
    b
}

/// `KEY=value` pairs with quotes and backslash escapes removed. Lines that do
/// not parse are skipped rather than failing the whole file.
pub fn parse_os_release(text: &str) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim();
        if key.is_empty() {
            continue;
        }
        out.insert(key.to_string(), unquote_shell(value.trim()));
    }
    out
}

/// The subset of shell quoting os-release allows: double quotes with
/// backslash escapes, single quotes, or a bare word ending at whitespace.
fn unquote_shell(v: &str) -> String {
    let mut chars = v.chars();
    match chars.next() {
        Some('"') => {
            let mut out = String::new();
            let mut escaped = false;
            for c in chars {
                if escaped {
                    out.push(c);
                    escaped = false;
                } else if c == '\\' {
                    escaped = true;
                } else if c == '"' {
                    break;
                } else {
                    out.push(c);
                }
            }
            out.trim().to_string()
        }
        Some('\'') => {
            let rest = &v[1..];
            let end = rest.find('\'').unwrap_or(rest.len());
            rest[..end].trim().to_string()
        }
        Some(_) => v.split_whitespace().next().unwrap_or("").to_string(),
        None => String::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn fixtures() -> Option<PathBuf> {
        let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("shared")
            .join("branding")
            .join("fixtures");
        dir.is_dir().then_some(dir)
    }

    fn as_map(b: &Branding) -> HashMap<&'static str, &str> {
        HashMap::from([
            ("name", b.name.as_str()),
            ("id", b.id.as_str()),
            ("vendor", b.vendor.as_str()),
            ("home_url", b.home_url.as_str()),
            ("docs_url", b.docs_url.as_str()),
            ("support_url", b.support_url.as_str()),
            ("logo", b.logo.as_str()),
            ("default_hostname", b.default_hostname.as_str()),
            ("default_image", b.default_image.as_str()),
        ])
    }

    #[test]
    fn shared_fixtures() {
        let Some(dir) = fixtures() else {
            eprintln!("shared fixtures not available; skipping");
            return;
        };
        let expected: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(dir.join("expected.json")).unwrap())
                .unwrap();
        for (case, spec) in expected.as_object().unwrap() {
            if case.starts_with('_') {
                continue;
            }
            let file = spec["branding"].as_str().map(|f| {
                serde_json::from_str::<serde_json::Value>(
                    &std::fs::read_to_string(dir.join(f)).unwrap(),
                )
                .unwrap()
                .as_object()
                .cloned()
                .unwrap()
            });
            let osr = spec["os_release"]
                .as_str()
                .map(|f| std::fs::read_to_string(dir.join(f)).unwrap());
            let override_name = spec["name_override"].as_str().unwrap_or("");
            let got = from_sources(file.as_ref(), osr.as_deref(), override_name);
            if let Some(expect) = spec["expect"].as_object() {
                let gm = as_map(&got);
                for (k, v) in expect {
                    assert_eq!(gm[k.as_str()], v.as_str().unwrap(), "{case}: {k}");
                }
            }
            if let Some(n) = spec["expect_name"].as_str() {
                assert_eq!(got.name, n, "{case}: name override");
            }
        }
    }

    #[test]
    fn nothing_readable_is_neutral() {
        let b = from_sources(None, None, "");
        assert_eq!(b.name, NEUTRAL_NAME);
        assert_eq!(b.id, NEUTRAL_ID);
        assert_eq!(b.default_hostname, NEUTRAL_ID);
        assert!(b.default_image.is_empty());
    }

    #[test]
    fn os_release_quoting() {
        let m = parse_os_release("NAME=\"Quoted \\\"Name\\\"\"\nPRETTY_NAME='Single'\nID=plain rest\nEMPTY=\nNOEQ\n");
        assert_eq!(m["NAME"], "Quoted \"Name\"");
        assert_eq!(m["PRETTY_NAME"], "Single");
        assert_eq!(m["ID"], "plain");
        assert_eq!(m["EMPTY"], "");
        assert!(!m.contains_key("NOEQ"));
    }
}
