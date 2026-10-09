// TunaOS Niri Installer — Go backend
//
// A plain argv/stdout CLI, not a service: the QML frontend runs it with
// Quickshell's Process for each operation (`discover-disks`, `detect`,
// `install <recipe>`, `readiness [page]`) and parses what comes back on
// stdout. This backend wraps fisherman; the disk list, TPM and requirements
// are fisherman's own (`fisherman probe --json`, probe.go).

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"syscall"
)

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
		fmt.Fprintln(os.Stderr, "  discover-disks     List the disks fisherman offers as JSON")
		fmt.Fprintln(os.Stderr, "  detect             Report live-ISO image, offline stores, TPM and requirements as JSON")
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

// discoverDisks prints the disks fisherman offers, in its order, rendered
// per shared/probe/README.md ([]ProbeDisk). On a probe failure it prints the
// reason on stderr and exits 1; the QML shows that reason.
func discoverDisks() {
	facts, err := runProbe()
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(facts.Disks); err != nil {
		fmt.Fprintf(os.Stderr, "encode output: %v\n", err)
		os.Exit(1)
	}
}

// detectEnvironment reports offline-install facts for the QML frontend.
func detectEnvironment() {
	stores := offlineStores()
	// TPM and requirements are fisherman's. A failed probe offers no TPM
	// choices and warns about nothing; discover-disks reports the failure.
	facts, err := runProbe()
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
	}
	result := map[string]any{
		"liveImage":     liveISOImage(),
		"offlineStores": stores,
		"offlineImages": offlineImages(stores),
		// fisherman's tpm.usable. The UI hides the TPM encryption options
		// when this is false, rather than offering a choice that would fail
		// later at install time.
		"hasTpm": err == nil && facts.TPMUsable,
		// fisherman's system.unmet ("ram", "cpu", "uefi"): the welcome page
		// warns about each one.
		"unmet": unmetOrEmpty(facts, err),
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

func unmetOrEmpty(facts ProbeFacts, err error) []string {
	if err != nil || facts.Unmet == nil {
		return []string{}
	}
	return facts.Unmet
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
