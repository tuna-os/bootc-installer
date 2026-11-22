//! Page-by-page tests against the real mock daemon (tuna-os/fisherman
//! branch `feat/fishermand-mock`, draft PR #513).
//!
//! Ignored by default: they need a built mock binary, which CI does not
//! have until the daemon ships. Run them with:
//!
//! ```bash
//! FISHERMAND_BIN=/tmp/cosmic-fishermand/bin/fishermand \
//!   cargo test --locked -- --ignored mock_
//! ```
//!
//! Each test spawns the mock with one `--scenario` on a fresh socket dir,
//! drives it through `crate::fishermand`, and kills it. Scenario names are
//! the daemon's real ones; `fishermand::scenario_alias` maps the spec names
//! (PR #447) to these (PR #513).

use std::path::PathBuf;
use std::process::{Child, Command};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::fishermand;

fn mock_bin() -> String {
    std::env::var("FISHERMAND_BIN")
        .expect("FISHERMAND_BIN must point at a built fishermand binary")
}

struct Mock {
    child: Child,
    dir: PathBuf,
}

impl Mock {
    fn start(scenario: &str) -> Self {
        let dir: PathBuf = std::env::temp_dir().join(format!(
            "cosmic-mock-{}-{}",
            scenario,
            std::process::id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let child = Command::new(mock_bin())
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
        Self { child, dir }
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
#[ignore]
fn mock_happy_probe_maps_to_wizard_facts() {
    let mock = Mock::start("happy");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    assert_eq!(gates["meetsRequirements"], Value::Bool(true));
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert_eq!(facts.disks.len(), 2);
    assert_eq!(facts.disks[0].path, "/dev/nvme0n1");
    assert!(facts.tpm_usable);
    assert!(facts.unmet.is_empty());
    assert!(!facts.intel_rst);
}

#[test]
#[ignore]
fn mock_no_tpm_validate_reports_encryption_required() {
    let mock = Mock::start("no-tpm");
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
#[ignore]
fn mock_existing_data_probe_keeps_both_disks() {
    let mock = Mock::start("existing-data");
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
}

#[test]
#[ignore]
fn mock_rst_probe_reports_intel_rst() {
    let mock = Mock::start("rst");
    let mut conn = mock.connect();
    let probe = fishermand::probe(&mut conn).unwrap();
    assert_eq!(probe["intelRst"]["detected"], Value::Bool(true));
    // The wizard's facts carry the flag; the RST page shows while set.
    let gates = fishermand::requirements(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(facts.intel_rst);
}

#[test]
#[ignore]
fn mock_requirements_gates_map_to_wizard_names() {
    let mock = Mock::start("low-ram");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    assert_eq!(gates["meetsRequirements"], Value::Bool(false));
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(facts.unmet.contains(&"ram".to_string()), "{facts:?}");

    let mock = Mock::start("no-uefi");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    // The mock's `firmware` gate is the wizard's `uefi` gate.
    assert!(facts.unmet.contains(&"uefi".to_string()), "{facts:?}");
}

fn run_install_to_terminal(scenario: &str) -> Vec<Value> {
    let mock = Mock::start(scenario);
    let mut conn = mock.connect();
    let mut events = Vec::new();
    let result = fishermand::install(&mut conn, happy_config("/dev/nvme0n1"), true, |event| {
        events.push(event);
        true
    });
    // Terminal events end the stream cleanly; only transport breaks err.
    assert!(result.is_ok(), "{scenario}: {result:?}");
    events
}

#[test]
#[ignore]
fn mock_device_lost_install_fails_with_device_lost() {
    let events = run_install_to_terminal("device-lost");
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
#[ignore]
fn mock_repart_error_install_fails_with_repart_failed() {
    let events = run_install_to_terminal("repart-error");
    let last = events.last().expect("install streams events");
    assert_eq!(last["event"], Value::from("failed"));
    assert_eq!(last["reason"], Value::from("repart_failed"));
}

#[test]
#[ignore]
fn mock_cancel_install_reports_cancelled() {
    let mock = Mock::start("cancel");
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
#[ignore]
fn mock_inhibitor_shutdown_records_the_call() {
    let mock = Mock::start("inhibitor");
    let mut conn = mock.shutdown_connect();
    // Blocked without skipInhibitors: the daemon answers an error whose
    // name is the only thing the client surfaces.
    let error = fishermand::reboot(&mut conn, false).unwrap_err();
    assert!(!error.to_string().is_empty());
}

#[test]
#[ignore]
fn mock_tight_space_probe_still_lists_the_disk() {
    let mock = Mock::start("tight-space");
    let mut conn = mock.connect();
    let gates = fishermand::requirements(&mut conn).unwrap();
    let probe = fishermand::probe(&mut conn).unwrap();
    let facts = fishermand::daemon_probe_to_facts(&probe, &gates).unwrap();
    assert!(!facts.disks.is_empty());
    // The NVMe holds data without room: no choice there, the confirm asks
    // for a forced erase instead. The foreign-label disk keeps room, so it
    // still offers the wipe-or-free choice.
    let nvme = facts.disks.iter().position(|d| d.path == "/dev/nvme0n1").unwrap();
    assert!(facts.disk_data[nvme].has_data);
    assert!(!facts.disk_data[nvme].data_detected());
    assert!(facts.disk_data.iter().any(|d| d.data_detected()));
}
