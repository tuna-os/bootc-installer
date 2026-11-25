//! Page-by-page tests against the real mock daemon (tuna-os/fisherman,
//! `fisherman/docs/FISHERMAND.md`).
//!
//! They need a built mock binary. `FISHERMAND_BIN` names it:
//!
//! ```bash
//! (cd fisherman/fisherman && go build -o /tmp/fishermand ./cmd/fishermand)
//! FISHERMAND_BIN=/tmp/fishermand cargo test --locked mock_
//! ```
//!
//! Without `FISHERMAND_BIN` each test prints why it did nothing and
//! returns. That is not a pass of the daemon path: read the output.
//!
//! Each test spawns the mock with one `--scenario` on a fresh socket dir,
//! drives it through `crate::fishermand`, and kills it. Scenario names are
//! the daemon's real ones; `fishermand::scenario_alias` maps the spec names
//! of `shared/flow/screens.yaml` to these.

use std::path::PathBuf;
use std::process::{Child, Command};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::fishermand;

/// The mock binary, or `None` with a line on stderr that says why the
/// test did nothing.
fn mock_bin() -> Option<String> {
    match std::env::var("FISHERMAND_BIN") {
        Ok(bin) if std::path::Path::new(&bin).is_file() => Some(bin),
        Ok(bin) => panic!("FISHERMAND_BIN={bin} is not a file"),
        Err(_) => {
            // Written to the stream itself, once: the test harness hides
            // what a passing test prints, and this must not be hidden.
            static SAID: std::sync::Once = std::sync::Once::new();
            SAID.call_once(|| {
                use std::io::Write;
                let _ = std::io::stderr().write_all(
                    b"\nSKIPPED: FISHERMAND_BIN is not set, so the mock_ tests ran no daemon. \
                      Build cmd/fishermand of tuna-os/fisherman and set FISHERMAND_BIN.\n",
                );
            });
            None
        }
    }
}

/// Starts the mock for `$scenario`, or leaves the test when there is no
/// mock binary.
macro_rules! mock_or_skip {
    ($scenario:expr) => {
        match Mock::start($scenario) {
            Some(mock) => mock,
            None => return,
        }
    };
}

pub(crate) struct Mock {
    child: Child,
    pub(crate) dir: PathBuf,
}

impl Mock {
    pub(crate) fn start(scenario: &str) -> Option<Self> {
        let bin = mock_bin()?;
        // Unique per spawn: tests run in parallel and one scenario (happy)
        // serves several tests, so a shared dir would race socket binds.
        static SPAWNS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let n = SPAWNS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let dir: PathBuf = std::env::temp_dir().join(format!(
            "cosmic-mock-{}-{}-{}",
            scenario,
            std::process::id(),
            n
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let child = Command::new(bin)
            .args([
                "--mock",
                "--scenario",
                scenario,
                "--socket-dir",
                dir.to_str().unwrap(),
            ])
            .spawn()
            .expect("mock daemon starts");
        let socket = dir.join("io.tunaos.Fisherman");
        let deadline = Instant::now() + Duration::from_secs(10);
        while !socket.exists() {
            if Instant::now() > deadline {
                panic!("mock daemon never opened {socket:?}");
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        // The daemon needs a breath after opening the socket.
        std::thread::sleep(Duration::from_millis(200));
        Some(Self { child, dir })
    }

    fn connect(&self) -> fishermand::Connection {
        fishermand::Connection::connect(self.dir.join("io.tunaos.Fisherman")).unwrap()
    }

    fn shutdown_connect(&self) -> fishermand::Connection {
        fishermand::Connection::connect(self.dir.join("io.systemd.Shutdown")).unwrap()
    }
}

impl Drop for Mock {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        std::fs::remove_dir_all(&dir_clone(&self.dir)).ok();
    }
}

fn dir_clone(dir: &PathBuf) -> PathBuf {
    dir.clone()
}

fn happy_config(disk: &str) -> Value {
    json!({
        "disk": disk,
        "encryption": {"type": "tpm2_luks"},
    })
}

#[test]
fn mock_happy_probe_maps_to_wizard_facts() {
    let mock = mock_or_skip!("happy");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    assert_eq!(gates["meetsRequirements"], Value::Bool(true));
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    // The mock's 8 GiB USB stick is below the daemon's 20 GiB minimum: it is
    // listed as too small, not offered.
    assert_eq!(facts.disks.len(), 1);
    assert_eq!(facts.disks[0].path, "/dev/nvme0n1");
    assert_eq!(facts.too_small.len(), 1);
    assert!(facts.too_small[0].caption.starts_with("/dev/sdb"), "{:?}", facts.too_small[0].caption);
    assert!(facts.tpm_usable);
    assert!(facts.unmet.is_empty());
    assert!(!facts.intel_rst);
    // The mock sends no handoff field: the fallback is a reboot.
    assert_eq!(facts.handoff_mode, "reboot");
}

#[test]
fn mock_no_tpm_validate_reports_encryption_required() {
    let mock = mock_or_skip!("no-tpm");
    let mut conn = mock.connect();
    let probe = fishermand::probe(&mut conn).unwrap();
    assert_eq!(probe["tpm"]["usable"], Value::Bool(false));
    // No encryption choice on a TPM-less machine: the daemon refuses.
    let reply = fishermand::validate(&mut conn, happy_config("/dev/nvme0n1"), false).unwrap();
    let problems = fishermand::daemon_problems(&reply);
    assert!(!problems.is_empty(), "a passphrase-less config needs an error");
    let reply = fishermand::validate(
        &mut conn,
        json!({
            "disk": "/dev/nvme0n1",
            "encryption": {"type": "luks_passphrase", "passphrase": "secret"},
        }),
        false,
    )
    .unwrap();
    assert_eq!(reply["valid"], Value::Bool(true));
    assert!(fishermand::daemon_problems(&reply).is_empty());
}

#[test]
fn mock_existing_data_probe_keeps_both_disks() {
    let mock = mock_or_skip!("existing-data");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(!facts.disks.is_empty());
    let nvme = probe["disks"]
        .as_array()
        .unwrap()
        .iter()
        .find(|d| d["path"] == "/dev/nvme0n1")
        .expect("NVMe present in existing-data");
    let data = &nvme["existingData"];
    assert_eq!(data["hasPartitionTable"], Value::Bool(true));
    assert!(!data["operatingSystems"].as_array().unwrap().is_empty());
    // The wizard pairs data with its disk by index; the NVMe offers the
    // wipe-or-free choice.
    let nvme_idx = facts.disks.iter().position(|d| d.path == "/dev/nvme0n1").unwrap();
    assert!(facts.disk_data[nvme_idx].has_data);
    assert!(facts.disk_data[nvme_idx].data_detected());
    // The disk with a foreign partition table has room, but the daemon
    // refuses free space there: no choice, the whole disk goes.
    let sdc = facts.disks.iter().position(|d| d.path == "/dev/sdc").expect("the dos disk");
    assert!(facts.disk_data[sdc].has_data);
    assert!(!facts.disk_data[sdc].data_detected());
    let free = json!({"disk": "/dev/sdc", "installMode": "free_space", "encryption": {"type": "tpm2_luks"}});
    let reply = fishermand::validate(&mut conn, free, false).unwrap();
    let codes: Vec<String> = fishermand::daemon_problems(&reply).into_iter().map(|p| p.code).collect();
    assert_eq!(codes, ["conflicting_disk_label"]);
    let mode = crate::TunaInstaller::install_mode_for(facts.disk_data[sdc].data_detected(), None);
    let erase = json!({"disk": "/dev/sdc", "installMode": mode.daemon_name(), "encryption": {"type": "tpm2_luks"}});
    let reply = fishermand::validate(&mut conn, erase, false).unwrap();
    assert!(fishermand::daemon_problems(&reply).is_empty(), "{reply}");
}

#[test]
fn mock_rst_probe_reports_intel_rst() {
    let mock = mock_or_skip!("rst");
    let mut conn = mock.connect();
    let probe = fishermand::probe(&mut conn).unwrap();
    assert_eq!(probe["intelRst"]["detected"], Value::Bool(true));
    // The wizard's facts carry the flag; the RST page shows while set.
    let gates = fishermand::requirements(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(facts.intel_rst);
}

#[test]
fn mock_requirements_gates_map_to_wizard_names() {
    let mock = mock_or_skip!("low-ram");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    assert_eq!(gates["meetsRequirements"], Value::Bool(false));
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(facts.unmet.contains(&"ram".to_string()), "{facts:?}");

    let mock = mock_or_skip!("no-uefi");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    // The mock's `firmware` gate is the wizard's `uefi` gate.
    assert!(facts.unmet.contains(&"uefi".to_string()), "{facts:?}");
}

fn run_install_to_terminal(scenario: &str) -> Option<Vec<Value>> {
    let mock = Mock::start(scenario)?;
    Some(install_events(&mock, happy_config("/dev/nvme0n1")))
}

/// One install on `mock`, to its terminal event.
fn install_events(mock: &Mock, config: Value) -> Vec<Value> {
    let mut conn = mock.connect();
    let mut events = Vec::new();
    let result = fishermand::install(&mut conn, config, true, |event| {
        events.push(event);
        true
    });
    // Terminal events end the stream cleanly; only transport breaks err.
    assert!(result.is_ok(), "{result:?}");
    events
}

/// Folds the events the way the install page does, and returns how the
/// install ended with the page's progress state.
fn fold(events: &[Value]) -> (fishermand::Terminal, crate::progress::Progress) {
    let mut progress = crate::progress::Progress::new("product");
    let mut log = String::new();
    let mut end = fishermand::Terminal::Continue;
    let mut last_fraction = 0.0;
    for event in events {
        assert_eq!(end, fishermand::Terminal::Continue, "an event came after the terminal one");
        end = fishermand::apply_install_event(&mut progress, &mut log, event);
        // overallPct never goes down (FISHERMAND.md).
        assert!(progress.fraction >= last_fraction, "the bar went back at {event}");
        last_fraction = progress.fraction;
    }
    (end, progress)
}

/// The recipe of a wizard that chose `disk`, with the daemon's sealed
/// default applied the way `apply_probe` applies it.
fn wizard_recipe(disk: &str, has_tpm: bool) -> crate::Recipe {
    let mut recipe = crate::Recipe::default();
    recipe.disk = disk.to_string();
    recipe.hostname = "tuna-box".to_string();
    recipe.locale = "de_DE.UTF-8".to_string();
    recipe.timezone = "Europe/Berlin".to_string();
    recipe.choose_keyboard("de");
    recipe.keyboard.as_mut().unwrap().variant = "nodeadkeys".to_string();
    recipe.encryption.enc_type =
        crate::TunaInstaller::daemon_default_type(has_tpm, &recipe.encryption.enc_type, false).to_string();
    recipe
}

#[test]
fn mock_device_lost_install_fails_with_device_lost() {
    let Some(events) = run_install_to_terminal("device-lost") else { return };
    let last = events.last().expect("install streams events");
    assert_eq!(last["event"], Value::from("failed"));
    assert_eq!(last["reason"], Value::from("device_lost"));
    let mut progress = crate::progress::Progress::new("product");
    let mut log = String::new();
    for event in &events {
        let terminal = fishermand::apply_install_event(&mut progress, &mut log, event);
        if event == last {
            assert_eq!(terminal, fishermand::Terminal::Failed);
        }
    }
    assert_eq!(
        progress.error.as_ref().map(|e| e.code.as_str()),
        Some("device_lost")
    );
}

#[test]
fn mock_repart_error_install_fails_with_repart_failed() {
    let Some(events) = run_install_to_terminal("repart-error") else { return };
    let last = events.last().expect("install streams events");
    assert_eq!(last["event"], Value::from("failed"));
    assert_eq!(last["reason"], Value::from("repart_failed"));
}

#[test]
fn mock_cancel_install_reports_cancelled() {
    let mock = mock_or_skip!("cancel");
    let dir = dir_clone(&mock.dir);
    let handle = std::thread::spawn(move || {
        let mut conn = fishermand::Connection::connect(dir.join("io.tunaos.Fisherman")).unwrap();
        let mut terminal = None;
        let mut progress = crate::progress::Progress::new("product");
        let mut log = String::new();
        fishermand::install(&mut conn, happy_config("/dev/nvme0n1"), true, |event| {
            match fishermand::apply_install_event(&mut progress, &mut log, &event) {
                fishermand::Terminal::Continue => true,
                end => {
                    terminal = Some(end);
                    false
                }
            }
        })
        .unwrap();
        terminal.expect("a terminal event ends the stream")
    });
    // The install waits mid-install_os until Cancel arrives.
    std::thread::sleep(Duration::from_secs(2));
    let mut conn = mock.connect();
    let reply = fishermand::cancel(&mut conn).unwrap();
    assert_eq!(reply["wasInstalling"], Value::Bool(true));
    assert_eq!(handle.join().unwrap(), fishermand::Terminal::Cancelled);
}

#[test]
fn mock_inhibitor_shutdown_records_the_call() {
    let mock = mock_or_skip!("inhibitor");
    let mut conn = mock.shutdown_connect();
    // Blocked without skipInhibitors: the daemon answers an error whose
    // name is the only thing the client surfaces.
    let error = fishermand::reboot(&mut conn, false).unwrap_err();
    assert!(!error.to_string().is_empty());
}

#[test]
fn mock_tight_space_probe_still_lists_the_disk() {
    let mock = mock_or_skip!("tight-space");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(!facts.disks.is_empty());
    // The NVMe holds data without room: no choice there, the confirm asks
    // for a forced erase instead.
    let nvme = facts.disks.iter().position(|d| d.path == "/dev/nvme0n1").unwrap();
    assert!(facts.disk_data[nvme].has_data);
    assert!(!facts.disk_data[nvme].data_detected());
    // The foreign-label disk has room, but its table cannot share the
    // disk: no disk of this scenario offers the choice.
    assert!(!facts.disk_data.iter().any(|d| d.data_detected()));
}

#[test]
fn mock_recovery_key_makes_and_enrols() {
    // The recovery-key page flow: install, MakeRecoveryKey when the page
    // opens, then Enroll on Done with the install passphrase as the unlock
    // password. Happy seals with TPM and no passphrase, so the unlock
    // password is empty. A volume only exists after an install.
    let mock = mock_or_skip!("happy");
    let mut install_conn = mock.connect();
    let mut last = None;
    fishermand::install(&mut install_conn, happy_config("/dev/nvme0n1"), true, |event| {
        last = Some(event);
        true
    })
    .unwrap();
    assert_eq!(
        last.expect("install streams events")["event"],
        Value::from("complete")
    );
    let mut conn = mock.connect();
    let key = fishermand::make_recovery_key(&mut conn).unwrap();
    // The harness matches the key by shape, eight groups of letters.
    assert!(fishermand::is_recovery_key_shape(&key), "{key}");
    let reply =
        fishermand::enroll_recovery(&mut conn, "/dev/nvme0n1", &key, "").unwrap();
    assert_eq!(reply["state"], Value::from("enrolled"));
    assert_eq!(reply["recoveryKey"], Value::from(key.as_str()));
}

// ---- one walk per scenario, through the calls each screen makes ----

#[test]
fn mock_happy_walk_reaches_handoff_with_no_mode() {
    // happy: try-or-install, language, keyboard, timezone, disk, confirm,
    // install, recovery-key, handoff, done. The TPM skips `encryption`.
    let mock = mock_or_skip!("happy");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(facts.tpm_usable, "happy has a TPM: the encryption page is skipped");
    assert!(!facts.disk_data[0].data_detected(), "an empty disk skips wipe-or-free");
    let recipe = wizard_recipe(&facts.disks[0].path, facts.tpm_usable);
    assert_eq!(recipe.encryption.enc_type, "tpm2-luks");

    // confirm: Validate the whole config.
    let config = fishermand::daemon_config(&recipe, None);
    let reply = fishermand::validate(&mut conn, config.clone(), false).unwrap();
    assert!(fishermand::daemon_problems(&reply).is_empty(), "{reply}");

    // install: ConfigureTarget first. The untouched location switch sends
    // no privacy object; a moved one sends it.
    let untouched = fishermand::configure_params(&recipe, None);
    assert!(untouched.get("privacy").is_none());
    let reply = fishermand::configure_target(&mut conn, untouched).unwrap();
    assert_eq!(reply["configured"], Value::Bool(true), "{reply}");
    let moved = fishermand::configure_params(&recipe, Some(true));
    assert_eq!(moved["privacy"]["locationServices"], Value::Bool(true));
    let reply = fishermand::configure_target(&mut conn, moved).unwrap();
    assert!(fishermand::daemon_problems(&reply).is_empty(), "{reply}");

    // Handoff before an install is refused: the page comes only after one.
    let early = fishermand::handoff(&mut conn, None).unwrap_err();
    assert_eq!(early.to_string(), "io.tunaos.Fisherman.NotInstalled");

    let events = install_events(&mock, config);
    let (end, progress) = fold(&events);
    assert_eq!(end, fishermand::Terminal::Complete);
    assert!(progress.error.is_none());
    assert_eq!(progress.fraction, 1.0);

    // recovery-key: make on entry, enrol on Done (TPM: empty unlock).
    let mut crypt = mock.connect();
    let key = fishermand::make_recovery_key(&mut crypt).unwrap();
    assert!(fishermand::is_recovery_key_shape(&key));
    fishermand::enroll_recovery(&mut crypt, &recipe.disk, &key, "").unwrap();

    // handoff: no mode goes on the wire; the daemon decides.
    assert_eq!(facts.handoff_mode, "reboot");
    let reply = fishermand::handoff(&mut conn, None).unwrap();
    assert_eq!(reply["mode"], Value::from("reboot"), "{reply}");
    assert_eq!(reply["started"], Value::Bool(true), "{reply}");
}

#[test]
fn mock_handoff_modes_come_from_probe() {
    for (scenario, mode) in [("handoff-migrate", "migrate"), ("handoff-soft-reboot", "soft_reboot")] {
        let mock = mock_or_skip!(scenario);
        let mut conn = mock.connect();
        let gates = fishermand::requirements(&mut conn).unwrap();
        let probe = fishermand::probe(&mut conn).unwrap();
        let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
        assert_eq!(facts.handoff_mode, mode, "{scenario}");
        let events = install_events(&mock, happy_config(&facts.disks[0].path));
        assert_eq!(fold(&events).0, fishermand::Terminal::Complete);
        let reply = fishermand::handoff(&mut conn, None).unwrap();
        assert_eq!(
            fishermand::handoff_mode_of(reply["mode"].as_str()),
            mode,
            "{scenario}: {reply}"
        );
    }
}

#[test]
fn mock_no_tpm_walk_installs_with_a_passphrase() {
    // no-tpm: the encryption page asks for a passphrase, twice.
    let mock = mock_or_skip!("no-tpm");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(!facts.tpm_usable);
    let mut recipe = wizard_recipe(&facts.disks[0].path, facts.tpm_usable);
    // No TPM: the page starts at the passphrase type. The daemon refuses
    // a TPM type here, so the page does not offer one.
    assert_eq!(recipe.encryption.enc_type, "luks-passphrase");
    let reply = fishermand::validate(&mut conn, happy_config(&recipe.disk), false).unwrap();
    let problems = fishermand::daemon_problems(&reply);
    assert!(problems.iter().any(|p| p.field.starts_with("encryption")), "{reply}");
    // The TPM types are not offered without a TPM.
    assert!(crate::available_encryption_choices(false).iter().all(|c| !crate::validate::needs_tpm2(c)));
    recipe.choose_encryption("luks-passphrase");
    recipe.encryption.passphrase = "correct horse battery staple".into();
    let config = fishermand::daemon_config(&recipe, None);
    assert_eq!(config["encryption"]["type"], Value::from("luks_passphrase"));
    let reply = fishermand::validate(&mut conn, config.clone(), false).unwrap();
    assert!(fishermand::daemon_problems(&reply).is_empty(), "{reply}");
    let events = install_events(&mock, config);
    assert_eq!(fold(&events).0, fishermand::Terminal::Complete);
    // The luks step runs; no event carries the passphrase.
    assert!(events.iter().any(|e| e["stepId"] == "luks"), "no luks step");
    assert!(!events.iter().any(|e| e.to_string().contains("correct horse")));
    // recovery-key: the passphrase unlocks the volume for the enrolment.
    let mut crypt = mock.connect();
    let key = fishermand::make_recovery_key(&mut crypt).unwrap();
    fishermand::enroll_recovery(&mut crypt, &recipe.disk, &key, &recipe.encryption.passphrase).unwrap();
}

#[test]
fn mock_existing_data_walk_installs_into_free_space_or_erases() {
    // existing-data: the wipe-or-free page; both answers install.
    for mode in [crate::InstallMode::FreeSpace, crate::InstallMode::Erase] {
        let mock = mock_or_skip!("existing-data");
        let mut conn = mock.connect();
        let gates = fishermand::requirements(&mut conn).unwrap();
        let probe = fishermand::probe(&mut conn).unwrap();
        let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
        let nvme = facts.disks.iter().position(|d| d.path == "/dev/nvme0n1").unwrap();
        assert!(facts.disk_data[nvme].data_detected(), "the page shows for this disk");
        let recipe = wizard_recipe("/dev/nvme0n1", facts.tpm_usable);
        let config = fishermand::daemon_config(&recipe, Some(mode));
        assert_eq!(config["installMode"], Value::from(mode.daemon_name()));
        let reply = fishermand::validate(&mut conn, config.clone(), false).unwrap();
        assert!(fishermand::daemon_problems(&reply).is_empty(), "{mode:?}: {reply}");
        let events = install_events(&mock, config);
        assert_eq!(fold(&events).0, fishermand::Terminal::Complete, "{mode:?}");
    }
}

#[test]
fn mock_tight_space_walk_erases_because_free_space_is_refused() {
    // tight-space: data and no room. No wipe-or-free page; the confirm
    // page validates the whole config, and the install takes the disk.
    let mock = mock_or_skip!("tight-space");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    let nvme = facts.disks.iter().position(|d| d.path == "/dev/nvme0n1").unwrap();
    let offered = facts.disk_data[nvme].data_detected();
    assert!(!offered);
    let recipe = wizard_recipe("/dev/nvme0n1", facts.tpm_usable);
    // What the wizard used to send: free space with no page to pick it on.
    let refused = fishermand::daemon_config(&recipe, Some(crate::InstallMode::FreeSpace));
    let reply = fishermand::validate(&mut conn, refused, false).unwrap();
    let codes: Vec<String> = fishermand::daemon_problems(&reply).into_iter().map(|p| p.code).collect();
    assert!(codes.contains(&"insufficient_free_space".to_string()), "{codes:?}");
    // What it sends now.
    let mode = crate::TunaInstaller::install_mode_for(offered, None);
    assert_eq!(mode, crate::InstallMode::Erase);
    let config = fishermand::daemon_config(&recipe, Some(mode));
    let reply = fishermand::validate(&mut conn, config.clone(), false).unwrap();
    assert!(fishermand::daemon_problems(&reply).is_empty(), "{reply}");
    let events = install_events(&mock, config);
    assert_eq!(fold(&events).0, fishermand::Terminal::Complete);
}

#[test]
fn mock_empty_disk_installs_with_the_whole_disk_mode() {
    let mock = mock_or_skip!("happy");
    let mut conn = mock.connect();
    let recipe = wizard_recipe("/dev/nvme0n1", true);
    let mode = crate::TunaInstaller::install_mode_for(false, None);
    let config = fishermand::daemon_config(&recipe, Some(mode));
    assert_eq!(config["installMode"], Value::from("erase"));
    let reply = fishermand::validate(&mut conn, config.clone(), false).unwrap();
    assert!(fishermand::daemon_problems(&reply).is_empty(), "{reply}");
    let events = install_events(&mock, config);
    assert_eq!(fold(&events).0, fishermand::Terminal::Complete);
}

#[test]
fn mock_rst_walk_offers_no_disk_and_refuses_the_hidden_one() {
    // rst: the RST page explains why the disk list misses the NVMe.
    let mock = mock_or_skip!("rst");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(facts.intel_rst);
    assert!(
        !facts.disks.iter().any(|d| d.path == "/dev/nvme0n1"),
        "the hidden disk is not offered: {:?}",
        facts.disks.iter().map(|d| &d.path).collect::<Vec<_>>()
    );
    // The daemon refuses the hidden disk when a client names it anyway.
    let reply = fishermand::validate(&mut conn, happy_config("/dev/nvme0n1"), false).unwrap();
    assert!(!fishermand::daemon_problems(&reply).is_empty(), "{reply}");
}

#[test]
fn mock_device_lost_walk_ends_on_the_failed_page_and_allows_a_retry() {
    let mock = mock_or_skip!("device-lost");
    let events = install_events(&mock, happy_config("/dev/nvme0n1"));
    let (end, progress) = fold(&events);
    assert_eq!(end, fishermand::Terminal::Failed);
    let error = progress.error.as_ref().unwrap();
    assert_eq!(error.code, "device_lost");
    assert_eq!(error.step_id, "install_os");
    // The done page says the disk changed, in the branding's words.
    assert_eq!(
        crate::progress::failure_lines(progress.error.as_ref()),
        vec!["done_failed_disk_changed"]
    );
    assert_eq!(
        crate::ui::daemon_failure_text(&error.code),
        crate::i18n::tr(crate::ui::copy::DONE_DEVICE_LOST)
    );
    // No handoff after a failure. The daemon is idle again, so Try again
    // reaches it: the lost disk is refused as data, not as a running
    // install, and the done page shows that reason.
    let mut conn = mock.connect();
    let refused = fishermand::handoff(&mut conn, None).unwrap_err();
    assert_eq!(refused.to_string(), "io.tunaos.Fisherman.NotInstalled");
    let again = fishermand::install(&mut conn, happy_config("/dev/nvme0n1"), true, |_| true).unwrap_err();
    assert_eq!(again.to_string(), "io.tunaos.Fisherman.InvalidConfig");
}

#[test]
fn mock_repart_error_walk_ends_on_the_failed_page() {
    let mock = mock_or_skip!("repart-error");
    let events = install_events(&mock, happy_config("/dev/nvme0n1"));
    let (end, progress) = fold(&events);
    assert_eq!(end, fishermand::Terminal::Failed);
    let error = progress.error.as_ref().unwrap();
    assert_eq!(error.code, "repart_failed");
    assert_eq!(error.step_id, "partition");
    assert_eq!(
        crate::ui::daemon_failure_text(&error.code),
        crate::i18n::tr(crate::ui::copy::DONE_REPART_FAILED)
    );
}

#[test]
fn mock_cancel_walk_ends_cancelled_and_a_second_cancel_is_idle() {
    let mock = mock_or_skip!("cancel");
    let dir = dir_clone(&mock.dir);
    let handle = std::thread::spawn(move || {
        let mut conn = fishermand::Connection::connect(dir.join("io.tunaos.Fisherman")).unwrap();
        let mut events = Vec::new();
        fishermand::install(&mut conn, happy_config("/dev/nvme0n1"), true, |event| {
            events.push(event);
            true
        })
        .unwrap();
        events
    });
    std::thread::sleep(Duration::from_secs(2));
    // A second Install while one runs is refused.
    let mut conn = mock.connect();
    let busy = fishermand::install(&mut conn, happy_config("/dev/nvme0n1"), true, |_| true).unwrap_err();
    assert_eq!(busy.to_string(), "io.tunaos.Fisherman.InstallInProgress");
    assert_eq!(
        fishermand::stream_failure_reason(&busy.to_string()),
        "io.tunaos.Fisherman.InstallInProgress"
    );
    // Cancel goes over its own connection.
    let mut cancel_conn = mock.connect();
    let reply = fishermand::cancel(&mut cancel_conn).unwrap();
    assert_eq!(reply["wasInstalling"], Value::Bool(true));
    let events = handle.join().unwrap();
    let (end, progress) = fold(&events);
    assert_eq!(end, fishermand::Terminal::Cancelled);
    assert!(progress.error.is_none(), "a cancel is not a failure");
    // The install page maps the cancelled event to exit code 130.
    assert_eq!(crate::install_outcome(Some(130), true), crate::Outcome::Cancelled);
    // Cancel is safe when idle.
    let reply = fishermand::cancel(&mut cancel_conn).unwrap();
    assert_eq!(reply["wasInstalling"], Value::Bool(false));
}

#[test]
fn mock_unconfirmed_install_is_refused() {
    let mock = mock_or_skip!("happy");
    let mut conn = mock.connect();
    let refused =
        fishermand::install(&mut conn, happy_config("/dev/nvme0n1"), false, |_| true).unwrap_err();
    assert_eq!(refused.to_string(), "io.tunaos.Fisherman.NotConfirmed");
}

#[test]
fn mock_absent_daemon_is_the_unreachable_state() {
    // No mock needed: nothing listens on this path.
    let dir = std::env::temp_dir().join(format!("cosmic-no-daemon-{}", std::process::id()));
    let Err(error) = fishermand::Connection::connect(dir.join("io.tunaos.Fisherman")) else {
        panic!("a socket that is not there connected");
    };
    let text = format!("cannot reach fishermand: {error}");
    assert_eq!(fishermand::stream_failure_reason(&text), "daemon_unreachable");
}
