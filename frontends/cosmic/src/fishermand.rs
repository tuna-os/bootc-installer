//! fishermand daemon client (Varlink) with the legacy subprocess path intact.
//!
//! Backend: tuna-os/fisherman#512, `docs/FISHERMAND.md` on branch
//! `feat/fishermand-mock`. Flow ids: `shared/flow/screens.yaml`. The framing
//! follows `shared/client/rust`; it is vendored here instead of a path
//! dependency so the wasm build (`--no-default-features --features web`)
//! gains no Unix-only dependency and `Cargo.lock` stays untouched.
//!
//! Switch: `TUNA_INSTALLER_BACKEND` is the switch that all four native
//! frontends share. `daemon` talks to fishermand, and `legacy` keeps the
//! recipe + `fisherman -` subprocess (`offline::fisherman_argv`). Unset, or
//! `auto`, uses the daemon when its socket is there and the subprocess
//! otherwise. The older `TUNA_USE_FISHERMAND=1` still selects the daemon
//! when `TUNA_INSTALLER_BACKEND` names no backend. The answer is read once
//! for each process (`use_daemon`).
//!
//! Sockets: the daemon serves every interface on every socket. One socket
//! path per interface keeps gnome-setup compatibility. `FISHERMAN_SOCKET_DIR`
//! moves all four; `TUNA_FISHERMAN_SOCKET` (the name that KDE and Niri read)
//! or the older `TUNA_FISHERMAND_SOCKET` points every call at one socket
//! (tests, mock daemon with `--socket-dir`).
//!
//! Secrets: passphrases and recovery keys pass through `parameters`. This
//! module never logs a request or a reply, and `Error`'s `Display` shows the
//! error name only (see `redact` for the log path).

use serde_json::{json, Value};

/// The backend the wizard talks to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Backend {
    Daemon,
    Legacy,
}

/// The backend for the given switch values. `backend` is
/// `TUNA_INSTALLER_BACKEND`, `legacy_flag` is `TUNA_USE_FISHERMAND`.
///
/// - `daemon` or `legacy` in `backend` wins.
/// - Else `TUNA_USE_FISHERMAND=1` selects the daemon, as before.
/// - Else (`auto`, unset or unknown) the daemon is used when its socket
///   is there. The capture harness never selects the daemon this way: it
///   renders fixtures and must not depend on the machine.
pub fn backend_from(
    backend: Option<&str>,
    legacy_flag: Option<&str>,
    socket_exists: bool,
    capturing: bool,
) -> Backend {
    match backend.map(|b| b.trim().to_ascii_lowercase()).as_deref() {
        Some("daemon") => return Backend::Daemon,
        Some("legacy") => return Backend::Legacy,
        _ => {}
    }
    if legacy_flag == Some("1") {
        return Backend::Daemon;
    }
    if socket_exists && !capturing {
        Backend::Daemon
    } else {
        Backend::Legacy
    }
}

#[cfg(not(target_arch = "wasm32"))]
fn fisherman_socket_exists() -> bool {
    use std::os::unix::fs::FileTypeExt;
    std::fs::metadata(socket_path("io.tunaos.Fisherman"))
        .map(|m| m.file_type().is_socket())
        .unwrap_or(false)
}

/// A browser build has no sockets (#105).
#[cfg(target_arch = "wasm32")]
fn fisherman_socket_exists() -> bool {
    false
}

fn backend_from_env() -> Backend {
    backend_from(
        std::env::var("TUNA_INSTALLER_BACKEND").ok().as_deref(),
        std::env::var("TUNA_USE_FISHERMAND").ok().as_deref(),
        // A unit test never follows the machine: a developer with a
        // daemon socket gets the same answers as CI.
        !cfg!(test) && fisherman_socket_exists(),
        std::env::var_os("TUNA_CAPTURE_DIR").is_some(),
    )
}

/// Whether the wizard talks to fishermand (see the module text for the
/// switch). Read once: a socket that appears later must not move a
/// running wizard to another backend between two pages.
pub fn use_daemon() -> bool {
    #[cfg(test)]
    if let Some(forced) = *test_seam::DAEMON.lock().unwrap() {
        return forced;
    }
    static BACKEND: std::sync::OnceLock<Backend> = std::sync::OnceLock::new();
    *BACKEND.get_or_init(backend_from_env) == Backend::Daemon
}

/// The spec screen id (shared/flow/screens.yaml) to mock-daemon scenario
/// name (docs/FISHERMAND.md `--list-scenarios`). PR #447 names scenarios
/// after screens (`happy-tpm`); PR #513 names them after facts (`happy`).
/// Where they differ, the daemon's real name wins.
pub fn scenario_alias(name: &str) -> &str {
    match name {
        "happy-tpm" => "happy",
        "happy-no-tpm" => "no-tpm",
        "rst-present" => "rst",
        "cancel-mid-install" => "cancel",
        _ => name,
    }
}

/// Default socket paths, one per interface (FISHERMAND.md socket table).
pub fn default_socket_path(interface: &str) -> &'static str {
    match interface {
        "io.systemd.SysInstall" => "/run/systemd/io.systemd.SysInstall",
        "io.systemd.CryptEnroll" => "/run/systemd/io.systemd.CryptEnroll",
        "io.systemd.Shutdown" => "/run/systemd/io.systemd.Shutdown",
        "io.tunaos.Fisherman" => "/run/fisherman/io.tunaos.Fisherman",
        _ => "/run/fisherman/io.tunaos.Fisherman",
    }
}

/// Resolve the socket for `interface`, with the test overrides applied.
pub fn socket_path_with(
    interface: &str,
    socket_dir: Option<&str>,
    single: Option<&str>,
) -> String {
    if let Some(single) = single.filter(|s| !s.is_empty()) {
        return single.to_string();
    }
    if let Some(dir) = socket_dir.filter(|s| !s.is_empty()) {
        let leaf = default_socket_path(interface)
            .rsplit('/')
            .next()
            .unwrap_or(interface);
        return format!("{dir}/{leaf}");
    }
    default_socket_path(interface).to_string()
}

/// What `daemon_flow_tests` sets for the whole process: the backend and
/// the socket directory of its mock. The update loop reads both on worker
/// threads, so a thread-local value does not reach it. Those tests hold
/// one lock and run one at a time; no other test builds the application.
#[cfg(test)]
pub mod test_seam {
    use std::sync::Mutex;
    pub static DAEMON: Mutex<Option<bool>> = Mutex::new(None);
    pub static SOCKET_DIR: Mutex<Option<String>> = Mutex::new(None);
}

/// Resolve the socket for `interface` from the environment.
pub fn socket_path(interface: &str) -> String {
    #[cfg(test)]
    if let Some(dir) = test_seam::SOCKET_DIR.lock().unwrap().as_deref() {
        return socket_path_with(interface, Some(dir), None);
    }
    socket_path_with(
        interface,
        std::env::var("FISHERMAN_SOCKET_DIR").ok().as_deref(),
        std::env::var("TUNA_FISHERMAN_SOCKET")
            .ok()
            .filter(|s| !s.is_empty())
            .or_else(|| std::env::var("TUNA_FISHERMAND_SOCKET").ok())
            .as_deref(),
    )
}

/// A recovery key is 8 groups of 6 to 10 lowercase letters joined by `-`
/// (screens.yaml `recovery_key_shape`; the daemon emits 8 of 8). Match by
/// shape, never by a node named `Recovery Key` (shared/flow README test
/// contract).
pub fn is_recovery_key_shape(s: &str) -> bool {
    let groups: Vec<&str> = s.split('-').collect();
    groups.len() == 8
        && groups.iter().all(|g| {
            (6..=10).contains(&g.len()) && g.bytes().all(|b| b.is_ascii_lowercase())
        })
}

#[cfg(not(target_arch = "wasm32"))]
mod transport {
    use super::*;
    use std::fmt;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixStream;
    use std::path::Path;

    /// The service answered with an error reply. Holds the parameters so a
    /// caller can read error details, but `Display` shows the name only:
    /// parameters may carry secrets.
    #[derive(Debug)]
    pub enum Error {
        /// Callers match on the name today; the recovery-key and handoff
        /// pages will read the details. Kept, not logged, by design.
        #[allow(dead_code)]
        Varlink { name: String, parameters: Value },
        Transport(String),
    }

    impl fmt::Display for Error {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            match self {
                Error::Varlink { name, .. } => write!(f, "{name}"),
                Error::Transport(e) => write!(f, "transport: {e}"),
            }
        }
    }

    impl std::error::Error for Error {}

    impl From<std::io::Error> for Error {
        fn from(e: std::io::Error) -> Self {
            Error::Transport(e.to_string())
        }
    }

    /// One Varlink connection. One call at a time; open a second connection
    /// to cancel a running install.
    pub struct Connection {
        writer: UnixStream,
        reader: BufReader<UnixStream>,
    }

    impl Connection {
        pub fn connect(path: impl AsRef<Path>) -> Result<Self, Error> {
            let stream = UnixStream::connect(path)?;
            Ok(Self {
                reader: BufReader::new(stream.try_clone()?),
                writer: stream,
            })
        }

        fn send(&mut self, request: Value) -> Result<(), Error> {
            let mut wire =
                serde_json::to_vec(&request).map_err(|e| Error::Transport(e.to_string()))?;
            wire.push(0);
            self.writer.write_all(&wire)?;
            Ok(())
        }

        /// Read one NUL-terminated reply. Returns (parameters, continues).
        fn receive(&mut self) -> Result<(Value, bool), Error> {
            let mut raw = Vec::new();
            let n = self.reader.read_until(0, &mut raw)?;
            if n == 0 || raw.last() != Some(&0) {
                return Err(Error::Transport("the service closed the connection".into()));
            }
            raw.pop();
            let message: serde_json::Map<String, Value> = serde_json::from_slice(&raw)
                .map_err(|_| Error::Transport("a message is not a JSON object".into()))?;
            let parameters = message
                .get("parameters")
                .cloned()
                .unwrap_or_else(|| json!({}));
            if let Some(name) = message.get("error").and_then(Value::as_str) {
                return Err(Error::Varlink {
                    name: name.to_string(),
                    parameters,
                });
            }
            let continues = message
                .get("continues")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            Ok((parameters, continues))
        }

        /// A call with one reply.
        pub fn call(&mut self, method: &str, parameters: Value) -> Result<Value, Error> {
            self.send(json!({ "method": method, "parameters": parameters }))?;
            Ok(self.receive()?.0)
        }

        /// A streaming call. `on_reply` runs for every reply, the last one
        /// included. Return `false` to stop early; drop the connection after.
        pub fn call_more(
            &mut self,
            method: &str,
            parameters: Value,
            mut on_reply: impl FnMut(Value) -> bool,
        ) -> Result<(), Error> {
            self.send(json!({ "method": method, "parameters": parameters, "more": true }))?;
            loop {
                let (reply, continues) = self.receive()?;
                if !on_reply(reply) || !continues {
                    return Ok(());
                }
            }
        }
    }

    /// Open the socket for `interface`.
    pub fn connect(interface: &str) -> Result<Connection, Error> {
        Connection::connect(super::socket_path(interface))
    }

    // ------------------------------------------------ typed daemon calls ----

    const FISHERMAN: &str = "io.tunaos.Fisherman";
    // The disk page wires ListCandidateDevices, the recovery-key page wires
    // CryptEnroll. Allowed until those screen commits land.
    #[allow(dead_code)]
    const SYSINSTALL: &str = "io.systemd.SysInstall";
    #[allow(dead_code)]
    const CRYPTENROLL: &str = "io.systemd.CryptEnroll";
    const SHUTDOWN: &str = "io.systemd.Shutdown";

    pub fn requirements(conn: &mut Connection) -> Result<Value, Error> {
        conn.call(&format!("{FISHERMAN}.Requirements"), json!({}))
    }

    pub fn probe(conn: &mut Connection) -> Result<Value, Error> {
        conn.call(&format!("{FISHERMAN}.Probe"), json!({}))
    }

    pub fn validate(conn: &mut Connection, config: Value, partial: bool) -> Result<Value, Error> {
        conn.call(
            &format!("{FISHERMAN}.Validate"),
            json!({ "config": config, "partial": partial }),
        )
    }

    /// Record the target choices (`ConfigureTarget`): user, hostname and
    /// region picks from `configure_params`. The optional privacy object
    /// (`{"locationServices": bool}`) goes only when the user changed it
    /// on the timezone page (ruling on #442).
    pub fn configure_target(conn: &mut Connection, params: Value) -> Result<Value, Error> {
        conn.call(&format!("{FISHERMAN}.ConfigureTarget"), params)
    }

    /// Stream install events. `on_event` sees every reply, the terminal one
    /// included; return `false` to stop early.
    pub fn install(
        conn: &mut Connection,
        config: Value,
        confirmed: bool,
        on_event: impl FnMut(Value) -> bool,
    ) -> Result<(), Error> {
        conn.call_more(
            &format!("{FISHERMAN}.Install"),
            json!({ "config": config, "confirmed": confirmed }),
            on_event,
        )
    }

    // The handoff page wires this.
    #[allow(dead_code)]
    pub fn handoff(conn: &mut Connection, mode: Option<&str>) -> Result<Value, Error> {
        let mut params = serde_json::Map::new();
        if let Some(mode) = mode {
            params.insert("mode".into(), Value::from(mode));
        }
        conn.call(&format!("{FISHERMAN}.Handoff"), Value::Object(params))
    }

    pub fn cancel(conn: &mut Connection) -> Result<Value, Error> {
        conn.call(&format!("{FISHERMAN}.Cancel"), json!({}))
    }

    /// Candidate disks without subscription: one stream, ends by itself.
    // The disk page wires this.
    #[allow(dead_code)]
    pub fn list_candidate_devices(conn: &mut Connection) -> Result<Vec<Value>, Error> {
        let mut devices = Vec::new();
        conn.call_more(
            &format!("{SYSINSTALL}.ListCandidateDevices"),
            json!({}),
            |reply| {
                devices.push(reply);
                true
            },
        )?;
        Ok(devices)
    }

    pub fn make_recovery_key(conn: &mut Connection) -> Result<String, Error> {
        let reply = conn.call(&format!("{CRYPTENROLL}.MakeRecoveryKey"), json!({}))?;
        reply
            .get("recoveryKey")
            .and_then(Value::as_str)
            .map(str::to_string)
            .ok_or_else(|| Error::Transport("MakeRecoveryKey missed recoveryKey".into()))
    }

    /// Enrol a recovery key into the installed volume (screens.yaml
    /// `recovery-key`): the key made when the page opened, unlocked with
    /// the install passphrase (empty when the disk sealed to PCR 7).
    pub fn enroll_recovery(
        conn: &mut Connection,
        node: &str,
        recovery_key: &str,
        unlock_password: &str,
    ) -> Result<Value, Error> {
        conn.call(
            &format!("{CRYPTENROLL}.Enroll"),
            json!({
                "node": node,
                "mechanism": "recovery",
                "recoveryKey": recovery_key,
                "unlockPassword": unlock_password,
            }),
        )
    }

    pub fn reboot(conn: &mut Connection, skip_inhibitors: bool) -> Result<(), Error> {
        conn.call(
            &format!("{SHUTDOWN}.Reboot"),
            json!({ "skipInhibitors": skip_inhibitors }),
        )?;
        Ok(())
    }

    pub fn power_off(conn: &mut Connection, skip_inhibitors: bool) -> Result<(), Error> {
        conn.call(
            &format!("{SHUTDOWN}.PowerOff"),
            json!({ "skipInhibitors": skip_inhibitors }),
        )?;
        Ok(())
    }

    // The handoff page wires this (EL10 soft-reboot).
    #[allow(dead_code)]
    pub fn soft_reboot(conn: &mut Connection, skip_inhibitors: bool) -> Result<(), Error> {
        conn.call(
            &format!("{SHUTDOWN}.SoftReboot"),
            json!({ "skipInhibitors": skip_inhibitors }),
        )?;
        Ok(())
    }
}

#[cfg(not(target_arch = "wasm32"))]
pub use transport::*;

/// The browser build has no daemon and no sockets (#105). Same names, so
/// callers keep one code path; every call fails closed.
#[cfg(target_arch = "wasm32")]
pub mod stub {
    use super::Value;

    #[derive(Debug)]
    pub enum Error {
        Transport(String),
    }

    impl std::fmt::Display for Error {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            match self {
                Error::Transport(e) => write!(f, "transport: {e}"),
            }
        }
    }

    impl std::error::Error for Error {}

    pub struct Connection;

    pub fn connect(_interface: &str) -> Result<Connection, Error> {
        Err(Error::Transport("no daemon in a browser build".into()))
    }

    macro_rules! unavailable {
        ($($name:ident($($arg:tt)*) -> $ret:ty;)*) => {
            $(pub fn $name($($arg)*) -> Result<$ret, Error> {
                Err(Error::Transport("no daemon in a browser build".into()))
            })*
        };
    }

    unavailable! {
        requirements(_conn: &mut Connection) -> Value;
        probe(_conn: &mut Connection) -> Value;
        validate(_conn: &mut Connection, _config: Value, _partial: bool) -> Value;
        configure_target(_conn: &mut Connection, _params: Value) -> Value;
        handoff(_conn: &mut Connection, _mode: Option<&str>) -> Value;
        cancel(_conn: &mut Connection) -> Value;
        list_candidate_devices(_conn: &mut Connection) -> Vec<Value>;
        make_recovery_key(_conn: &mut Connection) -> String;
        reboot(_conn: &mut Connection, _skip: bool) -> ();
        power_off(_conn: &mut Connection, _skip: bool) -> ();
        soft_reboot(_conn: &mut Connection, _skip: bool) -> ();
    }
}

#[cfg(target_arch = "wasm32")]
pub use stub::*;

/// How one daemon install event moves the install page. The last reply of
/// the stream carries a terminal event; a dropped connection cancels.
#[derive(Debug, PartialEq, Eq)]
pub enum Terminal {
    Continue,
    Complete,
    Cancelled,
    Failed,
}

/// Fold one `Install` event into the progress state and the log.
///
/// Event shape: FISHERMAND.md install table (`event`, `stepId`,
/// `stepIndex`, `totalSteps`, `overallPct`, `message`, `reason`,
/// `nextAction`). The recovery key never arrives here: gnome-setup makes it
/// when the recovery page opens (`CryptEnroll.MakeRecoveryKey`).
pub fn apply_install_event(
    progress: &mut crate::progress::Progress,
    log: &mut String,
    event: &Value,
) -> Terminal {
    let str_of = |key: &str| event.get(key).and_then(Value::as_str).unwrap_or("");
    match str_of("event") {
        "step_started" | "progress" | "step_finished" => {
            // `stepIndex` starts at 1 (fisherman's reporter.go). The cleanup
            // after a failure has no total: it is not a step of the install.
            if let Some(total) = event.get("totalSteps").and_then(Value::as_u64).filter(|t| *t > 0) {
                progress.total_steps = total;
                if let Some(index) = event.get("stepIndex").and_then(Value::as_u64) {
                    progress.step = index;
                }
            }
            if let Some(pct) = event.get("overallPct").and_then(Value::as_u64) {
                progress.fraction = (pct.min(100) as f32) / 100.0;
            }
            let id = str_of("stepId");
            if !id.is_empty() {
                progress.step_id = id.to_string();
                progress.step_name = step_words(id);
            }
            let message = str_of("message");
            if !message.is_empty() {
                log.push_str(&message);
                log.push('\n');
            } else if str_of("event") == "step_started" && !id.is_empty() {
                // The daemon can send a step with no message. The log card
                // then names the step, so the card is not empty.
                log.push_str(&progress.step_label(crate::branding::get()));
                log.push('\n');
            }
            Terminal::Continue
        }
        "warning" => {
            let message = str_of("message");
            if !message.is_empty() {
                log.push_str(&message);
                log.push('\n');
            }
            Terminal::Continue
        }
        "cancelled" => Terminal::Cancelled,
        "complete" => {
            progress.fraction = 1.0;
            Terminal::Complete
        }
        "failed" => {
            progress.error = Some(crate::progress::InstallError {
                message: str_of("message").to_string(),
                code: str_of("reason").to_string(),
                field: String::new(),
                step_id: str_of("stepId").to_string(),
                // The daemon sends no `disk_changed`: the step says it.
                disk_changed: disk_changed_at(str_of("stepId")),
                cleanup: None,
            });
            Terminal::Failed
        }
        _ => Terminal::Continue,
    }
}

/// The words for a daemon step that the branding copy has no `step_<id>` line
/// for: the line of the recipe step that does the same work.
fn step_words(id: &str) -> String {
    let like = match id {
        "validate_device" => "step_prepare_disk",
        "post_fixups" => "step_configure",
        "bootloader" => "step_format_efi",
        "cleanup" => "step_finalize",
        _ => return id.to_string(),
    };
    let words = crate::branding::get().text(like);
    if words.is_empty() { id.to_string() } else { words }
}

/// What a disk is called: vendor and model, without the PCI vendor id that
/// virtio puts where a vendor belongs ("0x1af4"). A disk that names neither
/// is called after its bus; the row has its path and its size.
fn disk_title(vendor: &str, model: &str, bus: &str, path: &str) -> String {
    let pci = |s: &str| {
        s.strip_prefix("0x")
            .is_some_and(|hex| !hex.is_empty() && hex.chars().all(|c| c.is_ascii_hexdigit()))
    };
    let named: Vec<&str> = [vendor.trim(), model.trim()]
        .into_iter()
        .filter(|s| !s.is_empty() && !pci(s))
        .collect();
    if !named.is_empty() {
        named.join(" ")
    } else if bus.is_empty() {
        path.to_string()
    } else {
        crate::i18n::tr_with(crate::ui::copy::DISK_BUS_TITLE, &[("bus", bus)])
    }
}

/// The bus as people write it.
fn bus_label(transport: &str) -> String {
    match transport {
        "ata" => "ATA".into(),
        "sata" => "SATA".into(),
        "nvme" => "NVMe".into(),
        "usb" => "USB".into(),
        "mmc" => "MMC".into(),
        "virtio" => "VirtIO".into(),
        other => other.to_uppercase(),
    }
}

/// The install's daemon `Config` from the recipe (IDL `Config`).
///
/// Only fields the daemon owns: disk, encryption, user, hostname, and
/// the wipe-or-free choice as `installMode`. The image, filesystem,
/// bootloader and Flatpaks stay in the recipe for the legacy path: the
/// daemon partitions and configures, it does not fetch an image. Groups
/// have no daemon field yet, so the account's groups travel only through
/// `ConfigureTarget` once the daemon names one.
pub fn daemon_config(recipe: &crate::Recipe, install_mode: Option<crate::InstallMode>) -> Value {
    let mut config = serde_json::Map::new();
    if !recipe.disk.is_empty() {
        config.insert("disk".into(), Value::from(recipe.disk.clone()));
    }
    if let Some(mode) = install_mode {
        config.insert("installMode".into(), Value::from(mode.daemon_name()));
    }
    let mut encryption = serde_json::Map::new();
    encryption.insert(
        "type".into(),
        Value::from(map_encryption_type(&recipe.encryption.enc_type)),
    );
    if !recipe.encryption.passphrase.is_empty() {
        encryption.insert(
            "passphrase".into(),
            Value::from(recipe.encryption.passphrase.clone()),
        );
    }
    config.insert("encryption".into(), Value::Object(encryption));
    if let Some(user) = daemon_user(recipe) {
        config.insert("user".into(), user);
    }
    if !recipe.hostname.is_empty() {
        config.insert("hostname".into(), Value::from(recipe.hostname.clone()));
    }
    Value::Object(config)
}

/// The daemon `User` object from the recipe, shared by `daemon_config`
/// and `configure_params`. The password travels only inside the Varlink
/// parameters; nothing logs it.
fn daemon_user(recipe: &crate::Recipe) -> Option<Value> {
    let user = recipe.user.as_ref()?;
    let mut u = serde_json::Map::new();
    u.insert("username".into(), Value::from(user.username.clone()));
    if !user.fullname.is_empty() {
        u.insert("fullName".into(), Value::from(user.fullname.clone()));
    }
    if !user.password.is_empty() {
        u.insert("password".into(), Value::from(user.password.clone()));
    }
    // Groups have no daemon field: membership of `wheel` is `admin`.
    u.insert("admin".into(), Value::from(user.groups.iter().any(|g| g == "wheel")));
    Some(Value::Object(u))
}

/// The `ConfigureTarget` parameters from the recipe: user, hostname, and
/// the region picks (locale, keymap, time zone). Empty picks stay out, so
/// the image keeps its own values. `location_services` is the switch on
/// the timezone page: `None` while the user did not move it, and then no
/// privacy object goes and the daemon default stands (ruling on #442).
pub fn configure_params(recipe: &crate::Recipe, location_services: Option<bool>) -> Value {
    let mut params = serde_json::Map::new();
    if let Some(user) = daemon_user(recipe) {
        params.insert("user".into(), user);
    }
    if !recipe.hostname.is_empty() {
        params.insert("hostname".into(), Value::from(recipe.hostname.clone()));
    }
    if !recipe.locale.is_empty() {
        params.insert("locale".into(), Value::from(recipe.locale.clone()));
    }
    if let Some(kb) = &recipe.keyboard {
        if !kb.layout.is_empty() {
            let keymap = if kb.variant.is_empty() {
                kb.layout.clone()
            } else {
                // The daemon reads `layout-variant` (`de-nodeadkeys`); a comma
                // is `keymap_invalid`.
                format!("{}-{}", kb.layout, kb.variant)
            };
            params.insert("keymap".into(), Value::from(keymap));
        }
    }
    if !recipe.timezone.is_empty() {
        params.insert("timeZone".into(), Value::from(recipe.timezone.clone()));
    }
    if let Some(on) = location_services {
        params.insert("privacy".into(), json!({ "locationServices": on }));
    }
    Value::Object(params)
}

/// The recipe's encryption names are fisherman's encryption-choices.json
/// names (shared/recipe); the daemon's `Encryption.type` is `(none,
/// luks_passphrase, tpm2_luks, tpm2_luks_passphrase)`. Unknown names pass
/// through: the daemon's `Validate` owns the error, not this map.
fn map_encryption_type(enc_type: &str) -> String {
    // Recipe types use dashes (shared/recipe/encryption-choices.json), the
    // daemon underscores; the names come from the file, not from a list here.
    enc_type.replace('-', "_")
}

/// `probe::Facts` from a daemon `Probe` reply plus its `Requirements`
/// reply. The mock's gate ids are `ram`, `cpu`, `firmware`; the wizard's
/// gates are `ram`, `cpu`, `uefi` (`hardware::gate_for`).
pub fn daemon_probe_to_facts(probe: &Value, gates: &Value) -> Result<crate::probe::Facts, String> {
    let eligible: Vec<&Value> = probe
        .get("disks")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
        .iter()
        .filter(|d| d.get("eligible").and_then(Value::as_bool) == Some(true))
        .collect();
    let disks = eligible
        .iter()
        .map(|d| {
            let str_of = |key: &str| d.get(key).and_then(Value::as_str).unwrap_or("").to_string();
            let model = str_of("model");
            let vendor = str_of("vendor");
            let bus = bus_label(&str_of("transport"));
            let title = disk_title(&vendor, &model, &bus, &str_of("path"));
            crate::model::DiskInfo {
                title,
                path: str_of("path"),
                model,
                size_label: str_of("sizeLabel"),
                transport_label: bus,
                removable: d.get("removable").and_then(Value::as_bool).unwrap_or(false),
            }
        })
        .collect();
    // Same order as `disks`: the wipe-or-free page pairs them by index.
    let disk_data = eligible
        .iter()
        .map(|d| {
            let data = d.get("existingData");
            let has_data = data
                .map(|e| {
                    e.get("hasPartitionTable").and_then(Value::as_bool).unwrap_or(false)
                        || e.get("hasLuks").and_then(Value::as_bool).unwrap_or(false)
                        || !e
                            .get("operatingSystems")
                            .and_then(Value::as_array)
                            .map(Vec::as_slice)
                            .unwrap_or(&[])
                            .is_empty()
                })
                .unwrap_or(false);
            crate::probe::DiskData {
                has_data,
                free_bytes: d.get("freeBytes").and_then(Value::as_u64).unwrap_or(0),
                minimal_bytes: d.get("minimalSizeBytes").and_then(Value::as_u64).unwrap_or(0),
                // Only a GPT can share the disk with a second system.
                conflicting_label: data
                    .and_then(|e| e.get("partitionTableType"))
                    .and_then(Value::as_str)
                    .is_some_and(|t| !t.is_empty() && t != "gpt"),
            }
        })
        .collect();
    let unmet = gates
        .get("gates")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
        .iter()
        .filter(|g| g.get("ok").and_then(Value::as_bool) != Some(true))
        .map(|g| match g.get("id").and_then(Value::as_str) {
            Some("firmware") => "uefi".to_string(),
            Some(id) => id.to_string(),
            None => String::new(),
        })
        .filter(|id| !id.is_empty())
        .collect();
    Ok(crate::probe::Facts {
        disks,
        tpm_usable: probe
            .pointer("/tpm/usable")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        unmet,
        is_live: probe
            .pointer("/live/isLive")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        live_image: probe
            .pointer("/live/liveImage")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        // The daemon's Probe has no offline stores yet.
        offline_images: Vec::new(),
        intel_rst: probe
            .pointer("/intelRst/detected")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        disk_data,
        handoff_mode: handoff_mode_of(probe.pointer("/handoff/mode").and_then(Value::as_str))
            .to_string(),
        handoff_reason: probe
            .pointer("/handoff/reason")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        raw: serde_json::to_string(probe).map_err(|e| format!("cannot reserialize Probe: {e}"))?,
    })
}

/// The handoff mode for a `handoff.mode` of the Probe reply. The daemon
/// decides; a missing or unknown value means reboot. The wire spells the
/// soft reboot with an underscore (fisherman/internal/handoff:
/// ModeSoftReboot) and the ruling on #512 with a dash: both are the same
/// mode here.
pub fn handoff_mode_of(mode: Option<&str>) -> &'static str {
    match mode {
        Some("migrate") => "migrate",
        Some("soft_reboot") | Some("soft-reboot") => "soft_reboot",
        _ => "reboot",
    }
}

/// Whether a failed daemon step changed the disk, from its step id: only
/// `validate_device` runs before the first write. `None` when the event
/// names no step.
pub fn disk_changed_at(step_id: &str) -> Option<bool> {
    match step_id {
        "" => None,
        "validate_device" => Some(false),
        _ => Some(true),
    }
}

/// The failure reason for a daemon install that ended with no terminal
/// event. `error` is the text of the `InstallFinished` error:
/// `ConfigureTarget: <code>` when the daemon refused a choice, a Varlink
/// error name when it refused the call, and a transport note otherwise.
pub fn stream_failure_reason(error: &str) -> &str {
    if let Some(code) = error.strip_prefix("ConfigureTarget: ") {
        return code;
    }
    let name = error.strip_prefix("ConfigureTarget failed: ").unwrap_or(error);
    if name.starts_with("io.tunaos.") || name.starts_with("org.varlink.") || name.starts_with("io.systemd.") {
        return name;
    }
    "daemon_unreachable"
}

/// The options page's problems from a daemon `Validate` reply. Same shape
/// as `validate::Problem`, so the page renders them unchanged.
pub fn daemon_problems(reply: &Value) -> Vec<crate::validate::Problem> {
    reply
        .get("errors")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
        .iter()
        .filter_map(|e| serde_json::from_value(e.clone()).ok())
        .collect()
}

/// The options page's partial recipe as a daemon `Config`: only the keys
/// `Validate` owns (hostname, encryption, user, disk). The recipe's
/// filesystem and image keys have no daemon field. Passphrases stay out of
/// logs by the same rule as every other call here.
pub fn daemon_config_from_partial(partial: &Value) -> Value {
    let mut config = serde_json::Map::new();
    for key in ["disk", "hostname"] {
        if let Some(value) = partial.get(key) {
            config.insert(key.into(), value.clone());
        }
    }
    if let Some(enc) = partial.get("encryption").and_then(Value::as_object) {
        let mut mapped = serde_json::Map::new();
        if let Some(t) = enc.get("type").and_then(Value::as_str) {
            mapped.insert("type".into(), Value::from(map_encryption_type(t)));
        }
        if let Some(p) = enc.get("passphrase") {
            mapped.insert("passphrase".into(), p.clone());
        }
        config.insert("encryption".into(), Value::Object(mapped));
    }
    if let Some(user) = partial.get("user") {
        config.insert("user".into(), user.clone());
    }
    Value::Object(config)
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn daemon_switch_defaults_to_legacy_subprocess() {
        // The switch is opt-in: an unset or other value keeps the recipe
        // path, so nothing regresses until the daemon ships.
        assert!(!socket_path_with("io.tunaos.Fisherman", None, None).is_empty());
        assert_eq!(
            socket_path_with("io.tunaos.Fisherman", None, None),
            "/run/fisherman/io.tunaos.Fisherman"
        );
        assert_eq!(
            socket_path_with(
                "io.systemd.SysInstall",
                Some("/tmp/mock"),
                None
            ),
            "/tmp/mock/io.systemd.SysInstall"
        );
        assert_eq!(
            socket_path_with("io.tunaos.Fisherman", Some("/tmp/mock"), Some("/tmp/one.sock")),
            "/tmp/one.sock"
        );
    }

    #[test]
    fn the_shared_switch_selects_the_backend() {
        use Backend::{Daemon, Legacy};
        // An explicit value wins over everything else.
        assert_eq!(backend_from(Some("daemon"), None, false, false), Daemon);
        assert_eq!(backend_from(Some("daemon"), None, false, true), Daemon);
        assert_eq!(backend_from(Some(" Daemon "), None, false, false), Daemon);
        assert_eq!(backend_from(Some("legacy"), Some("1"), true, false), Legacy);
        // The old switch still works when the shared one names no backend.
        assert_eq!(backend_from(None, Some("1"), false, false), Daemon);
        assert_eq!(backend_from(Some("auto"), Some("1"), false, false), Daemon);
        assert_eq!(backend_from(None, Some("0"), false, false), Legacy);
        assert_eq!(backend_from(None, Some("true"), false, false), Legacy);
        // auto, unset and unknown values follow the socket.
        for auto in [None, Some("auto"), Some(""), Some("bogus")] {
            assert_eq!(backend_from(auto, None, true, false), Daemon, "{auto:?}");
            assert_eq!(backend_from(auto, None, false, false), Legacy, "{auto:?}");
            // The capture renders fixtures: a socket on the machine does
            // not move it to the daemon.
            assert_eq!(backend_from(auto, None, true, true), Legacy, "{auto:?}");
        }
    }

    #[test]
    fn one_socket_override_wins_over_the_directory() {
        // TUNA_FISHERMAN_SOCKET (and the older TUNA_FISHERMAND_SOCKET)
        // reach socket_path_with as `single`.
        assert_eq!(
            socket_path_with("io.systemd.Shutdown", Some("/tmp/mock"), Some("/tmp/one.sock")),
            "/tmp/one.sock"
        );
        assert_eq!(
            socket_path_with("io.systemd.Shutdown", Some("/tmp/mock"), Some("")),
            "/tmp/mock/io.systemd.Shutdown"
        );
    }

    #[test]
    fn privacy_goes_to_configure_target_only_when_the_user_changed_it() {
        let mut recipe = crate::Recipe::default();
        recipe.timezone = "Europe/Berlin".into();
        // Untouched switch: no privacy object, the daemon default stands.
        let untouched = configure_params(&recipe, None);
        assert!(untouched.get("privacy").is_none(), "{untouched}");
        assert_eq!(untouched["timeZone"], Value::from("Europe/Berlin"));
        // Turned on, and turned off again: both are a change.
        let on = configure_params(&recipe, Some(true));
        assert_eq!(on["privacy"], json!({"locationServices": true}));
        let off = configure_params(&recipe, Some(false));
        assert_eq!(off["privacy"], json!({"locationServices": false}));
    }

    #[test]
    fn the_keymap_and_the_admin_flag_are_in_the_daemons_form() {
        let mut recipe = crate::Recipe::default();
        recipe.choose_keyboard("de");
        assert_eq!(configure_params(&recipe, None)["keymap"], Value::from("de"));
        recipe.keyboard.as_mut().unwrap().variant = "nodeadkeys".into();
        assert_eq!(configure_params(&recipe, None)["keymap"], Value::from("de-nodeadkeys"));
        recipe.user = Some(crate::model::User {
            username: "alex".into(),
            groups: vec!["wheel".into(), "audio".into()],
            ..Default::default()
        });
        assert_eq!(configure_params(&recipe, None)["user"]["admin"], Value::Bool(true));
        recipe.user.as_mut().unwrap().groups = vec!["audio".into()];
        assert_eq!(daemon_config(&recipe, None)["user"]["admin"], Value::Bool(false));
    }

    #[test]
    fn handoff_mode_accepts_both_spellings_and_falls_back_to_reboot() {
        assert_eq!(handoff_mode_of(Some("migrate")), "migrate");
        assert_eq!(handoff_mode_of(Some("soft_reboot")), "soft_reboot");
        assert_eq!(handoff_mode_of(Some("soft-reboot")), "soft_reboot");
        assert_eq!(handoff_mode_of(Some("reboot")), "reboot");
        assert_eq!(handoff_mode_of(Some("kexec")), "reboot");
        assert_eq!(handoff_mode_of(None), "reboot");
    }

    /// shared/probe/handoff-cases.json: the cases every frontend meets.
    #[test]
    fn handoff_mode_meets_the_shared_cases() {
        let file: Value = serde_json::from_str(include_str!(
            "../../../shared/probe/handoff-cases.json"
        ))
        .unwrap();
        let cases = file["cases"].as_array().unwrap();
        assert!(!cases.is_empty());
        for case in cases {
            assert_eq!(
                handoff_mode_of(case["wire_mode"].as_str()),
                case["mode"].as_str().unwrap(),
                "{}",
                case["name"]
            );
        }
    }

    #[test]
    fn a_failed_step_says_whether_the_disk_changed() {
        assert_eq!(disk_changed_at("validate_device"), Some(false));
        assert_eq!(disk_changed_at("partition"), Some(true));
        assert_eq!(disk_changed_at("install_os"), Some(true));
        assert_eq!(disk_changed_at(""), None);
        let mut progress = crate::progress::Progress::new("product");
        let mut log = String::new();
        let event = json!({"event": "failed", "stepId": "install_os",
            "reason": "device_lost", "message": "gone", "overallPct": 40});
        assert_eq!(apply_install_event(&mut progress, &mut log, &event), Terminal::Failed);
        let error = progress.error.as_ref().unwrap();
        assert_eq!(error.code, "device_lost");
        assert_eq!(error.disk_changed, Some(true));
        assert_eq!(
            crate::progress::failure_lines(progress.error.as_ref()),
            vec!["done_failed_disk_changed"]
        );
    }

    #[test]
    fn a_stream_that_ends_with_no_terminal_event_names_its_reason() {
        assert_eq!(stream_failure_reason("ConfigureTarget: locale_invalid"), "locale_invalid");
        assert_eq!(
            stream_failure_reason("io.tunaos.Fisherman.InstallInProgress"),
            "io.tunaos.Fisherman.InstallInProgress"
        );
        assert_eq!(
            stream_failure_reason("ConfigureTarget failed: org.varlink.service.PermissionDenied"),
            "org.varlink.service.PermissionDenied"
        );
        assert_eq!(stream_failure_reason("cannot reach fishermand: transport: no socket"), "daemon_unreachable");
        assert_eq!(stream_failure_reason("transport: connection reset"), "daemon_unreachable");
    }

    #[test]
    fn spec_names_map_to_real_mock_scenario_names() {
        // PR #447 names scenarios after screens, PR #513 after facts.
        assert_eq!(scenario_alias("happy-tpm"), "happy");
        assert_eq!(scenario_alias("happy-no-tpm"), "no-tpm");
        assert_eq!(scenario_alias("rst-present"), "rst");
        assert_eq!(scenario_alias("cancel-mid-install"), "cancel");
        // Identity for the rest: existing-data, device-lost, repart-error.
        assert_eq!(scenario_alias("device-lost"), "device-lost");
        assert_eq!(scenario_alias("existing-data"), "existing-data");
        assert_eq!(scenario_alias("repart-error"), "repart-error");
    }

    #[test]
    fn recovery_key_shape_matches_daemon_format() {
        // The daemon emits 8 groups of 8 lowercase letters (FISHERMAND.md);
        // the shared contract allows 6 to 10 (screens.yaml).
        assert!(is_recovery_key_shape("mktardcw-nnhufnbx-kwnvoixz-ahhhuahf-xqwqwqwq-yzqwqwqw-abcqwqwq-defqwqwq"));
        assert!(is_recovery_key_shape("mktard-nnhufn-bxkwvo-oixzah-hhuahf-xqwqwq-yzqwqw-abcpqw"));
        assert!(!is_recovery_key_shape("Recovery Key"));
        assert!(!is_recovery_key_shape("mkta-rdcw"));
        // The capture fixture's 4-letter groups are synthetic, never
        // emitted: the shape must not match them.
        assert!(!is_recovery_key_shape("mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf"));
        assert!(!is_recovery_key_shape("MKTAQWCD-NNHUQWCD-FNBXQWCD-KWNVQWCD-OIXZQWCD-AHHHQWCD-UAHFQWCD-XQWQQWCD"));
    }

    #[test]
    fn install_events_move_progress_and_end_cleanly() {
        let mut progress = crate::progress::Progress::new("product");
        let mut log = String::new();
        let started = serde_json::json!({
            "event": "step_started", "stepId": "partition",
            "stepIndex": 1, "totalSteps": 9, "overallPct": 11,
        });
        assert_eq!(apply_install_event(&mut progress, &mut log, &started), Terminal::Continue);
        assert_eq!(progress.step, 1);
        assert_eq!(progress.total_steps, 9);
        assert_eq!(progress.step_id, "partition");

        let failed = serde_json::json!({
            "event": "failed", "stepId": "install_os", "reason": "device_lost",
            "message": "the disk went away", "nextAction": "retry",
        });
        assert_eq!(apply_install_event(&mut progress, &mut log, &failed), Terminal::Failed);
        let error = progress.error.as_ref().expect("failed sets the error");
        assert_eq!(error.code, "device_lost");
        assert_eq!(error.step_id, "install_os");

        let mut done = crate::progress::Progress::new("product");
        let mut done_log = String::new();
        let complete = serde_json::json!({ "event": "complete", "overallPct": 100 });
        assert_eq!(
            apply_install_event(&mut done, &mut done_log, &complete),
            Terminal::Complete
        );
        assert_eq!(done.fraction, 1.0);

        let cancelled = serde_json::json!({ "event": "cancelled" });
        assert_eq!(
            apply_install_event(&mut done, &mut done_log, &cancelled),
            Terminal::Cancelled
        );
    }

    #[test]
    fn the_log_has_words_and_no_step_ids() {
        let mut progress = crate::progress::Progress::new("product");
        let mut log = String::new();
        for (index, id) in ["validate_device", "partition", "post_fixups", "bootloader"].iter().enumerate() {
            let event = serde_json::json!({"event": "step_started", "stepId": id,
                "stepIndex": index + 1, "totalSteps": 10, "overallPct": 0});
            apply_install_event(&mut progress, &mut log, &event);
        }
        assert_eq!((progress.step, progress.total_steps), (4, 10));
        assert_eq!(log.lines().count(), 4);
        assert!(!log.contains('_'), "{log}");
        // The cleanup after a failure counts for nothing.
        let cleanup = serde_json::json!({"event": "step_started", "stepId": "cleanup",
            "stepIndex": 0, "totalSteps": 0, "overallPct": 4});
        apply_install_event(&mut progress, &mut log, &cleanup);
        assert_eq!((progress.step, progress.total_steps), (4, 10));
    }

    #[test]
    fn a_disk_is_never_called_by_a_pci_id() {
        assert_eq!(disk_title("0x1af4", "", "VirtIO", "/dev/vda"), "VirtIO disk");
        assert_eq!(disk_title("0x1af4", "", "", "/dev/vda"), "/dev/vda");
        assert_eq!(disk_title("Mockware", "Mock NVMe", "NVMe", "/dev/nvme0n1"), "Mockware Mock NVMe");
    }

    #[cfg(unix)]
    #[test]
    fn error_display_shows_the_name_only() {
        // Parameters may carry secrets: they must never reach a log line.
        let error = Error::Varlink {
            name: "InvalidConfig".to_string(),
            parameters: serde_json::json!({
                "errors": [],
                "passphrase": "correct horse battery staple",
            }),
        };
        let shown = error.to_string();
        assert!(shown.contains("InvalidConfig"));
        assert!(!shown.contains("correct horse"));
    }

    #[cfg(unix)]
    #[test]
    fn wire_format_round_trips_against_a_scripted_peer() {
        use std::io::{BufRead, BufReader, Write};
        use std::os::unix::net::UnixListener;

        let dir = std::env::temp_dir().join(format!("fishermand-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("daemon.sock");
        let listener = UnixListener::bind(&path).unwrap();

        // A scripted peer: one single-reply call, one two-reply stream, one
        // error reply. Each message ends with NUL, like the real daemon.
        let peer = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut frame = |want_continues: bool| {
                let mut raw = Vec::new();
                reader.read_until(0, &mut raw).unwrap();
                raw.pop();
                let request: Value = serde_json::from_slice(&raw).unwrap();
                let method = request["method"].as_str().unwrap().to_string();
                let reply = if method.ends_with("Requirements") {
                    serde_json::json!({ "parameters": { "meetsRequirements": true } })
                } else if method.ends_with("Cancel") {
                    serde_json::json!({ "error": "NotInstalled", "parameters": {} })
                } else {
                    serde_json::json!({ "parameters": { "overallPct": 50 }, "continues": want_continues })
                };
                let mut wire = serde_json::to_vec(&reply).unwrap();
                wire.push(0);
                stream.write_all(&wire).unwrap();
                // The stream's last reply carries no `continues` flag.
                if want_continues {
                    let last = serde_json::json!({ "parameters": { "overallPct": 100 } });
                    let mut wire = serde_json::to_vec(&last).unwrap();
                    wire.push(0);
                    stream.write_all(&wire).unwrap();
                }
            };
            frame(false);
            frame(true);
            frame(false);
        });

        let mut conn = Connection::connect(&path).unwrap();
        let gates = requirements(&mut conn).unwrap();
        assert_eq!(gates["meetsRequirements"], Value::Bool(true));

        let mut seen = 0;
        install(
            &mut conn,
            serde_json::json!({}),
            true,
            |reply| {
                seen += 1;
                reply["overallPct"].is_number()
            },
        )
        .unwrap();
        assert_eq!(seen, 2);

        let error = cancel(&mut conn).unwrap_err();
        assert_eq!(error.to_string(), "NotInstalled");

        peer.join().unwrap();
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn recipe_maps_to_daemon_config_without_image_fields() {
        let mut recipe = crate::Recipe::default();
        recipe.disk = "/dev/nvme0n1".into();
        recipe.hostname = "tuna".into();
        recipe.encryption.enc_type = "tpm2-luks-passphrase".into();
        recipe.encryption.passphrase = "secret".into();
        recipe.user = crate::model::user_block("alex", "Alex Example", "pw", &["wheel".into()]);
        let config = daemon_config(&recipe, Some(crate::InstallMode::Erase));
        assert_eq!(config["disk"], Value::from("/dev/nvme0n1"));
        assert_eq!(config["installMode"], Value::from("erase"));
        assert_eq!(config["encryption"]["type"], Value::from("tpm2_luks_passphrase"));
        assert_eq!(config["encryption"]["passphrase"], Value::from("secret"));
        assert_eq!(config["user"]["username"], Value::from("alex"));
        assert_eq!(config["hostname"], Value::from("tuna"));
        // The daemon partitions and configures; it never fetches an image.
        assert!(config.get("image").is_none());
        assert!(config.get("filesystem").is_none());
        assert!(config.get("flatpaks").is_none());
    }

    #[test]
    fn daemon_probe_maps_to_wizard_facts() {
        let probe = serde_json::json!({
            "protocolVersion": 1,
            "disks": [
                {"path": "/dev/nvme0n1", "sizeLabel": "476.9 GiB", "model": "Mock NVMe 512",
                 "vendor": "Mockware", "transport": "nvme", "removable": false, "eligible": true},
                {"path": "/dev/sdb", "sizeLabel": "8 GiB", "model": "Mock USB Stick",
                 "vendor": "Mockware", "transport": "usb", "removable": true, "eligible": false}
            ],
            "tpm": {"present": true, "version": "2.0", "usable": true},
            "intelRst": {"detected": false},
            "live": {"isLive": true, "liveImage": "ghcr.io/tuna-os/mock:live"}
        });
        let gates = serde_json::json!({"gates": [
            {"id": "ram", "ok": true},
            {"id": "cpu", "ok": true},
            {"id": "firmware", "ok": false}
        ]});
        let facts = daemon_probe_to_facts(&probe, &gates).unwrap();
        // Only eligible disks reach the wizard, in the daemon's order.
        assert_eq!(facts.disks.len(), 1);
        assert_eq!(facts.disks[0].path, "/dev/nvme0n1");
        assert_eq!(facts.disks[0].title, "Mockware Mock NVMe 512");
        assert!(facts.tpm_usable);
        assert!(facts.is_live);
        assert_eq!(facts.live_image, "ghcr.io/tuna-os/mock:live");
        // The wizard's gate name for firmware is uefi.
        assert_eq!(facts.unmet, vec!["uefi".to_string()]);
        assert!(!facts.intel_rst);
        // disk_data parallels disks: one entry, no data on a fresh disk.
        assert_eq!(facts.disk_data.len(), 1);
        assert!(!facts.disk_data[0].has_data);
    }

    #[test]
    fn daemon_probe_with_rst_and_data_maps_both() {
        let probe = serde_json::json!({
            "protocolVersion": 1,
            "disks": [
                {"path": "/dev/nvme0n1", "sizeLabel": "477 GiB", "model": "NVMe",
                 "vendor": "Mockware", "transport": "nvme", "removable": false, "eligible": true,
                 "freeBytes": 100, "minimalSizeBytes": 200,
                 "existingData": {"hasPartitionTable": true, "partitions": [],
                     "operatingSystems": ["Windows"], "hasLuks": false}}
            ],
            "tpm": {"present": false, "version": "", "usable": false},
            "intelRst": {"detected": true, "affectedDisks": ["/dev/nvme0n1"]},
            "live": {"isLive": false}
        });
        let gates = serde_json::json!({"gates": []});
        let facts = daemon_probe_to_facts(&probe, &gates).unwrap();
        assert!(facts.intel_rst);
        assert_eq!(facts.disk_data.len(), 1);
        assert!(facts.disk_data[0].has_data);
        assert_eq!(facts.disk_data[0].free_bytes, 100);
        assert_eq!(facts.disk_data[0].minimal_bytes, 200);
    }

    #[test]
    fn daemon_validate_problems_render_on_the_page() {
        let reply = serde_json::json!({"valid": false, "errors": [
            {"field": "hostname", "code": "hostname_invalid_char", "message": "bad"}
        ]});
        let problems = daemon_problems(&reply);
        assert_eq!(problems.len(), 1);
        assert_eq!(problems[0].field, "hostname");
        assert_eq!(problems[0].code, "hostname_invalid_char");
    }

    #[test]
    fn partial_recipe_maps_to_daemon_config() {
        let partial = serde_json::json!({
            "hostname": "tuna",
            "filesystem": "btrfs",
            "encryption": {"type": "luks-passphrase", "passphrase": "secret"},
        });
        let config = daemon_config_from_partial(&partial);
        assert_eq!(config["hostname"], Value::from("tuna"));
        assert_eq!(config["encryption"]["type"], Value::from("luks_passphrase"));
        assert_eq!(config["encryption"]["passphrase"], Value::from("secret"));
        // No daemon field: dropped, not sent.
        assert!(config.get("filesystem").is_none());
    }

    #[test]
    fn daemon_probe_handoff_defaults_to_reboot() {
        // The daemon decides the mode; a missing or unknown field means
        // reboot, and the install calls Handoff with no mode.
        let gates = serde_json::json!({"gates": []});
        let bare = serde_json::json!({"protocolVersion": 1, "disks": []});
        let facts = daemon_probe_to_facts(&bare, &gates).unwrap();
        assert_eq!(facts.handoff_mode, "reboot");
        assert!(facts.handoff_reason.is_empty());
        let soft = serde_json::json!({
            "protocolVersion": 1, "disks": [],
            "handoff": {"mode": "soft_reboot", "reason": "EL10 cells restart userspace"},
        });
        let facts = daemon_probe_to_facts(&soft, &gates).unwrap();
        assert_eq!(facts.handoff_mode, "soft_reboot");
        assert_eq!(facts.handoff_reason, "EL10 cells restart userspace");
        let weird = serde_json::json!({
            "protocolVersion": 1, "disks": [],
            "handoff": {"mode": "hyperdrive"},
        });
        let facts = daemon_probe_to_facts(&weird, &gates).unwrap();
        assert_eq!(facts.handoff_mode, "reboot");
    }

}
