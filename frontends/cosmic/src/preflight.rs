//! First-boot preflight: locale, keyboard, timezone and connectivity.
//!
//! GNOME asks these before the disk page (`defaults/language.py`,
//! `keyboard.py`, `timezone.py`, `network.py`, `conn_check.py`). This
//! frontend used to ask none of them: the installed system inherited
//! whatever the live session happened to use. Each check here is plain
//! data plus a host command, so the wizard stays honest about what the
//! sandbox can and cannot do:
//!
//! - Listing and applying go through `localectl` / `timedatectl` on the
//!   host (`flatpak-spawn --host` when sandboxed). Applying needs
//!   privileges and is best-effort: a failed apply warns and the wizard
//!   keeps going, because the install itself does not depend on it.
//! - The connectivity check tries the registry of the selected image on
//!   443 first, then the shared targets (`ghcr.io:443`, `8.8.8.8:53`),
//!   five seconds each.
//!   Live media skips the page entirely (an offline install needs no
//!   network), also as in GNOME (`should_show` on `offline_install`).

use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::time::Duration;

/// The shared connectivity targets, tried after the registry of the
/// selected image: a registry, then bare DNS.
pub const CONNECT_TARGETS: [(&str, u16); 2] = [("ghcr.io", 443), ("8.8.8.8", 53)];

/// Seconds per target, as in GNOME.
pub const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);

/// Skip the whole check (and pass): `VANILLA_SKIP_CONN_CHECK`, as in GNOME.
pub fn conn_check_skipped() -> bool {
    std::env::var_os("VANILLA_SKIP_CONN_CHECK").is_some()
}

/// The registry host of an image reference: the part before the first
/// `/` when it looks like a host (a dot, a port or `localhost`), else
/// Docker Hub. `None` for an empty reference.
pub fn registry_host(imgref: &str) -> Option<String> {
    let reference = imgref.trim();
    let reference = reference
        .split_once("://")
        .map_or(reference, |(_, rest)| rest);
    if reference.is_empty() {
        return None;
    }
    let first = reference.split('/').next().unwrap_or("");
    let is_host = reference.contains('/')
        && (first.contains('.') || first.contains(':') || first == "localhost");
    if !is_host {
        return Some("registry-1.docker.io".to_string());
    }
    // A port in the reference is the registry's own; the check is for 443.
    Some(first.split(':').next().unwrap_or(first).to_string())
}

/// The targets for an install of `imgref`, in order: the registry of the
/// selected image on 443 first, because that is the host the install
/// downloads from, then the shared list. No target is tried twice.
pub fn connect_targets(imgref: &str) -> Vec<(String, u16)> {
    let mut targets: Vec<(String, u16)> = Vec::new();
    if let Some(host) = registry_host(imgref) {
        targets.push((host, 443));
    }
    for (host, port) in CONNECT_TARGETS {
        if !targets.iter().any(|(h, p)| h == host && *p == port) {
            targets.push((host.to_string(), port));
        }
    }
    targets
}

/// True when any target for `imgref` accepts a TCP connection within the
/// timeout.
pub fn check_connectivity(imgref: &str) -> bool {
    if conn_check_skipped() {
        return true;
    }
    connect_targets(imgref)
        .iter()
        .any(|(host, port)| reaches(&format!("{host}:{port}"), CONNECT_TIMEOUT).unwrap_or(false))
}

fn reaches(addr: &str, timeout: Duration) -> std::io::Result<bool> {
    let mut last_err = None;
    for candidate in addr.to_socket_addrs()? {
        // `connect_timeout` needs a concrete SocketAddr, not a name.
        let ip = match candidate {
            SocketAddr::V4(v4) => SocketAddr::V4(v4),
            SocketAddr::V6(v6) => SocketAddr::V6(v6),
        };
        match TcpStream::connect_timeout(&ip, timeout) {
            Ok(_) => return Ok(true),
            Err(e) => last_err = Some(e),
        }
    }
    Err(last_err.unwrap_or_else(|| {
        std::io::Error::new(std::io::ErrorKind::NotFound, "no address for host")
    }))
}

/// Split `localectl list-locales` output into the locale list.
pub fn parse_locales(output: &str) -> Vec<String> {
    output
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(str::to_string)
        .collect()
}

/// The session's locale first (as `$LANG` names it), then the rest in
/// listed order — the current choice stays selected instead of resetting
/// to the top of the list.
pub fn order_locales(mut locales: Vec<String>, current: &str) -> Vec<String> {
    if let Some(i) = locales.iter().position(|l| l == current) {
        let found = locales.remove(i);
        locales.insert(0, found);
    }
    locales
}

/// Split `localectl list-x11-keymap-layouts` output into layout names.
pub fn parse_keymaps(output: &str) -> Vec<String> {
    output
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(str::to_string)
        .collect()
}

/// Split `timedatectl list-timezones` output into zone names.
pub fn parse_timezones(output: &str) -> Vec<String> {
    output
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(str::to_string)
        .collect()
}

/// Case-insensitive substring filter over zone names, capped so the page
/// stays a page and not a ten-thousand-line list. An empty query shows the
/// head of the list instead of everything.
pub fn filter_timezones<'a>(zones: &'a [String], query: &str, limit: usize) -> Vec<&'a String> {
    let q = query.trim().to_lowercase();
    if q.is_empty() {
        return zones.iter().take(limit).collect();
    }
    zones
        .iter()
        .filter(|z| z.to_lowercase().contains(&q))
        .take(limit)
        .collect()
}

/// `localectl set-locale LANG=...` on the host. Best-effort (see module docs).
pub fn apply_locale_command(locale: &str) -> Vec<String> {
    crate::offline::host_command(&["localectl", "set-locale", &format!("LANG={locale}")])
}

/// `localectl set-x11-keymap ...` on the host: the XKB layout, which
/// localectl also converts to the console keymap. Best-effort.
pub fn apply_keymap_command(keymap: &str) -> Vec<String> {
    crate::offline::host_command(&["localectl", "set-x11-keymap", keymap])
}

/// `timedatectl set-timezone ...` on the host. Best-effort.
pub fn apply_timezone_command(timezone: &str) -> Vec<String> {
    crate::offline::host_command(&["timedatectl", "set-timezone", timezone])
}

/// Run a host command and return its stdout. A command that cannot run,
/// or exits nonzero, yields nothing: the page then shows its empty state
/// instead of blocking the wizard on a preflight detail.
fn host_stdout(argv: &[String]) -> Option<String> {
    let Some((program, args)) = argv.split_first() else {
        return None;
    };
    match std::process::Command::new(program).args(args).output() {
        Ok(out) if out.status.success() => Some(String::from_utf8_lossy(&out.stdout).into_owned()),
        Ok(out) => {
            tracing::warn!("preflight list {argv:?} exited {}", out.status);
            None
        }
        Err(e) => {
            tracing::warn!("preflight list {argv:?} could not run: {e}");
            None
        }
    }
}

/// `localectl list-locales` on the host.
pub fn load_locales() -> Vec<String> {
    host_stdout(&crate::offline::host_command(&[
        "localectl",
        "list-locales",
    ]))
    .map(|o| parse_locales(&o))
    .unwrap_or_default()
}

/// `localectl list-x11-keymap-layouts` on the host: the XKB layouts, the
/// names the recipe's `keyboard.layout` takes. Console keymap names
/// (`de-latin1`) are not XKB layouts.
pub fn load_keymaps() -> Vec<String> {
    host_stdout(&crate::offline::host_command(&[
        "localectl",
        "list-x11-keymap-layouts",
    ]))
    .map(|o| parse_keymaps(&o))
    .unwrap_or_default()
}

/// `timedatectl list-timezones` on the host.
pub fn load_timezones() -> Vec<String> {
    host_stdout(&crate::offline::host_command(&[
        "timedatectl",
        "list-timezones",
    ]))
    .map(|o| parse_timezones(&o))
    .unwrap_or_default()
}

/// Run a host command without waiting for an answer and without failing
/// the caller: preflight applies must never break the install.
pub fn apply_best_effort(argv: &[String]) {
    if let Some((program, args)) = argv.split_first() {
        match std::process::Command::new(program).args(args).spawn() {
            Ok(_) => {}
            Err(e) => tracing::warn!("preflight apply {argv:?} failed to start: {e}"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn locales_parse_and_current_sorts_first() {
        let parsed = parse_locales("C\nC.UTF-8\nen_US.UTF-8\n\nfr_FR.UTF-8\n");
        assert_eq!(parsed, vec!["C", "C.UTF-8", "en_US.UTF-8", "fr_FR.UTF-8"]);
        let ordered = order_locales(parsed, "fr_FR.UTF-8");
        assert_eq!(ordered[0], "fr_FR.UTF-8");
        assert_eq!(ordered.len(), 4);
    }

    #[test]
    fn unknown_current_locale_keeps_listed_order() {
        let parsed = parse_locales("en_US.UTF-8\n");
        assert_eq!(order_locales(parsed.clone(), "xx_YY"), parsed);
    }

    #[test]
    fn keymaps_parse() {
        assert_eq!(parse_keymaps("us\ndvorak\n"), vec!["us", "dvorak"]);
        assert!(parse_keymaps("").is_empty());
    }

    #[test]
    fn timezone_search_is_case_insensitive_and_capped() {
        let zones = vec![
            "Europe/Berlin".to_string(),
            "Europe/Paris".to_string(),
            "America/New_York".to_string(),
        ];
        let found = filter_timezones(&zones, "europe", 10);
        assert_eq!(found.len(), 2);
        let capped = filter_timezones(&zones, "", 2);
        assert_eq!(capped.len(), 2);
        let mixed = filter_timezones(&zones, "BER", 10);
        assert_eq!(mixed.len(), 1);
        assert!(filter_timezones(&zones, "moon", 10).is_empty());
    }

    #[test]
    fn apply_commands_target_the_host_tools() {
        assert!(!crate::offline::in_flatpak());
        assert_eq!(
            apply_locale_command("fr_FR.UTF-8"),
            vec!["localectl", "set-locale", "LANG=fr_FR.UTF-8"]
        );
        assert_eq!(
            apply_keymap_command("fr"),
            vec!["localectl", "set-x11-keymap", "fr"]
        );
        assert_eq!(
            apply_timezone_command("Europe/Paris"),
            vec!["timedatectl", "set-timezone", "Europe/Paris"]
        );
    }

    #[test]
    fn connectivity_reaches_a_local_listener() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            let _ = listener.accept();
        });
        assert!(reaches(&format!("127.0.0.1:{port}"), Duration::from_secs(5)).unwrap());
    }

    #[test]
    fn connectivity_fails_closed_port_fast() {
        // Port 1 is privileged and (practically) never listening: refused,
        // not a five-second wait.
        let start = std::time::Instant::now();
        let refused = reaches("127.0.0.1:1", Duration::from_secs(5));
        assert!(refused.is_err() || !refused.unwrap());
        assert!(start.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn the_registry_of_the_selected_image_is_probed_first() {
        assert_eq!(registry_host("quay.io/example/os:stable").as_deref(), Some("quay.io"));
        assert_eq!(registry_host("docker://quay.io/example/os").as_deref(), Some("quay.io"));
        assert_eq!(registry_host("registry.example:5000/os:1").as_deref(), Some("registry.example"));
        assert_eq!(registry_host("localhost/os:1").as_deref(), Some("localhost"));
        // No registry in the reference is Docker Hub.
        assert_eq!(registry_host("library/os:1").as_deref(), Some("registry-1.docker.io"));
        assert_eq!(registry_host("os").as_deref(), Some("registry-1.docker.io"));
        assert_eq!(registry_host("  "), None);

        let targets = connect_targets("quay.io/example/os:stable");
        assert_eq!(targets[0], ("quay.io".to_string(), 443));
        assert_eq!(targets[1..], [("ghcr.io".to_string(), 443), ("8.8.8.8".to_string(), 53)]);
        // The shared list alone with no image, and no host twice.
        assert_eq!(connect_targets("").len(), 2);
        assert_eq!(connect_targets("ghcr.io/example/os:1").len(), 2);
    }
}
