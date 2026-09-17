package main

// Contract tests for the argv/stdout CLI the QML frontend drives with
// Quickshell's Process. Each subcommand ends in os.Exit, so these run the test
// binary as a child process (the pattern main_test.go already uses for
// `install`) and assert on its stdout, stderr and exit status — that triple is
// the whole interface the frontend sees.
//
// The child is this same coverage-instrumented binary, so `go test -cover`
// still counts what runs inside it.

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

const argvSeparator = "\x1f"

// TestMain turns this binary into the installer backend when GO_TEST_CLI_ARGV
// is set, so a test can exercise main()'s dispatch as a real process.
func TestMain(m *testing.M) {
	if argv, ok := os.LookupEnv("GO_TEST_CLI_ARGV"); ok {
		os.Args = []string{"tuna-installer-niri"}
		if argv != "" {
			os.Args = append(os.Args, strings.Split(argv, argvSeparator)...)
		}
		main()
		os.Exit(0)
	}
	os.Exit(m.Run())
}

type cliResult struct {
	stdout string
	stderr string
	code   int
}

// runCLI runs the backend as a child process with the given argv and extra
// environment, and reports everything the frontend would observe.
func runCLI(t *testing.T, env []string, argv ...string) cliResult {
	t.Helper()

	cmd := exec.Command(os.Args[0])
	cmd.Env = append(os.Environ(), "GO_TEST_CLI_ARGV="+strings.Join(argv, argvSeparator))
	cmd.Env = append(cmd.Env, env...)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	code := 0
	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if !errors.As(err, &exitErr) {
			t.Fatalf("running the backend: %v", err)
		}
		code = exitErr.ExitCode()
	}
	return cliResult{stdout: stdout.String(), stderr: stderr.String(), code: code}
}

// writeStub puts an executable script in dir; callers prepend dir to the
// child's PATH so the backend finds it instead of the real tool.
func writeStub(t *testing.T, dir, name, script string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
}

func pathWith(dir string) string {
	return "PATH=" + dir + string(os.PathListSeparator) + os.Getenv("PATH")
}

const lsblkStub = `#!/bin/sh
[ -n "$LSBLK_FAIL" ] && exit 1
printf '%s' "$LSBLK_JSON"
`

// ---------------------------------------------------------------------------
// dispatch
// ---------------------------------------------------------------------------

func TestCLIWithoutArgumentsPrintsUsageAndFails(t *testing.T) {
	got := runCLI(t, nil)

	if got.code != 1 {
		t.Errorf("exit code = %d, want 1", got.code)
	}
	for _, want := range []string{"Usage:", "discover-disks", "detect", "install", "readiness"} {
		if !strings.Contains(got.stderr, want) {
			t.Errorf("usage text is missing %q; stderr = %q", want, got.stderr)
		}
	}
	if got.stdout != "" {
		// The frontend parses stdout as JSON; diagnostics belong on stderr.
		t.Errorf("stdout = %q, want empty", got.stdout)
	}
}

func TestCLIRejectsAnUnknownCommand(t *testing.T) {
	got := runCLI(t, nil, "reformat-everything")

	if got.code != 1 {
		t.Errorf("exit code = %d, want 1", got.code)
	}
	if !strings.Contains(got.stderr, "Unknown command: reformat-everything") {
		t.Errorf("stderr = %q, want it to name the unknown command", got.stderr)
	}
	if got.stdout != "" {
		t.Errorf("stdout = %q, want empty", got.stdout)
	}
}

// ---------------------------------------------------------------------------
// discover-disks
// ---------------------------------------------------------------------------

func TestDiscoverDisksReturnsOnlyWholeDisks(t *testing.T) {
	dir := t.TempDir()
	writeStub(t, dir, "lsblk", lsblkStub)

	lsblkJSON := `{"blockdevices":[
		{"name":"nvme0n1","size":"476.9G","type":"disk","tran":"nvme"},
		{"name":"nvme0n1p1","size":"1G","type":"part"},
		{"name":"loop0","size":"4K","type":"loop"},
		{"name":"sda","size":"1.8T","type":"disk","tran":"usb"}
	]}`

	got := runCLI(t, []string{pathWith(dir), "LSBLK_JSON=" + lsblkJSON}, "discover-disks")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}
	var disks []DiskInfo
	if err := json.Unmarshal([]byte(got.stdout), &disks); err != nil {
		t.Fatalf("stdout is not the JSON array the frontend parses: %v\n%s", err, got.stdout)
	}
	if len(disks) != 2 {
		t.Fatalf("got %d disks (%v), want the 2 type=disk entries", len(disks), disks)
	}
	if disks[0].Name != "nvme0n1" || disks[0].Transport != "nvme" || disks[0].Size != "476.9G" {
		t.Errorf("first disk = %+v", disks[0])
	}
	if disks[1].Name != "sda" || disks[1].Transport != "usb" {
		t.Errorf("second disk = %+v", disks[1])
	}
}

// No disks is a legitimate answer and must stay parseable, not become a crash
// or a bare `null` the frontend cannot iterate.
func TestDiscoverDisksWithNoWholeDisksStillEmitsJSON(t *testing.T) {
	dir := t.TempDir()
	writeStub(t, dir, "lsblk", lsblkStub)

	got := runCLI(t,
		[]string{pathWith(dir), `LSBLK_JSON={"blockdevices":[{"name":"loop0","type":"loop"}]}`},
		"discover-disks")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}
	var disks []DiskInfo
	if err := json.Unmarshal([]byte(got.stdout), &disks); err != nil {
		t.Fatalf("stdout is not valid JSON: %v\n%s", err, got.stdout)
	}
	if len(disks) != 0 {
		t.Errorf("got %v, want no disks", disks)
	}
}

func TestDiscoverDisksFailsWhenLsblkFails(t *testing.T) {
	dir := t.TempDir()
	writeStub(t, dir, "lsblk", lsblkStub)

	got := runCLI(t, []string{pathWith(dir), "LSBLK_FAIL=1"}, "discover-disks")

	if got.code != 1 {
		t.Errorf("exit code = %d, want 1", got.code)
	}
	if !strings.Contains(got.stderr, "lsblk failed") {
		t.Errorf("stderr = %q, want it to report the lsblk failure", got.stderr)
	}
}

func TestDiscoverDisksFailsOnUnparseableLsblkOutput(t *testing.T) {
	dir := t.TempDir()
	writeStub(t, dir, "lsblk", lsblkStub)

	got := runCLI(t, []string{pathWith(dir), "LSBLK_JSON=not json"}, "discover-disks")

	if got.code != 1 {
		t.Errorf("exit code = %d, want 1", got.code)
	}
	if !strings.Contains(got.stderr, "parse lsblk output") {
		t.Errorf("stderr = %q, want the parse error", got.stderr)
	}
}

// A device lsblk reports in a shape DiskInfo cannot decode is skipped rather
// than failing the whole listing — the other disks still have to be offered.
func TestDiscoverDisksSkipsAnUndecodableDevice(t *testing.T) {
	dir := t.TempDir()
	writeStub(t, dir, "lsblk", lsblkStub)

	lsblkJSON := `{"blockdevices":[
		{"name":["unexpected","array"],"type":"disk"},
		{"name":"sda","size":"1.8T","type":"disk"}
	]}`

	got := runCLI(t, []string{pathWith(dir), "LSBLK_JSON=" + lsblkJSON}, "discover-disks")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}
	var disks []DiskInfo
	if err := json.Unmarshal([]byte(got.stdout), &disks); err != nil {
		t.Fatal(err)
	}
	if len(disks) != 1 || disks[0].Name != "sda" {
		t.Errorf("got %v, want only sda", disks)
	}
}

// ---------------------------------------------------------------------------
// detect
// ---------------------------------------------------------------------------

// The five keys detectEnvironment emits are the frontend's environment
// contract: installer.qml reads each one by name. Renaming or dropping one
// breaks the UI silently, so pin them.
func TestDetectEmitsTheEnvironmentContract(t *testing.T) {
	dir := t.TempDir()
	writeStub(t, dir, "bootc", "#!/bin/sh\nexit 1\n")
	writeStub(t, dir, "podman", "#!/bin/sh\nexit 1\n")
	storeDir := filepath.Join(t.TempDir(), "oci-store")
	if err := os.MkdirAll(storeDir, 0o755); err != nil {
		t.Fatal(err)
	}

	got := runCLI(t,
		[]string{pathWith(dir), "TUNA_OFFLINE_STORES=" + storeDir},
		"detect")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}

	var env map[string]any
	if err := json.Unmarshal([]byte(got.stdout), &env); err != nil {
		t.Fatalf("stdout is not the JSON object the frontend parses: %v\n%s", err, got.stdout)
	}
	for _, key := range []string{"liveImage", "offlineStores", "offlineImages", "hasTpm", "productName"} {
		if _, ok := env[key]; !ok {
			t.Errorf("detect output is missing the %q key; got %v", key, env)
		}
	}
	if _, ok := env["hasTpm"].(bool); !ok {
		t.Errorf("hasTpm = %v (%T), want a bool", env["hasTpm"], env["hasTpm"])
	}
	if _, ok := env["liveImage"].(string); !ok {
		t.Errorf("liveImage = %v (%T), want a string", env["liveImage"], env["liveImage"])
	}
	if _, ok := env["productName"].(string); !ok {
		t.Errorf("productName = %v (%T), want a string", env["productName"], env["productName"])
	}
}

func TestDetectReportsTheStoresFromTheEnvironment(t *testing.T) {
	dir := t.TempDir()
	writeStub(t, dir, "bootc", "#!/bin/sh\nexit 1\n")
	writeStub(t, dir, "podman", "#!/bin/sh\nexit 1\n")
	base := t.TempDir()
	present := filepath.Join(base, "present")
	if err := os.MkdirAll(present, 0o755); err != nil {
		t.Fatal(err)
	}
	absent := filepath.Join(base, "absent")

	got := runCLI(t,
		[]string{pathWith(dir), "TUNA_OFFLINE_STORES=" + present + string(os.PathListSeparator) + absent},
		"detect")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}
	var env struct {
		OfflineStores []string `json:"offlineStores"`
	}
	if err := json.Unmarshal([]byte(got.stdout), &env); err != nil {
		t.Fatal(err)
	}
	if len(env.OfflineStores) != 1 || env.OfflineStores[0] != present {
		t.Errorf("offlineStores = %v, want only the directory that exists (%s)", env.OfflineStores, present)
	}
}

// ---------------------------------------------------------------------------
// readiness
// ---------------------------------------------------------------------------

func TestReadinessSubcommandWritesTheStamp(t *testing.T) {
	runtimeDir := t.TempDir()

	got := runCLI(t, []string{"XDG_RUNTIME_DIR=" + runtimeDir}, "readiness", "welcome")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}
	body, err := os.ReadFile(filepath.Join(runtimeDir, stampName))
	if err != nil {
		t.Fatalf("no stamp was written: %v", err)
	}
	if !strings.Contains(string(body), "page=welcome") {
		t.Errorf("stamp = %q, want the page the frontend passed", body)
	}
}

// Without a page argument the stamp still has to be well formed — a smoke test
// parses it either way.
func TestReadinessSubcommandDefaultsThePage(t *testing.T) {
	runtimeDir := t.TempDir()

	got := runCLI(t, []string{"XDG_RUNTIME_DIR=" + runtimeDir}, "readiness")

	if got.code != 0 {
		t.Fatalf("exit code = %d, stderr = %q", got.code, got.stderr)
	}
	body, err := os.ReadFile(filepath.Join(runtimeDir, stampName))
	if err != nil {
		t.Fatalf("no stamp was written: %v", err)
	}
	if !strings.Contains(string(body), "page=unknown") {
		t.Errorf("stamp = %q, want page=unknown", body)
	}
}

// The stamp is observability. A frontend that cannot write it must still come
// up, so this path reports on stderr and exits 0 by design.
func TestReadinessSubcommandSucceedsWhenTheStampCannotBeWritten(t *testing.T) {
	got := runCLI(t, []string{"XDG_RUNTIME_DIR="}, "readiness", "welcome")

	if got.code != 0 {
		t.Fatalf("exit code = %d, want 0 — a failed stamp must not fail the UI", got.code)
	}
	if !strings.Contains(got.stderr, "readiness:") {
		t.Errorf("stderr = %q, want the failure reported", got.stderr)
	}
}

// readinessStamp itself, in process: it is the seam between the environment
// and writeReadinessStamp.
func TestReadinessStampUsesTheRuntimeDirFromTheEnvironment(t *testing.T) {
	runtimeDir := t.TempDir()
	t.Setenv("XDG_RUNTIME_DIR", runtimeDir)

	readinessStamp("disk")

	body, err := os.ReadFile(filepath.Join(runtimeDir, stampName))
	if err != nil {
		t.Fatalf("no stamp was written: %v", err)
	}
	if !strings.Contains(string(body), "page=disk") {
		t.Errorf("stamp = %q, want page=disk", body)
	}
}

func TestReadinessStampIsBestEffortWithoutARuntimeDir(t *testing.T) {
	t.Setenv("XDG_RUNTIME_DIR", "")

	// Must not panic and must not exit: the install path keeps working.
	readinessStamp("welcome")
}
