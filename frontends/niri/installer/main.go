// TunaOS Niri Installer — Go backend
//
// A plain argv/stdout CLI, not a service: the QML frontend runs it with
// Quickshell's Process for each operation (`discover-disks`, `detect`,
// `install`, `validate`, `readiness [page]`) and parses what comes back on
// stdout. This backend wraps fisherman; the disk list, TPM, requirements,
// live media and offline images are fisherman's own (`fisherman probe
// --json`, probe.go), and so are the recipe rules (`fisherman validate
// --json`, validate.go).

package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"syscall"
)

// Recipe is the fisherman install recipe: every property of
// shared/recipe/fisherman-recipe.schema.json, and nothing else.
//
// The QML's recipe is decoded into this struct and encoded again for
// fisherman. A struct that listed only some keys dropped the others without a
// word (#297), so decodeRecipe refuses a key that is not here, and
// recipe_test.go fails when the schema has a property this struct lacks.
// A pointer is a key whose absence means something: no `flatpaks` lets
// fisherman apply its default, `[]` copies nothing.
type Recipe struct {
	Disk            string     `json:"disk"`
	Filesystem      string     `json:"filesystem"`
	BtrfsSubvolumes bool       `json:"btrfsSubvolumes"`
	Encryption      Encryption `json:"encryption"`
	// Image may be empty on live media: bootc installs the running system.
	Image            string    `json:"image,omitempty"`
	TargetImgref     string    `json:"targetImgref,omitempty"`
	Bootloader       string    `json:"bootloader,omitempty"`
	ComposeFsBackend bool      `json:"composeFsBackend,omitempty"`
	Flatpaks         *[]string `json:"flatpaks,omitempty"`
	// AdditionalImageStores lists offline OCI stores. Left out, fisherman
	// exposes the stores it finds on the host; this backend never fills it.
	AdditionalImageStores []string `json:"additionalImageStores,omitempty"`
	DistroID              string   `json:"distroID"`
	SelinuxDisabled       bool     `json:"selinuxDisabled"`
	Hostname              string   `json:"hostname"`
	UnifiedStorage        bool     `json:"unifiedStorage,omitempty"`
	GenericImage          bool     `json:"genericImage,omitempty"`
	ZfsPoolName           string   `json:"zfsPoolName,omitempty"`
	ImageType             string   `json:"imageType,omitempty"`
	FlatpakVarPath        string   `json:"flatpakVarPath,omitempty"`
	// User is the account fisherman creates. Left out (nil), fisherman
	// creates none; normalizeRecipe drops a block with no username, the
	// schema's "empty skips" rule, so it never reaches fisherman half-filled.
	User *User `json:"user,omitempty"`
	// The wizard writes none of these; they pass through as they came.
	CustomMounts    json.RawMessage `json:"customMounts,omitempty"`
	VarDisk         json.RawMessage `json:"varDisk,omitempty"`
	SlurpWallpapers bool            `json:"slurpWallpapers,omitempty"`
	Slurp           json.RawMessage `json:"slurp,omitempty"`
	TargetMount     string          `json:"targetMount,omitempty"`
	LuksMapperName  string          `json:"luksMapperName,omitempty"`
	BrewTap         string          `json:"brewTap,omitempty"`
}

// User is the recipe's `user` block (shared/recipe/fisherman-recipe.schema.json).
// The password travels with the recipe on stdin only, like the passphrase.
// Groups is nil when the QML names none: normalizeRecipe then writes the
// shared list (user.go). An empty list is the operator's "no group".
type User struct {
	Username string    `json:"username"`
	Fullname string    `json:"fullname"`
	Password string    `json:"password"`
	Groups   *[]string `json:"groups,omitempty"`
}

type Encryption struct {
	// "none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"
	Type       string `json:"type"`
	Passphrase string `json:"passphrase,omitempty"`
}

// decodeRecipe reads the QML's recipe. A key that Recipe does not list is an
// error, at any depth of the parts this backend types: sending it on without
// the key would install something the user did not choose.
func decodeRecipe(data []byte) (Recipe, error) {
	var recipe Recipe
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&recipe); err != nil {
		return Recipe{}, err
	}
	if dec.More() {
		return Recipe{}, errors.New("more than one JSON value")
	}
	return recipe, nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: tuna-installer-niri <command> [args...]")
		fmt.Fprintln(os.Stderr, "Commands:")
		fmt.Fprintln(os.Stderr, "  discover-disks     List the disks fisherman offers as JSON")
		fmt.Fprintln(os.Stderr, "  detect             Report live media, offline images, TPM, requirements and encryption choices as JSON")
		fmt.Fprintln(os.Stderr, "  catalog            List the images.json catalog leaves with inheritance resolved as JSON")
		fmt.Fprintln(os.Stderr, "  session-get        Report the live session's keyboard, locale, timezone and connectivity as JSON")
		fmt.Fprintln(os.Stderr, "  session-set        Apply keyboard/locale/timezone JSON read from stdin to the live session")
		fmt.Fprintln(os.Stderr, "  netcheck [image]   Report as JSON whether the registry of an image answers")
		fmt.Fprintln(os.Stderr, "  network-settings   Open the desktop's network settings on the host")
		fmt.Fprintln(os.Stderr, "  install            Run fisherman with the recipe JSON read from stdin")
		fmt.Fprintln(os.Stderr, "  cancel             Stop a running install (the progress page's Cancel, the window's close)")
		fmt.Fprintln(os.Stderr, "  log-path           Print the persistent install log file dialog_output.py shows")
		fmt.Fprintln(os.Stderr, "  validate           Check a partial recipe from stdin with fisherman validate --json --partial")
		fmt.Fprintln(os.Stderr, "  readiness [page]   Record that the UI window presented a frame")
		fmt.Fprintln(os.Stderr, "  reboot             Restart the host (the done page's action)")
		fmt.Fprintln(os.Stderr, "  poweroff           Power the host off (the requirements gate's action)")
		fmt.Fprintln(os.Stderr, "  firmware           Reboot into the firmware setup (the UEFI gate's remediation)")
		os.Exit(1)
	}

	switch os.Args[1] {
	case "discover-disks":
		discoverDisks()
	case "detect":
		detectEnvironment()
	case "catalog":
		catalogMain()
	case "session-get":
		sessionGetMain()
	case "session-set":
		sessionSetMain()
	case "netcheck":
		image := ""
		if len(os.Args) > 2 {
			image = os.Args[2]
		}
		netcheckMain(image)
	case "network-settings":
		networkSettingsMain()
	case "cancel":
		cancelMain()
	case "log-path":
		logPathMain()
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
	case "validate":
		// A page's fields as a partial recipe, on stdin for the same reason.
		validateMain()
	case "reboot":
		// The done page's Restart. On the host through flatpak-spawn when
		// sandboxed, like every other frontend's reboot path (power.go).
		rebootMain()
	case "poweroff":
		poweroffMain()
	case "firmware":
		firmwareMain()
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

// detectEnvironment reports the environment facts for the QML frontend.
func detectEnvironment() {
	// Every fact is fisherman's. A failed probe offers no TPM choices,
	// warns about nothing and is not live media; discover-disks reports the
	// failure.
	facts, err := runProbe()
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		facts = ProbeFacts{OfflineImages: []string{}}
	}
	result := map[string]any{
		// probe's live.is_live: only then may the recipe leave `image`
		// empty, which installs the running system.
		"isLive": facts.IsLive,
		// The booted image on live media, for display; "" otherwise.
		"liveImage": facts.LiveImage,
		// Image refs in the host's offline stores (offline.images).
		"offlineImages": facts.OfflineImages,
		// fisherman's tpm.usable. The UI hides the TPM encryption options
		// when this is false, rather than offering a choice that would fail
		// later at install time.
		"hasTpm": err == nil && facts.TPMUsable,
		// fisherman's system.unmet ("ram", "cpu", "uefi"): the welcome page
		// warns about each one.
		"unmet": unmetOrEmpty(facts, err),
		// The encryption types in display order, with needs_passphrase and
		// needs_tpm2: fisherman's data/encryption-choices.json, embedded.
		"encryptionChoices": encryptionChoices(),
		// Product identity per shared/branding/README.md: branding.json,
		// then os-release, then neutral. The QML takes its product name,
		// hostname seed, distroID and default image from here; nothing in
		// the frontend names a product.
		"branding": resolveBranding(),
		// The persistent install log dialog_output.py shows: the QML
		// names it next to its Copy button ("log-path" prints the same).
		"logPath": installLogDisplayPath(),
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
// progress page's Cancel reaches the group through `cancel` (power.go).
func forwardSignals(pgid int, sigs <-chan os.Signal) {
	for sig := range sigs {
		if s, ok := sig.(syscall.Signal); ok {
			_ = syscall.Kill(-pgid, s)
		}
	}
}

// normalizeRecipe fills what the UI leaves out before the recipe goes on to
// fisherman: the branding's distroID, and the account's groups (the shared
// list, or the operator's). A user block with no username is dropped rather
// than sent: fisherman would skip it anyway, and a password with no account
// has nowhere to go.
func normalizeRecipe(recipe *Recipe, distroID string, groups []string) {
	if recipe.DistroID == "" {
		recipe.DistroID = distroID
	}
	if recipe.User != nil {
		if recipe.User.Username == "" {
			recipe.User = nil
		} else if recipe.User.Groups == nil {
			list := append([]string{}, groups...)
			recipe.User.Groups = &list
		}
	}
}

// exitCodeOf is the status this backend ends with for the wrapper's: its
// own exit code, or 128 + the signal that killed it. fisherman exits 130
// when it is cancelled (shared/recipe/README.md), and the QML shows the
// cancelled page for that code, so the code must survive this process.
func exitCodeOf(err error) int {
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		return 1
	}
	if ws, ok := exitErr.Sys().(syscall.WaitStatus); ok && ws.Signaled() {
		return 128 + int(ws.Signal())
	}
	if code := exitErr.ExitCode(); code > 0 {
		return code
	}
	return 1
}

func runInstall(recipeJSON string) {
	if len(recipeJSON) == 0 {
		fmt.Fprintln(os.Stderr, "invalid recipe: empty")
		os.Exit(1)
	}
	recipe, err := decodeRecipe([]byte(recipeJSON))
	if err != nil {
		fmt.Fprintf(os.Stderr, "invalid recipe: %v\n", err)
		os.Exit(1)
	}

	// An empty image (install the running system) and the offline stores
	// are fisherman's to judge and find (tuna-os/fisherman#276): it rejects
	// an empty image off live media before touching a disk, and exposes the
	// host's stores when additionalImageStores is absent.
	normalizeRecipe(&recipe, resolveBranding().ID, accountGroups())

	data, err := json.Marshal(recipe)
	if err != nil {
		fmt.Fprintf(os.Stderr, "encode recipe: %v\n", err)
		os.Exit(1)
	}

	// The one resolver (offline.go): the staged and verified binary in a
	// Flatpak, /usr/local/bin/fisherman otherwise; pkexec, or `sudo -n` on
	// live media. Live media is the probe's answer; a probe that fails is
	// "not live", and pkexec then asks.
	fisherman, err := resolveFisherman()
	if err != nil {
		fmt.Fprintf(os.Stderr, "fisherman: %v\n", err)
		os.Exit(1)
	}
	facts, _ := runProbe()

	// The recipe goes on the wrapper's stdin, which closes at EOF: no file
	// holds it.
	cmd := wrapperCommand(fisherman.InstallArgv(facts.IsLive))
	cmd.Stdin = bytes.NewReader(data)

	// Tee fisherman's output to a persistent log in addition to the pipe
	// Quickshell reads (root.installLog in installer.qml) — that property is
	// in-memory only and gone the moment the window closes.
	logFile, logErr := openInstallLog()
	if logErr != nil {
		fmt.Fprintf(os.Stderr, "install log: %v\n", logErr)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
	} else {
		fmt.Fprintln(logFile, "=== install started, recipe on stdin ===")
		cmd.Stdout = io.MultiWriter(os.Stdout, logFile)
		cmd.Stderr = io.MultiWriter(os.Stderr, logFile)
	}

	runErr := cmd.Start()
	if runErr == nil {
		// The wrapper's pid, so `cancel` (the progress page's Cancel,
		// the window's close) can kill its process group. Removed when
		// the install ends either way.
		writePidfile(cmd.Process.Pid)
		sigs := make(chan os.Signal, 1)
		signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)
		go forwardSignals(cmd.Process.Pid, sigs)
		runErr = cmd.Wait()
		signal.Stop(sigs)
		clearPidfile()
	}
	if logFile != nil {
		fmt.Fprintf(logFile, "=== install exited: %v ===\n", runErr)
		logFile.Close()
	}
	if runErr != nil {
		fmt.Fprintf(os.Stderr, "fisherman failed: %v\n", runErr)
		os.Exit(exitCodeOf(runErr))
	}
}
