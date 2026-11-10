package main

// Tests for the live-session preflight (`session-get`, `session-set`) and
// the power/cancel/log-path commands. Host tools are stubbed through PATH
// the way cli_test.go stubs sudo and fisherman; pure parsers are tested
// directly.

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// localectl status shape (trimmed): the LANG value, the X11 layout first,
// the console keymap as fallback.
func TestParseLocalectlStatus(t *testing.T) {
	locale, keyboard := parseLocalectlStatus(`System Locale: LANG=en_US.UTF-8
    VC Keymap: us
   X11 Layout: de
`)
	if locale != "en_US.UTF-8" {
		t.Errorf("locale = %q", locale)
	}
	if keyboard != "de" {
		t.Errorf("keyboard = %q, want the X11 layout over the console keymap", keyboard)
	}

	locale, keyboard = parseLocalectlStatus("   System Locale: LANG=C.UTF-8\n    VC Keymap: fr\n")
	if locale != "C.UTF-8" || keyboard != "fr" {
		t.Errorf("got %q %q, want C.UTF-8 fr", locale, keyboard)
	}
}

func TestParseTimedatectlTimezoneTrims(t *testing.T) {
	if got := parseTimedatectlTimezone("Europe/Berlin\n"); got != "Europe/Berlin" {
		t.Errorf("got %q", got)
	}
}

// session-get with stubbed host tools: current values parsed, lists passed
// through, connectivity reported. The stubs stand in for localectl and
// timedatectl on the host (PATH, non-Flatpak).
func TestSessionGetReadsStubbedHostTools(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	dir := t.TempDir()
	writeStub(t, dir, "localectl", "#!/bin/sh\n"+
		"if [ \"$1\" = \"status\" ]; then echo 'System Locale: LANG=de_DE.UTF-8'; echo '   VC Keymap: de'; "+
		"elif [ \"$1\" = \"list-locales\" ]; then echo 'de_DE.UTF-8'; echo 'en_US.UTF-8'; "+
		"elif [ \"$1\" = \"list-keymaps\" ]; then echo 'de'; echo 'us'; fi\n")
	writeStub(t, dir, "timedatectl", "#!/bin/sh\n"+
		"if [ \"$1\" = \"show\" ]; then echo 'Europe/Berlin'; "+
		"elif [ \"$1\" = \"list-timezones\" ]; then echo 'Europe/Berlin'; echo 'UTC'; fi\n")
	got := runCLI(t, []string{pathWith(dir), "XDG_RUNTIME_DIR=" + t.TempDir()}, "session-get")
	if got.code != 0 {
		t.Fatalf("code = %d, stderr = %q", got.code, got.stderr)
	}
	var state SessionState
	if err := json.Unmarshal([]byte(got.stdout), &state); err != nil {
		t.Fatalf("stdout is not a SessionState: %v\n%s", err, got.stdout)
	}
	if state.Locale.Current != "de_DE.UTF-8" || len(state.Locale.Available) != 2 {
		t.Errorf("locale = %+v", state.Locale)
	}
	if state.Keyboard.Current != "de" || len(state.Keyboard.Available) != 2 {
		t.Errorf("keyboard = %+v", state.Keyboard)
	}
	if state.Timezone.Current != "Europe/Berlin" || len(state.Timezone.Available) != 2 {
		t.Errorf("timezone = %+v", state.Timezone)
	}
}

// session-set applies each requested field through the host tools and reads
// the request from stdin (never argv: values are session configuration). On
// live media, which is the only place it changes anything.
func TestSessionSetAppliesEachField(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	dir := t.TempDir()
	calls := filepath.Join(dir, "calls")
	writeStub(t, dir, "localectl", "#!/bin/sh\necho \"localectl $@\" >> "+calls+"\n")
	writeStub(t, dir, "timedatectl", "#!/bin/sh\necho \"timedatectl $@\" >> "+calls+"\n")

	got := runCLIWithStdin(t, []string{pathWith(dir), writeFakeProbe(t, true)},
		`{"keyboard":"de","locale":"de_DE.UTF-8","timezone":"Europe/Berlin"}`)
	if got.code != 0 {
		t.Fatalf("code = %d, stderr = %q", got.code, got.stderr)
	}
	data, _ := os.ReadFile(calls)
	log := string(data)
	for _, want := range []string{"localectl set-keymap de", "localectl set-locale LANG=de_DE.UTF-8", "timedatectl set-timezone Europe/Berlin"} {
		if !strings.Contains(log, want) {
			t.Errorf("host calls lack %q:\n%s", want, log)
		}
	}
}

// Only the fields the request names are applied (#291): the QML sends what
// the user changed, and nothing else may reach the host.
func TestSessionSetAppliesOnlyTheFieldsSent(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	dir := t.TempDir()
	calls := filepath.Join(dir, "calls")
	writeStub(t, dir, "localectl", "#!/bin/sh\necho \"localectl $@\" >> "+calls+"\n")
	writeStub(t, dir, "timedatectl", "#!/bin/sh\necho \"timedatectl $@\" >> "+calls+"\n")

	got := runCLIWithStdin(t, []string{pathWith(dir), writeFakeProbe(t, true)}, `{"timezone":"Europe/Berlin"}`)
	if got.code != 0 {
		t.Fatalf("code = %d, stderr = %q", got.code, got.stderr)
	}
	data, _ := os.ReadFile(calls)
	if strings.TrimSpace(string(data)) != "timedatectl set-timezone Europe/Berlin" {
		t.Errorf("host calls = %q, want the time zone only", data)
	}

	// Nothing to apply: success, and no tool runs.
	_ = os.Remove(calls)
	got = runCLIWithStdin(t, []string{pathWith(dir), writeFakeProbe(t, true)}, `{}`)
	if got.code != 0 {
		t.Errorf("an empty request exited %d: %q", got.code, got.stderr)
	}
	if _, err := os.Stat(calls); err == nil {
		t.Error("an empty request ran a host tool")
	}
}

// Off live media the host is an installed system: session-set changes
// nothing there, and says so (#291).
func TestSessionSetChangesNothingOffLiveMedia(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	dir := t.TempDir()
	calls := filepath.Join(dir, "calls")
	writeStub(t, dir, "localectl", "#!/bin/sh\necho \"localectl $@\" >> "+calls+"\n")
	writeStub(t, dir, "timedatectl", "#!/bin/sh\necho \"timedatectl $@\" >> "+calls+"\n")

	got := runCLIWithStdin(t, []string{pathWith(dir), writeFakeProbe(t, false)},
		`{"keyboard":"de","locale":"de_DE.UTF-8","timezone":"Europe/Berlin"}`)
	if got.code != 1 || !strings.Contains(got.stderr, "not live media") {
		t.Errorf("code = %d, stderr = %q; want 1 and the reason", got.code, got.stderr)
	}
	if _, err := os.Stat(calls); err == nil {
		data, _ := os.ReadFile(calls)
		t.Errorf("the installed system's settings were changed:\n%s", data)
	}
}

// A field whose tool fails is named on stderr and exits 1, and the other
// fields are still applied; garbage on stdin exits 1 without touching the
// host.
func TestSessionSetReportsAFailedField(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	dir := t.TempDir()
	calls := filepath.Join(dir, "calls")
	writeStub(t, dir, "localectl", "#!/bin/sh\necho \"localectl $@\" >> "+calls+"\n")
	writeStub(t, dir, "timedatectl", "#!/bin/sh\nexit 1\n")

	got := runCLIWithStdin(t, []string{pathWith(dir), writeFakeProbe(t, true)},
		`{"timezone":"Nowhere/Zero","locale":"de_DE.UTF-8"}`)
	if got.code != 1 {
		t.Errorf("code = %d, want 1", got.code)
	}
	if !strings.Contains(got.stderr, "timezone:") || strings.Contains(got.stderr, "locale:") {
		t.Errorf("stderr = %q, want the failed field named, and only it", got.stderr)
	}
	if data, _ := os.ReadFile(calls); !strings.Contains(string(data), "set-locale LANG=de_DE.UTF-8") {
		t.Errorf("the locale was not applied after the time zone failed: %q", data)
	}

	got = runCLIWithStdin(t, []string{pathWith(dir), writeFakeProbe(t, true)}, `{nope`)
	if got.code != 1 {
		t.Errorf("code = %d, want 1 for invalid JSON", got.code)
	}
}

// The connectivity check (#301): the registry of the selected image on 443
// first, then the shared targets every frontend uses.
func TestNetcheckTargetsStartWithTheImagesRegistry(t *testing.T) {
	cases := map[string][]string{
		"":                                       {"ghcr.io:443", "8.8.8.8:53"},
		"quay.io/centos-bootc/centos-bootc:c10s": {"quay.io:443", "ghcr.io:443", "8.8.8.8:53"},
		"ghcr.io/example/os:stable":              {"ghcr.io:443", "8.8.8.8:53"},
		"registry.example:5000/os/atlas:1":       {"registry.example:5000", "ghcr.io:443", "8.8.8.8:53"},
		"docker://registry.example/os/atlas@sha256:00":           {"registry.example:443", "ghcr.io:443", "8.8.8.8:53"},
		"ostree-unverified-registry:registry.example/os/atlas:1": {"registry.example:443", "ghcr.io:443", "8.8.8.8:53"},
		"localhost/os:dev":                    {"localhost:443", "ghcr.io:443", "8.8.8.8:53"},
		"library/fedora:42":                   {"registry-1.docker.io:443", "ghcr.io:443", "8.8.8.8:53"},
		"fedora":                              {"registry-1.docker.io:443", "ghcr.io:443", "8.8.8.8:53"},
		"containers-storage:localhost/os:dev": {"ghcr.io:443", "8.8.8.8:53"},
		"oci:/var/lib/images/os":              {"ghcr.io:443", "8.8.8.8:53"},
	}
	for image, want := range cases {
		if got := netcheckTargets(image); strings.Join(got, " ") != strings.Join(want, " ") {
			t.Errorf("netcheckTargets(%q) = %v, want %v", image, got, want)
		}
	}
}

// shared/network/targets.json: the targets of each reference, the timeout
// and the variables that turn the check off, as in every frontend.
func TestNetcheckTargetsFollowTheSharedFixture(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "..", "shared", "network", "targets.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Shared    []string `json:"shared_targets"`
		Timeout   int      `json:"timeout_seconds"`
		SkipEnv   []string `json:"skip_env"`
		SkipCases []struct {
			Env  map[string]string `json:"env"`
			Skip bool              `json:"skip"`
		} `json:"skip_cases"`
		Cases []struct {
			Imgref  string   `json:"imgref"`
			Targets []string `json:"targets"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	if len(fixture.Cases) < 20 {
		t.Fatalf("%d cases", len(fixture.Cases))
	}
	for _, c := range fixture.Cases {
		if got := netcheckTargets(c.Imgref); strings.Join(got, " ") != strings.Join(c.Targets, " ") {
			t.Errorf("netcheckTargets(%q) = %v, want %v", c.Imgref, got, c.Targets)
		}
	}
	if strings.Join(netcheckFallbacks, " ") != strings.Join(fixture.Shared, " ") {
		t.Errorf("shared targets %v, want %v", netcheckFallbacks, fixture.Shared)
	}
	if netcheckTimeout != time.Duration(fixture.Timeout)*time.Second {
		t.Errorf("timeout %v, want %ds", netcheckTimeout, fixture.Timeout)
	}
	if strings.Join(netcheckSkipEnv, " ") != strings.Join(fixture.SkipEnv, " ") {
		t.Errorf("skip variables %v, want %v", netcheckSkipEnv, fixture.SkipEnv)
	}
	for _, c := range fixture.SkipCases {
		if got := netcheckSkipped(func(name string) string { return c.Env[name] }); got != c.Skip {
			t.Errorf("env %v: skipped = %v, want %v", c.Env, got, c.Skip)
		}
	}
}

func TestCheckConnectivityTriesTheTargetsInOrder(t *testing.T) {
	var dialled []string
	answers := func(up ...string) dialer {
		return func(address string, _ time.Duration) error {
			dialled = append(dialled, address)
			if contains(up, address) {
				return nil
			}
			return os.ErrDeadlineExceeded
		}
	}
	image := "quay.io/example/os:1"

	connected, target := checkConnectivity(image, answers("quay.io:443", "ghcr.io:443"))
	if !connected || target != "quay.io:443" || len(dialled) != 1 {
		t.Errorf("registry up: connected=%v target=%q dialled=%v", connected, target, dialled)
	}

	dialled = nil
	connected, target = checkConnectivity(image, answers("8.8.8.8:53"))
	if !connected || target != "8.8.8.8:53" || strings.Join(dialled, " ") != "quay.io:443 ghcr.io:443 8.8.8.8:53" {
		t.Errorf("fallback: connected=%v target=%q dialled=%v", connected, target, dialled)
	}

	dialled = nil
	connected, target = checkConnectivity(image, answers())
	if connected || target != "" || len(dialled) != 3 {
		t.Errorf("offline: connected=%v target=%q dialled=%v", connected, target, dialled)
	}
}

// network-settings starts the first network tool the host has, and fails
// with a reason when it has none.
func TestNetworkSettingsOpensTheFirstToolTheHostHas(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	dir := t.TempDir()
	ran := filepath.Join(dir, "ran")
	// Only the second candidate exists. PATH holds nothing else but sh's
	// own directory, so no real tool of this machine is found.
	writeStub(t, dir, "cosmic-settings", "#!/bin/sh\necho \"$@\" > "+ran+"\n")
	sh, err := exec.LookPath("sh")
	if err != nil {
		t.Skip("no sh")
	}
	path := "PATH=" + dir + string(os.PathListSeparator) + filepath.Dir(sh)
	for _, tool := range networkTools {
		if _, statErr := os.Stat(filepath.Join(filepath.Dir(sh), tool[0])); statErr == nil {
			t.Skip("this machine has a real network tool beside sh")
		}
	}
	got := runCLI(t, []string{path}, "network-settings")
	if got.code != 0 || strings.TrimSpace(got.stdout) != "cosmic-settings" {
		t.Fatalf("code = %d, stdout = %q, stderr = %q", got.code, got.stdout, got.stderr)
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if data, err := os.ReadFile(ran); err == nil && strings.TrimSpace(string(data)) == "network" {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Errorf("cosmic-settings did not run with its network page")
}

func TestNetworkSettingsWithNoToolFails(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	sh, err := exec.LookPath("sh")
	if err != nil {
		t.Skip("no sh")
	}
	for _, tool := range networkTools {
		if _, statErr := os.Stat(filepath.Join(filepath.Dir(sh), tool[0])); statErr == nil {
			t.Skip("this machine has a real network tool beside sh")
		}
	}
	got := runCLI(t, []string{"PATH=" + filepath.Dir(sh)}, "network-settings")
	if got.code != 1 || !strings.Contains(got.stderr, "no network settings tool") {
		t.Errorf("code = %d, stderr = %q", got.code, got.stderr)
	}
}

// cancel with no install running is success: there is nothing to stop.
func TestCancelWithoutAPidfileSucceeds(t *testing.T) {
	got := runCLI(t, []string{"XDG_RUNTIME_DIR=" + t.TempDir()}, "cancel")
	if got.code != 0 {
		t.Errorf("code = %d, stderr = %q; want 0 with nothing to cancel", got.code, got.stderr)
	}
}

// cancel kills the recorded process group: a sleeper started in its own
// group (the shape wrapperCommand gives the install wrapper) must be gone
// after `cancel`, and the pid file with it.
func TestCancelKillsTheRecordedProcessGroup(t *testing.T) {
	runtime := t.TempDir()
	started := make(chan int, 1)
	go func() {
		cmd := testSleeper(t, runtime)
		started <- cmd.Process.Pid
		_ = cmd.Wait()
	}()
	pid := <-started
	writePid := func() {
		if err := os.WriteFile(filepath.Join(runtime, installPidName), []byte(itoa(pid)), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	writePid()

	got := runCLI(t, []string{"XDG_RUNTIME_DIR=" + runtime}, "cancel")
	if got.code != 0 {
		t.Fatalf("code = %d, stderr = %q", got.code, got.stderr)
	}
	deadline := time.Now().Add(10 * time.Second)
	for processGroupAlive(pid) {
		if time.Now().After(deadline) {
			t.Fatalf("process group %d still alive after cancel", pid)
		}
		time.Sleep(100 * time.Millisecond)
	}
	if _, err := os.Stat(filepath.Join(runtime, installPidName)); !os.IsNotExist(err) {
		t.Errorf("pid file survived the cancel")
	}
}

// log-path prints the same file the installer appends to.
func TestLogPathNamesTheInstallLog(t *testing.T) {
	stateHome := t.TempDir()
	got := runCLI(t, []string{"XDG_STATE_HOME=" + stateHome}, "log-path")
	if got.code != 0 {
		t.Fatalf("code = %d, stderr = %q", got.code, got.stderr)
	}
	want := filepath.Join(stateHome, "tuna-installer", "install.log")
	if strings.TrimSpace(got.stdout) != want {
		t.Errorf("log-path = %q, want %q", got.stdout, want)
	}
}

// poweroff and reboot shell to systemctl on the host: the stub records the
// call, and a failing systemctl exits 1 with the reason on stderr.
func TestPowerCommandsReachHostSystemctl(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	for _, tc := range []struct {
		cmd  string
		want string
	}{
		{"poweroff", "poweroff"},
		{"reboot", "reboot"},
		{"firmware", "reboot --firmware-setup"},
	} {
		dir := t.TempDir()
		calls := filepath.Join(dir, "calls")
		writeStub(t, dir, "systemctl", "#!/bin/sh\necho \"$@\" > "+calls+"\n")
		got := runCLI(t, []string{pathWith(dir)}, tc.cmd)
		if got.code != 0 {
			t.Fatalf("%s: code = %d, stderr = %q", tc.cmd, got.code, got.stderr)
		}
		data, _ := os.ReadFile(calls)
		if strings.TrimSpace(string(data)) != tc.want {
			t.Errorf("%s ran systemctl %q, want %q", tc.cmd, data, tc.want)
		}
	}
}
