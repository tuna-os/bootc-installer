//! Blocking hardware gates: CPU, RAM and firmware requirements as gates,
//! not warnings.
//!
//! The welcome page used to list fisherman's `system.unmet` as inline text
//! and let the user continue onto an uninstallable system. GNOME instead
//! opens a dedicated window per unmet requirement *before* the wizard
//! (`BootcCpuWindow`, `BootcRamWindow`, `BootcUnsupportedWindow`, chosen in
//! `bootc_installer/main.py::do_activate`):
//!
//! - RAM and CPU gates offer "continue anyway", which relaunches the
//!   installer with `IGNORE_RAM` / `IGNORE_CPU` in the environment.
//! - An unsupported firmware (non-UEFI) gate offers no way forward — only
//!   power off (`systemctl poweroff`).
//!
//! This module ports that decision table to data. The wizard shows its
//! `Requirements` page exactly when [`blocking_gates`] is non-empty; the
//! override is kept in-process (no relaunch: this frontend is one process,
//! and the probe result is already in memory).

/// One unmet requirement that blocks the wizard.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GateKind {
    /// Too little RAM (`BootcRamWindow`, `IGNORE_RAM` to override).
    Ram,
    /// Too few CPU cores (`BootcCpuWindow`, `IGNORE_CPU` to override).
    Cpu,
    /// Not UEFI firmware (`BootcUnsupportedWindow`): no override exists.
    Unsupported,
}

/// Which gates are overridden by "continue anyway".
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Overrides {
    pub ram: bool,
    pub cpu: bool,
}

/// Parse one `system.unmet` entry (shared/probe/README.md) into a gate.
/// Unknown entries are not gates: a future requirement must not silently
/// become a wall, nor silently pass.
pub fn gate_for(unmet: &str) -> Option<GateKind> {
    match unmet {
        "ram" => Some(GateKind::Ram),
        "cpu" => Some(GateKind::Cpu),
        "uefi" => Some(GateKind::Unsupported),
        _ => None,
    }
}

/// The gates that block the wizard right now: every known unmet requirement
/// except an overridden RAM/CPU gate. UEFI can never be overridden.
pub fn blocking_gates(unmet: &[String], overrides: &Overrides) -> Vec<GateKind> {
    unmet
        .iter()
        .filter_map(|u| gate_for(u))
        .filter(|g| match g {
            GateKind::Ram => !overrides.ram,
            GateKind::Cpu => !overrides.cpu,
            GateKind::Unsupported => true,
        })
        .collect()
}

/// Whether the gate offers "continue anyway" (`window_cpu`/`window_ram`
/// do; `window_unsupported` does not).
pub fn gate_overridable(kind: GateKind) -> bool {
    kind != GateKind::Unsupported
}

/// The environment variable GNOME's continue-anyway sets for the relaunch.
/// Here the override stays in-process, but the names are kept so logs and
/// the probe contract (`IGNORE_RAM`/`IGNORE_CPU`, shared/probe/README.md)
/// read the same.
pub fn override_env(kind: GateKind) -> Option<&'static str> {
    match kind {
        GateKind::Ram => Some("IGNORE_RAM"),
        GateKind::Cpu => Some("IGNORE_CPU"),
        GateKind::Unsupported => None,
    }
}

/// `systemctl poweroff` on the host (Flatpak-aware, as in `dialog_poweroff`
/// and the unsupported window: the sandbox has no systemctl of its own).
pub fn poweroff_command() -> Vec<String> {
    crate::offline::host_command(&["systemctl", "poweroff"])
}

/// `systemctl reboot --firmware-setup` on the host (the poweroff dialog's
/// firmware row: a non-UEFI boot may just need one setup-screen visit).
pub fn firmware_setup_command() -> Vec<String> {
    crate::offline::host_command(&["systemctl", "reboot", "--firmware-setup"])
}

/// Kill the install wrapper's process group, the shared contract
/// ("kill your wrapper's process group", `main.rs::spawn_wrapper`):
/// fisherman runs as root and cancels when its parent dies, so signalling
/// the leader's group is what stops the install instead of orphaning it.
/// This is what GNOME's `__on_exit_response` does through
/// `view_progress.terminate()` before quitting.
pub fn terminate_process_group(leader_pid: u32) -> std::io::Result<()> {
    std::process::Command::new("kill")
        .args(["-TERM", "--", &format!("-{leader_pid}")])
        .status()
        .map(|_| ())
}

/// Whether a PCI display device of vendor `0x10de` (NVIDIA) is below
/// `root` (`/sys/bus/pci/devices`). fisherman's probe does not report the
/// GPU yet, so each frontend looks (`shared/catalog/README.md`). A machine
/// where nothing can be read has no NVIDIA GPU.
pub fn has_nvidia_gpu_in(root: &std::path::Path) -> bool {
    let Ok(entries) = std::fs::read_dir(root) else {
        return false;
    };
    let read = |path: std::path::PathBuf| {
        std::fs::read_to_string(path)
            .map(|s| s.trim().to_lowercase())
            .unwrap_or_default()
    };
    entries.flatten().any(|entry| {
        let dir = entry.path();
        // Class 0x03xxxx is a display controller (VGA, 3D, other).
        read(dir.join("vendor")) == "0x10de" && read(dir.join("class")).starts_with("0x03")
    })
}

/// [`has_nvidia_gpu_in`] for this machine. `/sys` is the host's in a
/// Flatpak too.
pub fn has_nvidia_gpu() -> bool {
    has_nvidia_gpu_in(std::path::Path::new("/sys/bus/pci/devices"))
}

/// Opens the desktop's own network settings on the host, best effort: the
/// first tool that exists. COSMIC's first, then the others a live image can
/// carry. A sandbox has none of them, so the script runs on the host.
pub fn network_settings_command() -> Vec<String> {
    const SCRIPT: &str = "if command -v cosmic-settings >/dev/null 2>&1; then exec cosmic-settings network; \
elif command -v nm-connection-editor >/dev/null 2>&1; then exec nm-connection-editor; \
elif command -v gnome-control-center >/dev/null 2>&1; then exec gnome-control-center wifi; \
elif command -v systemsettings >/dev/null 2>&1; then exec systemsettings kcm_networkmanagement; \
else exit 127; fi";
    crate::offline::host_command(&["sh", "-c", SCRIPT])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn unmet(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn no_unmet_requirements_means_no_gates() {
        assert!(blocking_gates(&[], &Overrides::default()).is_empty());
    }

    #[test]
    fn each_known_requirement_is_a_gate() {
        let gates = blocking_gates(&unmet(&["ram", "cpu", "uefi"]), &Overrides::default());
        assert_eq!(
            gates,
            vec![GateKind::Ram, GateKind::Cpu, GateKind::Unsupported]
        );
    }

    #[test]
    fn unknown_requirements_neither_block_nor_pass_silently() {
        assert_eq!(gate_for("tpm"), None);
        assert!(blocking_gates(&unmet(&["tpm"]), &Overrides::default()).is_empty());
    }

    #[test]
    fn ram_and_cpu_gates_can_be_overridden_uefi_cannot() {
        assert!(gate_overridable(GateKind::Ram));
        assert!(gate_overridable(GateKind::Cpu));
        assert!(!gate_overridable(GateKind::Unsupported));
        let full = Overrides {
            ram: true,
            cpu: true,
        };
        assert_eq!(
            blocking_gates(&unmet(&["ram", "cpu", "uefi"]), &full),
            vec![GateKind::Unsupported]
        );
        assert!(blocking_gates(&unmet(&["ram", "cpu"]), &full).is_empty());
    }

    #[test]
    fn override_names_match_the_probe_contract() {
        assert_eq!(override_env(GateKind::Ram), Some("IGNORE_RAM"));
        assert_eq!(override_env(GateKind::Cpu), Some("IGNORE_CPU"));
        assert_eq!(override_env(GateKind::Unsupported), None);
    }

    #[test]
    fn power_commands_go_to_the_host() {
        // Outside a sandbox the command is bare systemctl.
        assert!(!crate::offline::in_flatpak());
        assert_eq!(poweroff_command(), vec!["systemctl", "poweroff"]);
        assert_eq!(
            firmware_setup_command(),
            vec!["systemctl", "reboot", "--firmware-setup"]
        );
    }

    #[test]
    fn terminating_a_group_kills_its_members() {
        let mut child = std::process::Command::new("sleep")
            .arg("60")
            .process_group_for_test()
            .spawn()
            .expect("sleep");
        let pid = child.id();
        terminate_process_group(pid).expect("kill");
        let status = child.wait().expect("wait");
        use std::os::unix::process::ExitStatusExt;
        assert_eq!(status.signal(), Some(15));
    }

    /// `std::os::unix::process::CommandExt::process_group` in test-only
    /// form, so the test above builds the same leader-of-its-own-group
    /// shape `spawn_wrapper` guarantees for the real install.
    trait ProcessGroupForTest {
        fn process_group_for_test(&mut self) -> &mut Self;
    }

    impl ProcessGroupForTest for std::process::Command {
        fn process_group_for_test(&mut self) -> &mut Self {
            use std::os::unix::process::CommandExt;
            self.process_group(0);
            self
        }
    }

    fn pci_device(root: &std::path::Path, name: &str, vendor: &str, class: &str) {
        let dir = root.join(name);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("vendor"), format!("{vendor}\n")).unwrap();
        std::fs::write(dir.join("class"), format!("{class}\n")).unwrap();
    }

    #[test]
    fn an_nvidia_display_device_is_found_and_nothing_else_is() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        assert!(!has_nvidia_gpu_in(root), "an empty bus");
        assert!(!has_nvidia_gpu_in(&root.join("missing")), "no bus at all");
        // An Intel GPU, and an NVIDIA device that is not a display (audio).
        pci_device(root, "0000:00:02.0", "0x8086", "0x030000");
        pci_device(root, "0000:01:00.1", "0x10de", "0x040300");
        assert!(!has_nvidia_gpu_in(root));
        // The 3D controller of a hybrid laptop.
        pci_device(root, "0000:01:00.0", "0x10DE", "0x030200");
        assert!(has_nvidia_gpu_in(root));
    }

    #[test]
    fn network_settings_open_on_the_host_with_the_cosmic_tool_first() {
        let argv = network_settings_command();
        assert_eq!(argv[..2], ["sh", "-c"]);
        let script = &argv[2];
        let at = |tool: &str| script.find(tool).unwrap_or_else(|| panic!("{tool} missing"));
        assert!(at("cosmic-settings network") < at("nm-connection-editor"));
        assert!(at("nm-connection-editor") < at("gnome-control-center"));
    }
}
