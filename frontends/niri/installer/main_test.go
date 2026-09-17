package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"strings"
	"testing"
)

// TestInstallReadsRecipeFromStdin guards the gh-22 fix: the recipe (which can
// carry a LUKS passphrase) must reach the backend over stdin, never over argv,
// because /proc/PID/cmdline is world-readable on Linux. runInstall must be
// invoked with the recipe that came from stdin.
func TestRunInstallRejectsEmptyRecipe(t *testing.T) {
	// runInstall is the backend's stdin entry point. An empty stdin must be a
	// hard error, not a silent pass-through (which would let a truncated
	// recipe reach fisherman).
	if os.Getenv("GO_TEST_RUN_INSTALL") == "1" {
		runInstall("")
		// If we get here the empty recipe was accepted — fail loudly via the
		// test process itself.
		os.Exit(0)
	}

	cmd := exec.Command(os.Args[0], "-test.run=TestRunInstallRejectsEmptyRecipe")
	cmd.Env = append(os.Environ(), "GO_TEST_RUN_INSTALL=1")
	out, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatalf("runInstall(\"\") accepted an empty recipe; stdout=%s", out)
	}
	if !strings.Contains(string(out), "invalid recipe: empty") {
		t.Fatalf("expected 'invalid recipe: empty' error, got: %s", out)
	}
}

func TestParseLSBLKOutput(t *testing.T) {
	input := []byte(`{
		"blockdevices": [
			{"name": "nvme0n1", "size": "500G", "type": "disk", "tran": "nvme"},
			{"name": "loop0", "size": "2G", "type": "loop"},
			{"name": "sda", "size": "1T", "type": "disk", "tran": "sata"}
		]
	}`)

	disks, err := parseLSBLKOutput(input)
	if err != nil {
		t.Fatalf("parseLSBLKOutput failed: %v", err)
	}
	if len(disks) != 2 {
		t.Fatalf("expected 2 disks, got %d", len(disks))
	}
	if disks[0].Name != "nvme0n1" || disks[0].Transport != "nvme" {
		t.Errorf("unexpected disk 0: %+v", disks[0])
	}
	if disks[1].Name != "sda" || disks[1].Transport != "sata" {
		t.Errorf("unexpected disk 1: %+v", disks[1])
	}
}

func TestRecipeUnmarshal(t *testing.T) {
	input := []byte(`{
		"disk": "/dev/sda",
		"filesystem": "btrfs",
		"btrfsSubvolumes": true,
		"encryption": {
			"type": "luks-passphrase",
			"passphrase": "secret-passphrase"
		},
		"image": "ghcr.io/tuna-os/skipjack:niri",
		"targetImgref": "ghcr.io/tuna-os/skipjack:stable",
		"bootloader": "systemd",
		"composeFsBackend": true,
		"flatpaks": ["org.mozilla.firefox"],
		"additionalImageStores": ["/run/media/store"],
		"distroID": "tunaos",
		"selinuxDisabled": true,
		"hostname": "niri-host"
	}`)

	var r Recipe
	if err := json.Unmarshal(input, &r); err != nil {
		t.Fatalf("json.Unmarshal(Recipe) failed: %v", err)
	}

	if r.Disk != "/dev/sda" || r.Filesystem != "btrfs" || !r.BtrfsSubvolumes {
		t.Errorf("unexpected storage fields: %+v", r)
	}
	if r.Encryption.Type != "luks-passphrase" || r.Encryption.Passphrase != "secret-passphrase" {
		t.Errorf("unexpected encryption: %+v", r.Encryption)
	}
	if r.Image != "ghcr.io/tuna-os/skipjack:niri" || r.TargetImgref != "ghcr.io/tuna-os/skipjack:stable" {
		t.Errorf("unexpected image fields: %+v", r)
	}
	if r.Bootloader != "systemd" || !r.ComposeFsBackend {
		t.Errorf("unexpected boot/composefs config: %+v", r)
	}
	if len(r.Flatpaks) != 1 || r.Flatpaks[0] != "org.mozilla.firefox" {
		t.Errorf("unexpected flatpaks: %+v", r.Flatpaks)
	}
	if len(r.AdditionalImageStores) != 1 || r.AdditionalImageStores[0] != "/run/media/store" {
		t.Errorf("unexpected additional image stores: %+v", r.AdditionalImageStores)
	}
	if r.Hostname != "niri-host" || r.DistroID != "tunaos" || !r.SelinuxDisabled {
		t.Errorf("unexpected system metadata: %+v", r)
	}
}
