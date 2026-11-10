//! Sandbox plumbing: how this frontend reaches fisherman and the host.
//! Contract: ../../INSTALLER-FRONTENDS.md §3 (privileges).
//!
//! Live media and offline image stores are fisherman's facts now (probe's
//! `live` and `offline`, probe.rs). This module used to find them itself:
//! `bootc status` plus /run/ostree-live and /proc/cmdline for live media,
//! and $TUNA_OFFLINE_STORES and /etc/tuna-installer/offline-stores for the
//! stores. Inside a Flatpak those paths are the runtime's, not the host's.
//! It also wrote the recipe to a 0600 temp file; fisherman now reads it on
//! stdin (`fisherman -`).
//!
//! [`fisherman_argv`] is the one resolver for the fisherman command:
//! probe, validate and install, natively, on live media and in a Flatpak.

use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

pub fn in_flatpak() -> bool {
    Path::new("/.flatpak-info").exists()
}

/// Where a native install has fisherman.
pub const NATIVE_FISHERMAN: &str = "/usr/local/bin/fisherman";

/// The fisherman the Flatpak builds. Nothing on the host can run it from
/// here, so it is staged first ([`stage_on_host`]).
pub const PACKAGED_FISHERMAN: &str = "/app/bin/fisherman";

/// What fisherman is asked to do. Each one has its own arguments and its
/// own privileges; all three run the same binary.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Use {
    /// `probe --json`, as the desktop user.
    Probe,
    /// `validate --json --partial -`, as the desktop user.
    Validate,
    /// `-` (the recipe on stdin), as root.
    Install,
}

/// A path as one word of a `bash -c` script.
fn sh_quote(word: &str) -> String {
    format!("'{}'", word.replace('\'', r"'\''"))
}

/// The one resolver: how this frontend reaches fisherman
/// (`shared/recipe/README.md`; issue #290). No other function in this crate
/// names a fisherman path; a test holds that.
///
/// - In a Flatpak the binary is `staged`: the packaged fisherman, copied to
///   the application cache and verified on the host ([`stage_on_host`]).
///   Everything runs through `flatpak-spawn --host`; the install escalates
///   with the host's pkexec.
/// - Natively it is [`NATIVE_FISHERMAN`]. The install escalates with
///   pkexec. On live media (`live`, from fisherman's probe) it is
///   `sudo -n`: the live user has passwordless sudo and may have no polkit
///   agent.
///
/// The install always runs inside a `bash -c` that this user owns.
/// fisherman runs as root, so this process can never signal it; it cancels
/// when its PARENT dies (tuna-os/fisherman#267). pkexec replaces itself
/// with fisherman, so that parent is the bash, and the bash is what a
/// cancel signals. No redirection: stdin, stdout and stderr pass through.
pub fn fisherman_argv(what: Use, flatpak: bool, live: bool, staged: &str) -> Vec<String> {
    let binary = if flatpak { staged } else { NATIVE_FISHERMAN };
    let mut argv: Vec<String> = Vec::new();
    if flatpak {
        argv.extend(["flatpak-spawn", "--host"].map(String::from));
    }
    match what {
        Use::Probe => {
            argv.push(binary.to_string());
            argv.extend(["probe", "--json"].map(String::from));
        }
        Use::Validate => {
            argv.push(binary.to_string());
            argv.extend(["validate", "--json", "--partial", "-"].map(String::from));
        }
        Use::Install => {
            let escalate = if !flatpak && live { "sudo -n" } else { "pkexec" };
            let binary = if flatpak {
                sh_quote(binary)
            } else {
                binary.to_string()
            };
            argv.extend(["bash", "-c"].map(String::from));
            argv.push(format!("{escalate} {binary} -; exit $?"));
        }
    }
    argv
}

/// [`fisherman_argv`] for this process. In a Flatpak the first call stages
/// the packaged fisherman; a staging failure is the error, and nothing
/// runs. `live` matters only for [`Use::Install`].
pub fn fisherman(what: Use, live: bool) -> Result<Vec<String>, String> {
    if !in_flatpak() {
        return Ok(fisherman_argv(what, false, live, ""));
    }
    static STAGED: std::sync::OnceLock<Result<String, String>> = std::sync::OnceLock::new();
    let staged = STAGED
        .get_or_init(|| {
            let source = std::env::var("BOOTC_FISHERMAN_PATH")
                .ok()
                .filter(|p| !p.is_empty())
                .unwrap_or_else(|| PACKAGED_FISHERMAN.to_string());
            let cache_home = std::env::var("XDG_CACHE_HOME").ok();
            stage_on_host(&source, cache_home.as_deref(), &host_sha256)
        })
        .clone()?;
    Ok(fisherman_argv(what, true, live, &staged))
}

/// Whether `path` is safe to hold a helper that root will run: missing, or
/// a real file or directory that this user owns and, with `check_mode`,
/// that no other user can write.
fn path_is_private(path: &Path, check_mode: bool) -> Result<(), String> {
    use std::os::unix::fs::MetadataExt;
    let meta = match std::fs::symlink_metadata(path) {
        Ok(meta) => meta,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(format!("cannot stat staging path {}: {e}", path.display())),
    };
    if meta.file_type().is_symlink() {
        return Err(format!("staging path {} is a symlink", path.display()));
    }
    let me = std::fs::metadata("/proc/self").map(|m| m.uid()).unwrap_or(u32::MAX);
    if meta.uid() != me {
        return Err(format!(
            "staging path {} is owned by uid {}, not {me}",
            path.display(),
            meta.uid()
        ));
    }
    if check_mode && meta.mode() & 0o022 != 0 {
        return Err(format!(
            "staging path {} is group- or world-writable",
            path.display()
        ));
    }
    Ok(())
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::Digest;
    sha2::Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// The SHA256 of `path` as the HOST sees it: `sha256sum` through the same
/// portal that will run the file.
fn host_sha256(path: &str) -> Option<String> {
    let out = std::process::Command::new("flatpak-spawn")
        .args(["--host", "sha256sum", "--", path])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    String::from_utf8_lossy(&out.stdout)
        .split_whitespace()
        .next()
        .map(str::to_string)
}

/// Copy the packaged fisherman (`source`) to
/// `$XDG_CACHE_HOME/bootc-installer/fisherman` and prove that the host sees
/// the same bytes. Returns the staged path.
///
/// The path is never derived from `HOME/.cache`: `/var/home` may be private
/// to one sandbox even with `--filesystem=host`, and then the host cannot
/// see the copy. The application cache (`XDG_CACHE_HOME`, which Flatpak
/// always sets) is a path the host has too. A copy that succeeded in the
/// sandbox is not proof of that, so `host_sha` asks the host for the hash
/// before any caller may run the file as root.
pub fn stage_on_host(
    source: &str,
    cache_home: Option<&str>,
    host_sha: &dyn Fn(&str) -> Option<String>,
) -> Result<String, String> {
    use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
    let base = cache_home
        .filter(|c| !c.is_empty())
        .ok_or("XDG_CACHE_HOME is not set: there is no host-visible place to stage fisherman")?;
    let base = Path::new(base);
    let dir = base.join("bootc-installer");
    let staged = dir.join("fisherman");
    path_is_private(base, false)?;
    path_is_private(&dir, true)?;
    path_is_private(&staged, true)?;

    let bytes = std::fs::read(source).map_err(|e| format!("cannot read {source}: {e}"))?;
    std::fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)
        .map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    std::fs::write(&staged, &bytes).map_err(|e| format!("cannot write {}: {e}", staged.display()))?;
    std::fs::set_permissions(&staged, std::fs::Permissions::from_mode(0o700))
        .map_err(|e| format!("cannot chmod {}: {e}", staged.display()))?;

    let staged = staged.to_string_lossy().into_owned();
    let expected = sha256_hex(&bytes);
    match host_sha(&staged) {
        Some(seen) if seen == expected => Ok(staged),
        Some(seen) => Err(format!(
            "the staged fisherman is not byte-identical on the host: {staged} is {seen}, the package is {expected}"
        )),
        None => Err(format!("the host cannot read the staged fisherman at {staged}")),
    }
}

/// Wrap argv so it executes on the host when sandboxed.
pub fn host_command(argv: &[&str]) -> Vec<String> {
    let mut cmd: Vec<String> = Vec::new();
    if in_flatpak() {
        cmd.push("flatpak-spawn".into());
        cmd.push("--host".into());
    }
    cmd.extend(argv.iter().map(|s| s.to_string()));
    cmd
}

/// Best-effort persistence of the fisherman install log, 0600, so a failed
/// install can be diagnosed after the wizard closes. The file gets the log
/// without the recovery key (`recovery_key` is the one the done page
/// shows; redact.rs, #337). Never fails the install: logging the log is not
/// worth failing the install over.
pub fn persist_install_log(log: &str, recovery_key: &str) {
    let home = std::env::var("HOME").unwrap_or_default();
    let base = std::env::var("XDG_STATE_HOME").unwrap_or_else(|_| format!("{home}/.local/state"));
    write_install_log(&Path::new(&base).join("tuna-installer"), log, recovery_key);
}

/// persist_install_log, into `dir`.
pub fn write_install_log(dir: &Path, log: &str, recovery_key: &str) {
    use std::io::Write;

    if let Err(e) = std::fs::create_dir_all(dir) {
        tracing::warn!("could not create {}: {e}", dir.display());
        return;
    }
    let log = crate::redact::recovery_key(log, recovery_key);
    let path = dir.join("install.log");
    let write = || -> std::io::Result<()> {
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .mode(0o600)
            .open(&path)?;
        f.write_all(log.as_bytes())
    };
    if let Err(e) = write() {
        tracing::warn!("could not persist install log to {}: {e}", path.display());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn temp_workdir(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "tuna-installer-offline-{}-{}",
            std::process::id(),
            tag
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    // ── sandbox detection / command construction ──────────────────────────────

    #[test]
    fn not_in_flatpak_in_test_environment() {
        // CI and developer machines are not sandboxed; the Flatpak branch of
        // the resolver is tested through `fisherman_argv(.., true, ..)`.
        assert!(!in_flatpak());
    }

    const STAGED: &str = "/home/u/.var/app/org.example.Installer/cache/bootc-installer/fisherman";

    /// The whole table of #290: probe, validate and install, each natively,
    /// on live media and in a Flatpak.
    #[test]
    fn the_resolver_gives_one_argv_per_use_and_place() {
        // Native: the installed binary, pkexec for the install.
        assert_eq!(
            fisherman_argv(Use::Probe, false, false, ""),
            ["/usr/local/bin/fisherman", "probe", "--json"]
        );
        assert_eq!(
            fisherman_argv(Use::Validate, false, false, ""),
            ["/usr/local/bin/fisherman", "validate", "--json", "--partial", "-"]
        );
        assert_eq!(
            fisherman_argv(Use::Install, false, false, ""),
            ["bash", "-c", "pkexec /usr/local/bin/fisherman -; exit $?"]
        );
        // Native live media: sudo -n for the install only. The probe and
        // the validation never escalate.
        assert_eq!(
            fisherman_argv(Use::Install, false, true, ""),
            ["bash", "-c", "sudo -n /usr/local/bin/fisherman -; exit $?"]
        );
        assert_eq!(
            fisherman_argv(Use::Probe, false, true, ""),
            fisherman_argv(Use::Probe, false, false, "")
        );
        // Flatpak: the staged, verified copy on the host, for all three.
        // Not /usr/local/bin/fisherman, which only an ISO installs.
        assert_eq!(
            fisherman_argv(Use::Probe, true, false, STAGED),
            ["flatpak-spawn", "--host", STAGED, "probe", "--json"]
        );
        assert_eq!(
            fisherman_argv(Use::Validate, true, false, STAGED),
            ["flatpak-spawn", "--host", STAGED, "validate", "--json", "--partial", "-"]
        );
        // Not `flatpak-spawn --host pkexec`: fisherman's parent would be
        // the host's session helper, and it could never be cancelled.
        let install = format!("pkexec '{STAGED}' -; exit $?");
        assert_eq!(
            fisherman_argv(Use::Install, true, false, STAGED),
            ["flatpak-spawn", "--host", "bash", "-c", install.as_str()]
        );
        // The host escalates in a Flatpak, live media or not.
        assert_eq!(
            fisherman_argv(Use::Install, true, true, STAGED),
            fisherman_argv(Use::Install, true, false, STAGED)
        );
        for argv in [
            fisherman_argv(Use::Probe, true, false, STAGED),
            fisherman_argv(Use::Validate, true, false, STAGED),
            fisherman_argv(Use::Install, true, false, STAGED),
        ] {
            assert!(!argv.join(" ").contains("/usr/local/bin"), "{argv:?}");
        }
    }

    #[test]
    fn a_staged_path_is_one_shell_word() {
        assert_eq!(sh_quote("/a b/it's"), r"'/a b/it'\''s'");
        let argv = fisherman_argv(Use::Install, true, false, "/cache dir/fisherman");
        assert_eq!(argv[4], "pkexec '/cache dir/fisherman' -; exit $?");
    }

    #[test]
    fn outside_a_flatpak_nothing_is_staged() {
        assert_eq!(
            fisherman(Use::Probe, false).unwrap(),
            ["/usr/local/bin/fisherman", "probe", "--json"]
        );
        assert_eq!(fisherman(Use::Install, false).unwrap().last().map(String::as_str),
                   Some("pkexec /usr/local/bin/fisherman -; exit $?"));
    }

    /// No other module names a fisherman path: probe, validate and install
    /// all come through `fisherman_argv` (#290).
    #[test]
    fn only_the_resolver_names_a_fisherman_path() {
        let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        for entry in std::fs::read_dir(&src).unwrap().flatten() {
            let path = entry.path();
            if path.extension().is_none_or(|e| e != "rs") {
                continue;
            }
            let text = std::fs::read_to_string(&path).unwrap();
            // Production code only: the tests of a module name the paths
            // they expect.
            let code = text.split("#[cfg(test)]").next().unwrap();
            let name = path.file_name().unwrap().to_string_lossy().into_owned();
            for (n, line) in code.lines().enumerate() {
                let comment = line.trim_start().starts_with("//");
                if comment || name == "offline.rs" {
                    continue;
                }
                for needle in ["bin/fisherman", "\"pkexec", "\"sudo"] {
                    assert!(!line.contains(needle), "{name}:{}: {line}", n + 1);
                }
            }
        }
        let own = std::fs::read_to_string(src.join("offline.rs")).unwrap();
        let own = own.split("#[cfg(test)]").next().unwrap();
        assert_eq!(own.matches("\"/usr/local/bin/fisherman\"").count(), 1);
        assert_eq!(own.matches("\"/app/bin/fisherman\"").count(), 1);
    }

    fn fake_package(dir: &Path) -> String {
        let source = dir.join("packaged-fisherman");
        std::fs::write(&source, b"#!/bin/sh\necho fisherman\n").unwrap();
        source.to_string_lossy().into_owned()
    }

    fn sha_of_file(path: &str) -> Option<String> {
        std::fs::read(path).ok().map(|b| sha256_hex(&b))
    }

    #[test]
    fn staging_copies_to_the_application_cache_and_checks_the_host_hash() {
        use std::os::unix::fs::PermissionsExt;
        let dir = temp_workdir("stage");
        let source = fake_package(&dir);
        let cache = dir.join("cache");
        std::fs::create_dir_all(&cache).unwrap();
        let staged = stage_on_host(&source, cache.to_str(), &sha_of_file).unwrap();
        assert_eq!(staged, cache.join("bootc-installer/fisherman").to_string_lossy());
        assert_eq!(std::fs::read(&staged).unwrap(), std::fs::read(&source).unwrap());
        let mode = |p: &Path| std::fs::metadata(p).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode(Path::new(&staged)), 0o700);
        assert_eq!(mode(&cache.join("bootc-installer")), 0o700);
        // Known vector: the hash is SHA256.
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn staging_refuses_what_the_host_does_not_confirm() {
        let dir = temp_workdir("stage-bad");
        let source = fake_package(&dir);
        let cache = dir.join("cache");
        std::fs::create_dir_all(&cache).unwrap();
        // The host sees other bytes (a sandbox-private home).
        let other = |_: &str| Some("0".repeat(64));
        let err = stage_on_host(&source, cache.to_str(), &other).unwrap_err();
        assert!(err.contains("not byte-identical"), "{err}");
        // The host sees no file at all.
        let none = |_: &str| None;
        let err = stage_on_host(&source, cache.to_str(), &none).unwrap_err();
        assert!(err.contains("cannot read the staged"), "{err}");
        // No XDG_CACHE_HOME: never fall back to HOME/.cache.
        for missing in [None, Some("")] {
            let err = stage_on_host(&source, missing, &sha_of_file).unwrap_err();
            assert!(err.contains("XDG_CACHE_HOME"), "{err}");
        }
        // No packaged binary.
        assert!(stage_on_host("/nonexistent/fisherman", cache.to_str(), &sha_of_file).is_err());
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn staging_refuses_a_symlink_or_a_writable_directory() {
        use std::os::unix::fs::PermissionsExt;
        let dir = temp_workdir("stage-private");
        let source = fake_package(&dir);
        // A symlink where the binary goes: another user's file would be
        // overwritten, or theirs run as root.
        let cache = dir.join("cache-link");
        std::fs::create_dir_all(cache.join("bootc-installer")).unwrap();
        std::fs::set_permissions(cache.join("bootc-installer"), std::fs::Permissions::from_mode(0o700)).unwrap();
        std::os::unix::fs::symlink("/bin/true", cache.join("bootc-installer/fisherman")).unwrap();
        let err = stage_on_host(&source, cache.to_str(), &sha_of_file).unwrap_err();
        assert!(err.contains("symlink"), "{err}");
        // A staging directory that others can write.
        let cache = dir.join("cache-open");
        std::fs::create_dir_all(cache.join("bootc-installer")).unwrap();
        std::fs::set_permissions(cache.join("bootc-installer"), std::fs::Permissions::from_mode(0o777)).unwrap();
        let err = stage_on_host(&source, cache.to_str(), &sha_of_file).unwrap_err();
        assert!(err.contains("writable"), "{err}");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn the_wrapper_passes_stdin_output_and_status_through() {
        // The wrapper's bash for real, pkexec stubbed on PATH: what is written to the wrapper's
        // stdin is what fisherman reads, and `-` is its only argument.
        use std::io::Write;
        let dir = temp_workdir("wrapper");
        let bin = dir.join("bin");
        std::fs::create_dir_all(&bin).unwrap();
        let stub = bin.join("pkexec");
        let seen = dir.join("stdin");
        use std::os::unix::fs::PermissionsExt;
        std::fs::write(
            &stub,
            format!(
                "#!/bin/sh\nprintf '%s|%s\\n' \"$1\" \"$2\"\ncat > {}\necho to-stderr >&2\nexit 7\n",
                seen.display()
            ),
        )
        .unwrap();
        std::fs::set_permissions(&stub, std::fs::Permissions::from_mode(0o755)).unwrap();
        let argv = fisherman_argv(Use::Install, false, false, "");
        let path = format!("{}:{}", bin.display(), std::env::var("PATH").unwrap_or_default());
        let mut child = std::process::Command::new(&argv[0])
            .args(&argv[1..])
            .env("PATH", path)
            .current_dir(&dir)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(br#"{"encryption":{"type":"luks-passphrase","passphrase":"s3cret"}}"#)
            .unwrap();
        let out = child.wait_with_output().unwrap();
        assert_eq!(out.status.code(), Some(7));
        assert_eq!(String::from_utf8_lossy(&out.stdout), "/usr/local/bin/fisherman|-\n");
        assert_eq!(String::from_utf8_lossy(&out.stderr), "to-stderr\n");
        assert!(std::fs::read_to_string(&seen).unwrap().contains("s3cret"));
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn host_command_passes_through_outside_flatpak() {
        assert_eq!(host_command(&["bootc", "status"]), vec!["bootc".to_string(), "status".to_string()]);
        assert_eq!(host_command(&[]), Vec::<String>::new());
    }
}
