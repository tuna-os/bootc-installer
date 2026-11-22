package main

// Power actions and install cancellation (GNOME dialog_poweroff.py and
// dialog_output.py parity).
//
// dialog_poweroff runs systemctl on the host (flatpak-spawn when sandboxed:
// the runtime has no systemctl of its own); so do `poweroff`, `reboot` and
// `firmware` here. `cancel` kills the install wrapper's process group — the
// contract wrapperCommand documents ("kill your wrapper's process group") —
// using the pid file runInstall writes, so quitting mid-install from the
// window's close button or the progress page's Cancel actually stops
// fisherman instead of orphaning it. `log-path` prints the persistent log
// file dialog_output.py shows, so the QML can name it next to its Copy
// button.

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// installPidName records the wrapper's pid while an install runs. It lives
// in $XDG_RUNTIME_DIR (per-user tmpfs, cleared between sessions) next to the
// readiness stamp — never beside the recipe, which a pid file must not
// outlive or resemble.
const installPidName = "tuna-installer-fisherman.pid"

func pidfilePath() string {
	if dir := os.Getenv("XDG_RUNTIME_DIR"); dir != "" {
		return dir + "/" + installPidName
	}
	return ""
}

func writePidfile(pid int) {
	path := pidfilePath()
	if path == "" {
		return
	}
	// Best-effort: cancel without a pid file is a no-op, and the install
	// must not fail for observability's sake.
	_ = os.WriteFile(path, []byte(strconv.Itoa(pid)), 0o644)
}

func clearPidfile() {
	if path := pidfilePath(); path != "" {
		_ = os.Remove(path)
	}
}

// readPidfile returns the recorded wrapper pid, or 0 when there is nothing
// to cancel.
func readPidfile() int {
	path := pidfilePath()
	if path == "" {
		return 0
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || pid <= 0 {
		return 0
	}
	return pid
}

// cancelInstall stops the running install wrapper: SIGTERM to its process
// group, then SIGKILL after a grace period. A missing pid file or a dead
// process is success (nothing to cancel), never an error.
func cancelInstall() {
	pid := readPidfile()
	if pid == 0 {
		return
	}
	_ = syscall.Kill(-pid, syscall.SIGTERM)
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		// Signal 0 performs error checking without delivering: ESRCH
		// means the group is gone.
		if err := syscall.Kill(-pid, 0); err != nil {
			clearPidfile()
			return
		}
		time.Sleep(200 * time.Millisecond)
	}
	_ = syscall.Kill(-pid, syscall.SIGKILL)
	clearPidfile()
}

// runPower runs a host power action: systemctl on the host, through
// flatpak-spawn when sandboxed. Killing our own group is not a concern —
// these replace the session rather than signal it.
func runPower(args ...string) {
	argv := append(hostCommand(), append([]string{"systemctl"}, args...)...)
	if out, err := exec.Command(argv[0], argv[1:]...).CombinedOutput(); err != nil {
		fmt.Fprintf(os.Stderr, "power: %v\n%s", err, out)
		os.Exit(1)
	}
}

func poweroffMain() {
	runPower("poweroff")
}

func rebootMain() {
	runPower("reboot")
}

func firmwareMain() {
	// The UEFI blocked-boot remediation: reboot into the firmware setup,
	// the same row dialog_poweroff offers when Systeminfo.is_uefi().
	runPower("reboot", "--firmware-setup")
}

func cancelMain() {
	// No wrapper process group exists on the daemon path: Cancel goes over
	// a second Varlink connection while the install runs.
	if useDaemon() {
		os.Exit(daemonCancel())
	}
	cancelInstall()
}

func logPathMain() {
	path := installLogDisplayPath()
	if path == "" {
		fmt.Fprintln(os.Stderr, "log-path: could not determine install log directory: no home")
		os.Exit(1)
	}
	fmt.Println(path)
}
