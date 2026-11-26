package main

// Tests for the fishermand path (daemon.go): recipe mapping, event
// translation, mode switching, and the Varlink calls against a scripted
// peer. The peer speaks the wire format only, like shared/client's tests.
// TUNA_TEST_FISHERMAN_SOCK points at a live mock for the integration test.

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"tuna-installer-niri/varlink"
)

func strp(s string) *string { return &s }
func intp(i int) *int       { return &i }

func TestBackendModeDefault(t *testing.T) {
	t.Setenv(daemonEnvBackend, "")
	t.Setenv(daemonEnvSocket, filepath.Join(t.TempDir(), "no-such-socket"))
	if got := backendMode(); got != "legacy" {
		t.Fatalf("missing socket without override: got %q, want legacy", got)
	}
}

func TestBackendModeOverride(t *testing.T) {
	t.Setenv(daemonEnvSocket, filepath.Join(t.TempDir(), "no-such-socket"))
	t.Setenv(daemonEnvBackend, "daemon")
	if got := backendMode(); got != "daemon" {
		t.Fatalf("forced daemon: got %q", got)
	}
	t.Setenv(daemonEnvBackend, "legacy")
	if got := backendMode(); got != "legacy" {
		t.Fatalf("forced legacy: got %q", got)
	}
}

func TestBackendModeAutoDetectsSocket(t *testing.T) {
	dir := t.TempDir()
	sock := filepath.Join(dir, "io.tunaos.Fisherman")
	f, err := os.Create(sock)
	if err != nil {
		t.Fatal(err)
	}
	f.Close()
	t.Setenv(daemonEnvBackend, "")
	t.Setenv(daemonEnvSocket, sock)
	if got := backendMode(); got != "daemon" {
		t.Fatalf("present socket: got %q, want daemon", got)
	}
}

func TestRecipeEncryptionType(t *testing.T) {
	for recipe, daemon := range map[string]string{
		"none": "none", "luks-passphrase": "luks_passphrase",
		"tpm2-luks": "tpm2_luks", "tpm2-luks-passphrase": "tpm2_luks_passphrase",
	} {
		got, err := recipeEncryptionType(recipe)
		if err != nil || got != daemon {
			t.Errorf("%q: got %q, %v; want %q", recipe, got, err, daemon)
		}
	}
	if _, err := recipeEncryptionType("rot13"); err == nil {
		t.Error("unknown encryption type: no error")
	}
}

func fullRecipe() Recipe {
	return Recipe{
		Disk: "dev-nvme", Filesystem: "btrfs",
		Encryption: Encryption{Type: "luks-passphrase", Passphrase: "correct horse 1"},
		Hostname:   "niri-box",
		User:       &User{Username: "tuna", Fullname: "Tuna User", Password: "s3cr3t-pw"},
	}
}

func TestRecipeToConfig(t *testing.T) {
	cfg, err := recipeToConfig(fullRecipe(), "erase")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Disk == nil || *cfg.Disk != "dev-nvme" {
		t.Errorf("disk: %+v", cfg.Disk)
	}
	if cfg.InstallMode == nil || *cfg.InstallMode != "erase" {
		t.Errorf("installMode: %+v", cfg.InstallMode)
	}
	if cfg.Encryption == nil || cfg.Encryption.Type != "luks_passphrase" ||
		cfg.Encryption.Passphrase == nil || *cfg.Encryption.Passphrase != "correct horse 1" {
		t.Errorf("encryption: %+v", cfg.Encryption)
	}
	if cfg.User == nil || cfg.User.Username != "tuna" ||
		cfg.User.FullName == nil || *cfg.User.FullName != "Tuna User" ||
		cfg.User.Password == nil || *cfg.User.Password != "s3cr3t-pw" {
		t.Errorf("user: %+v", cfg.User)
	}
	if cfg.Hostname == nil || *cfg.Hostname != "niri-box" {
		t.Errorf("hostname: %+v", cfg.Hostname)
	}
}

func TestRecipeToConfigMinimal(t *testing.T) {
	cfg, err := recipeToConfig(Recipe{Encryption: Encryption{Type: "none"}}, "free_space")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Disk != nil || cfg.User != nil || cfg.Hostname != nil {
		t.Errorf("absent keys must stay out: %+v", cfg)
	}
	if cfg.Encryption == nil || cfg.Encryption.Type != "none" || cfg.Encryption.Passphrase != nil {
		t.Errorf("encryption: %+v", cfg.Encryption)
	}
}
func TestRecipeToConfigMode(t *testing.T) {
	cfg, err := recipeToConfig(Recipe{Encryption: Encryption{Type: "none"}}, "free_space")
	if err != nil {
		t.Fatal(err)
	}
	if cfg.InstallMode == nil || *cfg.InstallMode != "free_space" {
		t.Errorf("installMode: %+v", cfg.InstallMode)
	}
	if _, err := recipeToConfig(Recipe{Encryption: Encryption{Type: "none"}}, "wipe"); err == nil {
		t.Error("unknown install mode: no error")
	}
}

func TestParseInstallInput(t *testing.T) {
	raw, _ := json.Marshal(fullRecipe())
	recipe, mode, err := parseInstallInput(string(raw))
	if err != nil || mode != "erase" {
		t.Fatalf("bare recipe: mode %q, err %v", mode, err)
	}
	if recipe.Disk != "dev-nvme" {
		t.Errorf("bare recipe disk: %q", recipe.Disk)
	}
	envelope, _ := json.Marshal(map[string]any{
		"recipe": json.RawMessage(raw), "installMode": "free_space"})
	recipe, mode, err = parseInstallInput(string(envelope))
	if err != nil || mode != "free_space" {
		t.Fatalf("envelope: mode %q, err %v", mode, err)
	}
	if recipe.Disk != "dev-nvme" {
		t.Errorf("envelope recipe disk: %q", recipe.Disk)
	}
	bad, mode, err := parseInstallInput(`{"recipe": {}, "installMode": "wipe"}`)
	if err != nil {
		t.Fatalf("envelope parses, the mode fails later: %v", err)
	}
	if _, err := recipeToConfig(bad, mode); err == nil {
		t.Error("bad envelope mode: no error")
	}
	if _, _, err := parseInstallInput(`not json`); err == nil {
		t.Error("garbage: no error")
	}
}
func TestRecoveryQRGrid(t *testing.T) {
	key := "firguvuh-cfclrvjn-kenfevun-kbunfgfc-nkebjtcn-cfdkrfgj-kitefifu-litfbtbn"
	grid := recoveryQR(key)
	if grid == nil {
		t.Fatal("no grid for a real key")
	}
	size, _ := grid["size"].(int)
	cells, _ := grid["cells"].([]int)
	if size < 21 || len(cells) != size*size {
		t.Fatalf("size %d, %d cells", size, len(cells))
	}
	dark := 0
	for _, c := range cells {
		dark += c
	}
	if dark == 0 || dark == len(cells) {
		t.Error("grid is blank or solid")
	}
	// The bitmap carries its quiet zone: white corners, and the finder
	// square starts at (4, 4).
	if cells[0] != 0 || cells[size-1] != 0 || cells[(size-1)*size] != 0 {
		t.Error("no quiet zone in the corners")
	}
	if cells[4*size+4] != 1 {
		t.Error("no finder square at (4, 4)")
	}
}

func TestFragmentToConfig(t *testing.T) {
	frag := map[string]any{
		"hostname":   "niri-box",
		"filesystem": "btrfs", // no Config counterpart: dropped
		"encryption": map[string]any{"type": "tpm2-luks-passphrase", "passphrase": "pw"},
		"user":       map[string]any{"username": "tuna", "fullname": "Tuna"},
		"image":      "ghcr.io/x/y", // image keys: dropped
	}
	cfg, err := fragmentToConfig(frag)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Hostname == nil || *cfg.Hostname != "niri-box" {
		t.Errorf("hostname: %+v", cfg.Hostname)
	}
	if cfg.Encryption == nil || cfg.Encryption.Type != "tpm2_luks_passphrase" {
		t.Errorf("encryption: %+v", cfg.Encryption)
	}
	if cfg.User == nil || cfg.User.Username != "tuna" ||
		cfg.User.FullName == nil || *cfg.User.FullName != "Tuna" {
		t.Errorf("user: %+v", cfg.User)
	}
	if cfg.Disk != nil {
		t.Errorf("disk must stay out: %+v", cfg.Disk)
	}
}

func TestTransportLabel(t *testing.T) {
	for in, want := range map[string]string{
		"nvme": "NVMe", "usb": "USB", "sata": "SATA", "": "", "mmc": "Mmc",
	} {
		if got := transportLabel(in); got != want {
			t.Errorf("%q: got %q, want %q", in, got, want)
		}
	}
}

func ev(event string, stepID string, pct int) daemonInstallEvent {
	return daemonInstallEvent{Event: event, StepID: strp(stepID),
		StepIndex: intp(2), TotalSteps: intp(10), OverallPct: pct,
		Message: strp("Working")}
}

func TestTranslateInstallStreamLines(t *testing.T) {
	var out strings.Builder
	events := []daemonInstallEvent{
		ev("step_started", "partition", 4),
		ev("progress", "partition", 5),
		ev("warning", "", 5),
		{Event: "complete", OverallPct: 100},
	}
	if got := translateInstallStream(&out, events); got != installComplete {
		t.Fatalf("result: got %v, want complete", got)
	}
	var lines []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		var m map[string]any
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Fatalf("line is not JSON: %q", line)
		}
		lines = append(lines, m)
	}
	if len(lines) != 4 {
		t.Fatalf("%d lines: %s", len(lines), out.String())
	}
	if lines[0]["type"] != "step" || lines[0]["step_id"] != "partition" ||
		lines[0]["step"] != float64(2) || lines[0]["total_steps"] != float64(10) {
		t.Errorf("step line: %v", lines[0])
	}
	if lines[0]["step_name"] == "" {
		t.Error("step line needs a fallback label for the progress page")
	}
	if lines[1]["type"] != "substep" || lines[1]["overall_pct"] != float64(5) {
		t.Errorf("progress line: %v", lines[1])
	}
	if lines[2]["type"] != "info" {
		t.Errorf("warning line: %v", lines[2])
	}
	if lines[3]["type"] != "complete" {
		t.Errorf("complete line: %v", lines[3])
	}
}

func TestTranslateInstallStreamFailed(t *testing.T) {
	var out strings.Builder
	reason, msg := "repart_failed", "systemd-repart failed"
	events := []daemonInstallEvent{ev("step_started", "partition", 4),
		{Event: "failed", StepID: strp("partition"), OverallPct: 4,
			Message: &msg, Reason: &reason}}
	if got := translateInstallStream(&out, events); got != installFailed {
		t.Fatalf("result: got %v, want failed", got)
	}
	var m map[string]any
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if err := json.Unmarshal([]byte(lines[len(lines)-1]), &m); err != nil {
		t.Fatal(err)
	}
	if m["type"] != "error" || m["code"] != "repart_failed" || m["step_id"] != "partition" {
		t.Errorf("error line: %v", m)
	}
}

func TestTranslateInstallStreamCancelled(t *testing.T) {
	var out strings.Builder
	events := []daemonInstallEvent{ev("step_started", "install_os", 40),
		{Event: "cancelled", OverallPct: 49}}
	if got := translateInstallStream(&out, events); got != installCancelled {
		t.Fatalf("result: got %v, want cancelled", got)
	}
	if strings.Contains(out.String(), "error") {
		t.Errorf("cancelled must not emit an error line: %s", out.String())
	}
}

func TestDaemonStepNames(t *testing.T) {
	for _, id := range []string{"validate_device", "partition", "luks",
		"tpm2_enroll", "mount", "install_os", "configure", "post_fixups",
		"bootloader", "finalize", "cleanup"} {
		if daemonStepName(id) == "" {
			t.Errorf("no fallback label for step %q", id)
		}
	}
}

// scriptedPeer serves one canned reply list per method over a UNIX socket.
func scriptedPeer(t *testing.T, replies map[string][]string) string {
	t.Helper()
	sock := filepath.Join(t.TempDir(), "fisherman")
	ln, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer c.Close()
				r := bufio.NewReader(c)
				for {
					raw, err := r.ReadBytes(0)
					if err != nil {
						return
					}
					var req struct {
						Method string `json:"method"`
					}
					if err := json.Unmarshal(raw[:len(raw)-1], &req); err != nil {
						return
					}
					for _, rep := range replies[req.Method] {
						fmt.Fprintf(c, "%s\x00", rep)
					}
				}
			}(c)
		}
	}()
	return sock
}

func reply(params string, continues bool) string {
	if continues {
		return fmt.Sprintf(`{"parameters":%s,"continues":true}`, params)
	}
	return fmt.Sprintf(`{"parameters":%s}`, params)
}

func withDaemonSocket(t *testing.T, sock string) {
	t.Helper()
	t.Setenv(daemonEnvBackend, "")
	t.Setenv(daemonEnvSocket, sock)
	if !useDaemon() {
		t.Fatal("test socket not picked up")
	}
}

func TestDaemonProbeFacts(t *testing.T) {
	sock := scriptedPeer(t, map[string][]string{
		"io.tunaos.Fisherman.Requirements": {reply(
			`{"meetsRequirements":false,"gates":[`+
				`{"id":"ram","ok":false,"severity":"warn","message":"low"},`+
				`{"id":"cpu","ok":true,"severity":"block","message":"ok"},`+
				`{"id":"firmware","ok":false,"severity":"block","message":"legacy"}]}`, false)},
		"io.tunaos.Fisherman.Probe": {reply(
			`{"protocolVersion":1,"disks":[`+
				`{"path":"/dev/nvme0n1","sizeBytes":1,"sizeLabel":"476.9 GiB","model":"M","vendor":"V",`+
				`"transport":"nvme","removable":false,"eligible":true,"freeBytes":1,"minimalSizeBytes":1,`+
				`"intelRst":false,"existingData":{"hasPartitionTable":false,"partitions":[],"operatingSystems":[],"hasLuks":false}},`+
				`{"path":"/dev/sdb","sizeBytes":1,"sizeLabel":"8 GiB","model":"","vendor":"",`+
				`"transport":"usb","removable":true,"eligible":false,"freeBytes":1,"minimalSizeBytes":1,`+
				`"intelRst":false,"existingData":{"hasPartitionTable":false,"partitions":[],"operatingSystems":[],"hasLuks":false}}],`+
				`"tpm":{"present":true,"version":"2.0","usable":true},`+
				`"intelRst":{"detected":false,"affectedDisks":[]},`+
				`"live":{"isLive":true,"liveImage":"ghcr.io/mock:live"}}`, false)},
	})
	withDaemonSocket(t, sock)
	facts, err := daemonProbeFacts()
	if err != nil {
		t.Fatal(err)
	}
	if len(facts.Unmet) != 2 || facts.Unmet[0] != "ram" || facts.Unmet[1] != "uefi" {
		t.Errorf("unmet: %v", facts.Unmet)
	}
	if !facts.TPMUsable || !facts.IsLive || facts.LiveImage != "ghcr.io/mock:live" {
		t.Errorf("facts: %+v", facts)
	}
	if len(facts.Disks) != 1 || facts.Disks[0].Path != "/dev/nvme0n1" ||
		facts.Disks[0].TransportLabel != "NVMe" || facts.Disks[0].Title != "M" {
		t.Errorf("disks: %+v", facts.Disks)
	}
	// No handoff hint in this Probe: the mode falls back to reboot.
	if facts.HandoffMode != "reboot" || facts.HandoffReason != "" {
		t.Errorf("handoff: mode %q reason %q", facts.HandoffMode, facts.HandoffReason)
	}
}

func TestDaemonProbeFactsRstAndData(t *testing.T) {
	sock := scriptedPeer(t, map[string][]string{
		"io.tunaos.Fisherman.Requirements": {reply(
			`{"meetsRequirements":true,"gates":[]}`, false)},
		"io.tunaos.Fisherman.Probe": {reply(
			`{"protocolVersion":1,"disks":[`+
				`{"path":"/dev/nvme0n1","sizeBytes":1,"sizeLabel":"476.9 GiB","model":"M","vendor":"V",`+
				`"transport":"nvme","removable":false,"eligible":true,"freeBytes":100,"minimalSizeBytes":10,`+
				`"intelRst":true,"existingData":{"hasPartitionTable":true,"partitionTableType":"gpt",`+
				`"partitions":[{"path":"/dev/nvme0n1p1","sizeBytes":5}],"operatingSystems":["Windows 11"],"hasLuks":false}}],`+
				`"tpm":{"present":true,"version":"2.0","usable":true},`+
				`"intelRst":{"detected":true,"mode":"vmd","affectedDisks":["/dev/nvme0n1"]},`+
				`"live":{"isLive":true}}`, false)},
	})
	withDaemonSocket(t, sock)
	facts, err := daemonProbeFacts()
	if err != nil {
		t.Fatal(err)
	}
	if !facts.IntelRst {
		t.Error("IntelRst not carried")
	}
	if len(facts.Disks) != 1 {
		t.Fatalf("disks: %+v", facts.Disks)
	}
	d := facts.Disks[0]
	if !d.HasData || d.FreeBytes != 100 || d.MinimalBytes != 10 || !d.IntelRst {
		t.Errorf("disk detail lost: %+v", d)
	}
}

func TestDaemonProbeFactsHandoff(t *testing.T) {
	probe := func(handoff string) ProbeFacts {
		sock := scriptedPeer(t, map[string][]string{
			"io.tunaos.Fisherman.Requirements": {reply(
				`{"meetsRequirements":true,"gates":[]}`, false)},
			"io.tunaos.Fisherman.Probe": {reply(
				`{"protocolVersion":1,"disks":[],"tpm":{"present":true,"version":"2.0","usable":true},`+
					`"intelRst":{"detected":false,"affectedDisks":[]},"live":{"isLive":true},`+
					handoff+`}`, false)},
		})
		withDaemonSocket(t, sock)
		facts, err := daemonProbeFacts()
		if err != nil {
			t.Fatal(err)
		}
		return facts
	}
	got := probe(`"handoff":{"mode":"migrate","reason":"btrfs seed"}`)
	if got.HandoffMode != "migrate" || got.HandoffReason != "btrfs seed" {
		t.Errorf("hint: mode %q reason %q", got.HandoffMode, got.HandoffReason)
	}
	got = probe(`"handoff":{"mode":"soft_reboot"}`)
	if got.HandoffMode != "soft_reboot" || got.HandoffReason != "" {
		t.Errorf("no reason: mode %q reason %q", got.HandoffMode, got.HandoffReason)
	}
	got = probe(`"handoff":{"mode":"hyperloop"}`)
	if got.HandoffMode != "reboot" {
		t.Errorf("unknown mode: got %q, want reboot", got.HandoffMode)
	}
}

func TestDaemonValidate(t *testing.T) {
	sock := scriptedPeer(t, map[string][]string{
		"io.tunaos.Fisherman.Validate": {reply(
			`{"valid":false,"errors":[{"field":"hostname","code":"hostname_invalid_char","message":"bad"}]}`, false)},
	})
	withDaemonSocket(t, sock)
	var out strings.Builder
	code, err := daemonValidate(map[string]any{"hostname": "bad host!"}, &out)
	if err != nil {
		t.Fatal(err)
	}
	if code != 1 {
		t.Errorf("code: got %d, want 1", code)
	}
	var answer struct {
		Valid  bool            `json:"valid"`
		Errors []daemonProblem `json:"errors"`
	}
	if err := json.Unmarshal([]byte(out.String()), &answer); err != nil {
		t.Fatal(err)
	}
	if answer.Valid || len(answer.Errors) != 1 || answer.Errors[0].Field != "hostname" {
		t.Errorf("answer: %s", out.String())
	}
}

func TestDaemonErrorHidesSecrets(t *testing.T) {
	secret := "correct-horse-battery-staple-9"
	sock := scriptedPeer(t, map[string][]string{
		"io.tunaos.Fisherman.Validate": {
			`{"error":"io.tunaos.Fisherman.InvalidConfig","parameters":{"errors":[{"field":"x","secret":"` + secret + `"}]}}`},
	})
	withDaemonSocket(t, sock)
	var out strings.Builder
	code, err := daemonValidate(map[string]any{"hostname": "h"}, &out)
	if err == nil {
		t.Fatalf("code %d without error", code)
	}
	if strings.Contains(err.Error(), secret) {
		t.Errorf("error text carries a secret: %v", err)
	}
	if code != 2 {
		t.Errorf("code: got %d, want 2", code)
	}
}

func TestDaemonConfigureTarget(t *testing.T) {
	var gotParams map[string]any
	// A request-capturing peer: the client must send the daemon's key
	// names, never the recipe's.
	dir := t.TempDir()
	path := filepath.Join(dir, "fisherman")
	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	go func() {
		c, err := ln.Accept()
		if err != nil {
			return
		}
		defer c.Close()
		r := bufio.NewReader(c)
		raw, err := r.ReadBytes(0)
		if err != nil {
			return
		}
		var req struct {
			Method     string         `json:"method"`
			Parameters map[string]any `json:"parameters"`
		}
		if err := json.Unmarshal(raw[:len(raw)-1], &req); err != nil {
			return
		}
		gotParams = req.Parameters
		fmt.Fprintf(c, "%s\x00", reply(`{"configured":true,"errors":[]}`, false))
	}()
	withDaemonSocket(t, path)
	var out strings.Builder
	code := daemonConfigureTarget(map[string]any{
		"user":     map[string]any{"username": "tuna", "fullname": "Tuna User", "password": "s3cr3t"},
		"hostname": "niri-box",
		"timezone": "Europe/Berlin",
		"locale":   "de_DE.UTF-8",
		"keymap":   "de",
		// The privacy object travels as one; the QML sends it only when
		// the user touched the toggle.
		"privacy": map[string]any{"locationServices": true},
	}, &out)
	if code != 0 {
		t.Fatalf("code %d: %s", code, out.String())
	}
	user, _ := gotParams["user"].(map[string]any)
	if user["username"] != "tuna" || user["fullName"] != "Tuna User" || user["password"] != "s3cr3t" {
		t.Errorf("user params: %v", gotParams["user"])
	}
	if _, ok := user["fullname"]; ok {
		t.Errorf("recipe key fullname must not cross: %v", user)
	}
	if gotParams["timeZone"] != "Europe/Berlin" {
		t.Errorf("timezone must cross as timeZone: %v", gotParams)
	}
	if _, ok := gotParams["timezone"]; ok {
		t.Errorf("lowercase timezone must not cross: %v", gotParams)
	}
	privacy, _ := gotParams["privacy"].(map[string]any)
	if privacy["locationServices"] != true {
		t.Errorf("privacy object must cross: %v", gotParams)
	}
	if _, ok := gotParams["locationServices"]; ok {
		t.Errorf("bare locationServices must not cross: %v", gotParams)
	}
}

func TestDaemonInstallStreamFromPeer(t *testing.T) {
	sock := scriptedPeer(t, map[string][]string{
		"io.tunaos.Fisherman.Install": {
			reply(`{"event":"step_started","stepId":"partition","stepIndex":1,"totalSteps":10,"overallPct":4}`, true),
			reply(`{"event":"progress","stepId":"install_os","stepIndex":5,"totalSteps":10,"overallPct":50}`, true),
			reply(`{"event":"complete","overallPct":100}`, false),
		},
	})
	withDaemonSocket(t, sock)
	conn, err := daemonDial()
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	var out strings.Builder
	result := installFailed
	err = conn.CallMore("io.tunaos.Fisherman.Install",
		map[string]any{"config": map[string]any{}, "confirmed": true},
		func(raw json.RawMessage) bool {
			var ev daemonInstallEvent
			if err := varlink.Decode(raw, &ev); err != nil {
				t.Errorf("bad event: %v", err)
				return false
			}
			emitInstallLine(&out, ev)
			if ev.Event == "complete" {
				result = installComplete
			}
			return true
		})
	if err != nil {
		t.Fatal(err)
	}
	if result != installComplete {
		t.Fatalf("result %v: %s", result, out.String())
	}
	n := len(strings.Split(strings.TrimSpace(out.String()), "\n"))
	if n != 3 {
		t.Errorf("%d lines, want 3: %s", n, out.String())
	}
}

// TestDaemonIntegration runs the read-only calls against a live mock. It
// needs the mock daemon: start one first, then
// TUNA_TEST_FISHERMAN_SOCK=<socket-dir> go test -run Integration ./...
func TestDaemonIntegration(t *testing.T) {
	dir := os.Getenv("TUNA_TEST_FISHERMAN_SOCK")
	if dir == "" {
		t.Skip("TUNA_TEST_FISHERMAN_SOCK not set")
	}
	t.Setenv(daemonEnvBackend, "")
	t.Setenv(daemonEnvSocket, filepath.Join(dir, "io.tunaos.Fisherman"))
	facts, err := daemonProbeFacts()
	if err != nil {
		t.Fatal(err)
	}
	if len(facts.Disks) == 0 {
		t.Error("mock offers no disks")
	}
	var out strings.Builder
	code, err := daemonValidate(map[string]any{"hostname": "niri-box",
		"user":       map[string]any{"username": "tuna"},
		"encryption": map[string]any{"type": "none"}}, &out)
	if err != nil || code != 0 {
		t.Errorf("good fragment: code %d, err %v: %s", code, err, out.String())
	}
	out.Reset()
	code, err = daemonValidate(map[string]any{"hostname": "bad host!"}, &out)
	if err != nil || code != 1 {
		t.Errorf("bad hostname: code %d, err %v: %s", code, err, out.String())
	}
	if !strings.Contains(out.String(), "hostname") {
		t.Errorf("bad hostname names no field: %s", out.String())
	}
	out.Reset()
	if code := daemonConfigureTarget(map[string]any{
		"hostname": "niri-box", "locale": "de_DE.UTF-8",
		"keymap": "de", "timeZone": "Europe/Berlin"}, &out); code != 0 {
		t.Errorf("configure-target: code %d: %s", code, out.String())
	}
	out.Reset()
	if code := daemonConfigureTarget(map[string]any{"hostname": "bad host!"}, &out); code != 1 {
		t.Errorf("bad configure-target: code %d, want 1: %s", code, out.String())
	}
}
