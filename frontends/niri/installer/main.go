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
	"os/signal"
	"strings"
	"syscall"
)

// DiskInfo represents a block device from lsblk
type DiskInfo struct {
	Name      string `json:"name"`
	Size      string `json:"size"`
	Type      string `json:"type"`
	Transport string `json:"tran,omitempty"`
	// The disk picker (ui/installer.qml) leads with the model when there is
	// one. It read modelData.model all along, but MODEL was never asked of
	// lsblk, so every disk showed as a bare /dev name.
	Model string `json:"model,omitempty"`
}

// lsblkColumns are the columns discover-disks asks lsblk for. Every field
// of DiskInfo has to be listed here or it is silently always empty.
const lsblkColumns = "NAME,SIZE,TYPE,TRAN,MODEL"

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
		fmt.Fprintln(os.Stderr, "  reboot             Restart the host (the done page's action)")
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
	case "reboot":
		// The done page's Restart. On the host through flatpak-spawn when
		// sandboxed, like every other frontend's reboot path.
		if out, err := runHost("systemctl", "reboot"); err != nil {
			fmt.Fprintf(os.Stderr, "reboot: %v\n%s", err, out)
			os.Exit(1)
		}
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
			// Older util-linux pads MODEL with trailing spaces.
			d.Model = strings.TrimSpace(d.Model)
			disks = append(disks, d)
		}
	}
	return disks, nil
}

func discoverDisks() {
	cmd := exec.Command("lsblk", "-J", "-o", lsblkColumns)
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
		// Product identity per shared/branding/README.md: branding.json,
		// then os-release, then neutral. The QML takes its product name,
		// hostname seed, distroID and default image from here; nothing in
		// the frontend names a product.
		"branding": resolveBranding(),
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(result); err != nil {
		fmt.Fprintf(os.Stderr, "encode output: %v\n", err)
		os.Exit(1)
	}
}

// hasTPM reports whether the machine exposes a TPM 2.0 device, which is what
// the tpm2-luks encryption modes require.
//
// It used to stat /sys/class/tpm/tpm0, which the kernel also creates for a
// TPM 1.2 device. A 1.2 machine was therefore offered tpm2-luks, and the
// install failed at enrolment, after fisherman had partitioned the disk.
// shared/tpm/README.md is the contract; probeTPM2 implements it.
func hasTPM() bool {
	return fakeTPMRequested() || probeTPM2("/")
}

// wrapperCommand builds the fisherman wrapper's command in a process group
// of its own. The shared cancel contract is "kill your wrapper's process
// group", which must never be this backend's (or Quickshell's) group.
func wrapperCommand(argv []string) *exec.Cmd {
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	return cmd
}

// forwardSignals relays every signal this backend receives to the wrapper's
// process group (pgid == the wrapper's pid). Before the wrapper had a group
// of its own, a signal to this backend's group (Ctrl-C in a terminal, or a
// session teardown) reached the wrapper too; this keeps that working. The
// UI has no cancel button, so nothing else signals the group yet.
func forwardSignals(pgid int, sigs <-chan os.Signal) {
	for sig := range sigs {
		if s, ok := sig.(syscall.Signal); ok {
			_ = syscall.Kill(-pgid, s)
		}
	}
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
		recipe.DistroID = resolveBranding().ID
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

	// flatpak-spawn --host bash -c 'pkexec /usr/local/bin/fisherman "$1"' in
	// Flatpak, sudo /usr/local/bin/fisherman otherwise.
	argv := append(fishermanCommand(), recipePath)
	cmd := wrapperCommand(argv)

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

	runErr := cmd.Start()
	if runErr == nil {
		sigs := make(chan os.Signal, 1)
		signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
		go forwardSignals(cmd.Process.Pid, sigs)
		runErr = cmd.Wait()
		signal.Stop(sigs)
	}
	if logFile != nil {
		fmt.Fprintf(logFile, "=== install exited: %v ===\n", runErr)
	}
	if runErr != nil {
		fmt.Fprintf(os.Stderr, "fisherman failed: %v\n", runErr)
		os.Exit(1)
	}
}
