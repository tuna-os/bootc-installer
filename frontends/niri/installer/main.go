// TunaOS Niri Installer — Go backend
//
// A plain argv/stdout CLI, not a service: the QML frontend runs it with
// Quickshell's Process for each operation (`discover-disks`, `detect`,
// `install <recipe>`, `readiness [page]`) and parses what comes back on
// stdout. This backend wraps fisherman and provides disk discovery.

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
)

// DiskInfo represents a block device from lsblk
type DiskInfo struct {
	Name      string `json:"name"`
	Size      string `json:"size"`
	Type      string `json:"type"`
	Transport string `json:"tran,omitempty"`
}

// Recipe is the fisherman install recipe (see ../../INSTALLER-FRONTENDS.md §1).
type Recipe struct {
	Disk            string     `json:"disk"`
	Filesystem      string     `json:"filesystem"`
	BtrfsSubvolumes bool       `json:"btrfsSubvolumes"`
	Encryption      Encryption `json:"encryption"`
	// Image may be empty in live-ISO mode: bootc installs the running container.
	Image            string   `json:"image,omitempty"`
	TargetImgref     string   `json:"targetImgref,omitempty"`
	Bootloader       string   `json:"bootloader,omitempty"`
	ComposeFsBackend bool     `json:"composeFsBackend,omitempty"`
	Flatpaks         []string `json:"flatpaks,omitempty"`
	// AdditionalImageStores lists embedded OCI stores for offline installs.
	AdditionalImageStores []string `json:"additionalImageStores,omitempty"`
	DistroID              string   `json:"distroID"`
	SelinuxDisabled       bool     `json:"selinuxDisabled"`
	Hostname              string   `json:"hostname"`
}

type Encryption struct {
	// "none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"
	Type       string `json:"type"`
	Passphrase string `json:"passphrase,omitempty"`
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: tuna-installer-niri <command> [args...]")
		fmt.Fprintln(os.Stderr, "Commands:")
		fmt.Fprintln(os.Stderr, "  discover-disks     List available block devices as JSON")
		fmt.Fprintln(os.Stderr, "  detect             Report live-ISO image and offline stores as JSON")
		fmt.Fprintln(os.Stderr, "  install <recipe>   Run fisherman with the given recipe JSON")
		fmt.Fprintln(os.Stderr, "  readiness [page]   Record that the UI window presented a frame")
		os.Exit(1)
	}

	switch os.Args[1] {
	case "discover-disks":
		discoverDisks()
	case "detect":
		detectEnvironment()
	case "install":
		// The recipe may hold a LUKS passphrase; read it from stdin rather
		// than argv so it never shows up in /proc/PID/cmdline (world-readable
		// on Linux). The QML frontend writes it with Quickshell's
		// Process.write().
		recipeJSON, err := io.ReadAll(os.Stdin)
		if err != nil {
			fmt.Fprintf(os.Stderr, "read recipe: %v\n", err)
			os.Exit(1)
		}
		runInstall(string(recipeJSON))
	case "readiness":
		// Called by the QML layer from ApplicationWindow.onFrameSwapped. See
		// readiness.go for why the write lives on this side of the boundary.
		page := ""
		if len(os.Args) > 2 {
			page = os.Args[2]
		}
		readinessStamp(page)
	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", os.Args[1])
		os.Exit(1)
	}
}

func parseLSBLKOutput(output []byte) ([]DiskInfo, error) {
	var result struct {
		Blockdevices []json.RawMessage `json:"blockdevices"`
	}
	if err := json.Unmarshal(output, &result); err != nil {
		return nil, fmt.Errorf("parse lsblk output: %w", err)
	}

	var disks []DiskInfo
	for _, raw := range result.Blockdevices {
		var d DiskInfo
		if err := json.Unmarshal(raw, &d); err != nil {
			continue
		}
		if d.Type == "disk" {
			disks = append(disks, d)
		}
	}
	return disks, nil
}

func discoverDisks() {
	cmd := exec.Command("lsblk", "-J", "-o", "NAME,SIZE,TYPE,TRAN")
	output, err := cmd.Output()
	if err != nil {
		fmt.Fprintf(os.Stderr, "lsblk failed: %v\n", err)
		os.Exit(1)
	}

	disks, err := parseLSBLKOutput(output)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(disks); err != nil {
		fmt.Fprintf(os.Stderr, "encode output: %v\n", err)
		os.Exit(1)
	}
}

// detectEnvironment reports offline-install facts for the QML frontend.
func detectEnvironment() {
	stores := offlineStores()
	result := map[string]any{
		"liveImage":     liveISOImage(),
		"offlineStores": stores,
		"offlineImages": offlineImages(stores),
		// The UI hides the TPM encryption options when this is false, rather
		// than offering a choice that would fail later at install time. Same
		// probe the XFCE and KDE frontends use.
		"hasTpm": hasTPM(),
		// Per-variant product name from os-release (PRETTY_NAME), so the UI
		// reads "Skipjack Installer" on a Skipjack ISO. Empty when os-release
		// is unreadable — the QML falls back to "TunaOS".
		"productName": productName(),
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(result); err != nil {
		fmt.Fprintf(os.Stderr, "encode output: %v\n", err)
		os.Exit(1)
	}
}

// hasTPM reports whether the machine exposes a TPM device, which is what the
// tpm2-luks encryption modes require.
func hasTPM() bool {
	_, err := os.Stat("/sys/class/tpm/tpm0")
	return err == nil
}

func runInstall(recipeJSON string) {
	if len(recipeJSON) == 0 {
		fmt.Fprintln(os.Stderr, "invalid recipe: empty")
		os.Exit(1)
	}
	var recipe Recipe
	if err := json.Unmarshal([]byte(recipeJSON), &recipe); err != nil {
		fmt.Fprintf(os.Stderr, "invalid recipe: %v\n", err)
		os.Exit(1)
	}

	// Offline install support (spec §4): live-ISO mode allows an empty image;
	// embedded stores are always passed — fisherman ignores unhelpful ones.
	if recipe.Image == "" && liveISOImage() == "" {
		fmt.Fprintln(os.Stderr, "invalid recipe: image is required outside live-ISO mode")
		os.Exit(1)
	}
	if len(recipe.AdditionalImageStores) == 0 {
		recipe.AdditionalImageStores = offlineStores()
	}
	if recipe.DistroID == "" {
		recipe.DistroID = "tunaos"
	}

	data, err := json.MarshalIndent(recipe, "", "  ")
	if err != nil {
		fmt.Fprintf(os.Stderr, "encode recipe: %v\n", err)
		os.Exit(1)
	}
	// 0600 under XDG_RUNTIME_DIR — the recipe may hold a passphrase.
	recipePath, err := writeRecipe(data)
	if err != nil {
		fmt.Fprintf(os.Stderr, "write recipe: %v\n", err)
		os.Exit(1)
	}
	defer os.RemoveAll(recipeDir(recipePath))

	// pkexec /app/bin/fisherman in Flatpak, sudo /usr/local/bin/fisherman otherwise.
	argv := append(fishermanCommand(), recipePath)
	cmd := exec.Command(argv[0], argv[1:]...)

	// Tee fisherman's output to a persistent log in addition to the pipe
	// Quickshell reads (root.installLog in installer.qml) — that property is
	// in-memory only and gone the moment the window closes.
	logFile, logErr := openInstallLog()
	if logErr != nil {
		fmt.Fprintf(os.Stderr, "install log: %v\n", logErr)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
	} else {
		defer logFile.Close()
		fmt.Fprintf(logFile, "=== install started, recipe=%s ===\n", recipePath)
		cmd.Stdout = io.MultiWriter(os.Stdout, logFile)
		cmd.Stderr = io.MultiWriter(os.Stderr, logFile)
	}

	runErr := cmd.Run()
	if logFile != nil {
		fmt.Fprintf(logFile, "=== install exited: %v ===\n", runErr)
	}
	if runErr != nil {
		fmt.Fprintf(os.Stderr, "fisherman failed: %v\n", runErr)
		os.Exit(1)
	}
}
