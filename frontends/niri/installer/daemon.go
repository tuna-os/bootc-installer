package main

// The fishermand backend: the same subcommands over Varlink instead of the
// `fisherman` recipe CLI (tuna-os/fisherman#512, tuna-os/bootc-installer#445).
//
// The QML keeps calling this backend's subcommands (`discover-disks`,
// `detect`, `validate`, `install`, `cancel`) with the same shapes, so the
// UI parses the same answers either way. Which path runs is backendMode:
// `TUNA_INSTALLER_BACKEND=daemon` forces the daemon, `=legacy` forces the
// recipe CLI, and the default `auto` uses the daemon when its socket exists
// and the CLI otherwise. The legacy path stays until the daemon ships.
//
// Secrets (passphrases, passwords, recovery keys) travel in call parameters
// and never reach a log. Error.Error returns the error name only.

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/skip2/go-qrcode"
	"tuna-installer-niri/varlink"
)

// defaultDaemonSocket is fishermand's io.tunaos.Fisherman socket
// (fisherman/docs/FISHERMAND.md). Every socket serves every interface.
const defaultDaemonSocket = "/run/fisherman/io.tunaos.Fisherman"

// daemonEnvBackend selects the path: "daemon", "legacy", or unset ("auto").
const daemonEnvBackend = "TUNA_INSTALLER_BACKEND"

// daemonEnvSocket overrides the socket path (tests, live media layout).
const daemonEnvSocket = "TUNA_FISHERMAN_SOCKET"

const daemonDialTimeout = 10 * time.Second

func daemonSocketPath() string {
	if p := os.Getenv(daemonEnvSocket); p != "" {
		return p
	}
	return defaultDaemonSocket
}

// backendMode reports "daemon" or "legacy".
func backendMode() string {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(daemonEnvBackend))) {
	case "daemon":
		return "daemon"
	case "legacy":
		return "legacy"
	default:
		if st, err := os.Stat(daemonSocketPath()); err == nil && !st.IsDir() {
			return "daemon"
		}
		return "legacy"
	}
}

func useDaemon() bool { return backendMode() == "daemon" }

func daemonDial() (*varlink.Conn, error) {
	return varlink.Dial(daemonSocketPath(), daemonDialTimeout)
}

// -- io.tunaos.Fisherman types (fisherman/internal/varlinkapi/idl/) --

type daemonGate struct {
	ID       string  `json:"id"`
	OK       bool    `json:"ok"`
	Severity string  `json:"severity"`
	Required *string `json:"required"`
	Actual   *string `json:"actual"`
	Message  string  `json:"message"`
	Action   *string `json:"action"`
}

type daemonPartition struct {
	Path      string  `json:"path"`
	Fstype    *string `json:"fstype"`
	Label     *string `json:"label"`
	SizeBytes int64   `json:"sizeBytes"`
}

type daemonExistingData struct {
	HasPartitionTable bool              `json:"hasPartitionTable"`
	PartitionTable    *string           `json:"partitionTableType"`
	Partitions        []daemonPartition `json:"partitions"`
	OperatingSystems  []string          `json:"operatingSystems"`
	HasLuks           bool              `json:"hasLuks"`
}

type daemonDisk struct {
	Path             string             `json:"path"`
	SizeBytes        int64              `json:"sizeBytes"`
	SizeLabel        string             `json:"sizeLabel"`
	Model            string             `json:"model"`
	Vendor           string             `json:"vendor"`
	Transport        string             `json:"transport"`
	Removable        bool               `json:"removable"`
	Eligible         bool               `json:"eligible"`
	ExcludedReason   *string            `json:"excludedReason"`
	FreeBytes        int64              `json:"freeBytes"`
	MinimalSizeBytes int64              `json:"minimalSizeBytes"`
	IntelRst         bool               `json:"intelRst"`
	ExistingData     daemonExistingData `json:"existingData"`
}

type daemonTpm struct {
	Present bool   `json:"present"`
	Version string `json:"version"`
	Usable  bool   `json:"usable"`
}

type daemonIntelRst struct {
	Detected      bool     `json:"detected"`
	Mode          *string  `json:"mode"`
	AffectedDisks []string `json:"affectedDisks"`
}

type daemonLive struct {
	IsLive    bool    `json:"isLive"`
	LiveImage *string `json:"liveImage"`
}

// daemonHandoffInfo is Probe's handoff hint: which mode the daemon will
// take, and why. Absent or unknown means reboot.
type daemonHandoffInfo struct {
	Mode   string  `json:"mode"`
	Reason *string `json:"reason"`
}
type daemonProblem struct {
	Field   string `json:"field"`
	Code    string `json:"code"`
	Message string `json:"message"`
}

type daemonUser struct {
	Username string  `json:"username"`
	FullName *string `json:"fullName,omitempty"`
	Password *string `json:"password,omitempty"`
	Admin    *bool   `json:"admin,omitempty"`
}

type daemonEncryption struct {
	Type       string  `json:"type"`
	Passphrase *string `json:"passphrase,omitempty"`
}

// daemonConfig is io.tunaos.Fisherman Config: disk, installMode, encryption,
// user, hostname. Fields stay out when absent; Validate with partial=true
// checks only the fields present.
type daemonConfig struct {
	Disk        *string           `json:"disk,omitempty"`
	InstallMode *string           `json:"installMode,omitempty"`
	Encryption  *daemonEncryption `json:"encryption,omitempty"`
	User        *daemonUser       `json:"user,omitempty"`
	Hostname    *string           `json:"hostname,omitempty"`
}

type daemonInstallEvent struct {
	Event      string  `json:"event"`
	StepID     *string `json:"stepId"`
	StepIndex  *int    `json:"stepIndex"`
	TotalSteps *int    `json:"totalSteps"`
	OverallPct int     `json:"overallPct"`
	Message    *string `json:"message"`
	Reason     *string `json:"reason"`
	NextAction *string `json:"nextAction"`
}

// recipeEncryptionType maps the recipe's encryption type (encryption-choices.json)
// to the daemon's (underscores, not hyphens).
func recipeEncryptionType(t string) (string, error) {
	switch t {
	case "none":
		return "none", nil
	case "luks-passphrase":
		return "luks_passphrase", nil
	case "tpm2-luks":
		return "tpm2_luks", nil
	case "tpm2-luks-passphrase":
		return "tpm2_luks_passphrase", nil
	default:
		return "", fmt.Errorf("unknown encryption type %q", t)
	}
}

// recipeToConfig maps a full recipe to the daemon's Config. The recipe has
// no install mode (the shared schema is another session's), so the wipe
// page's choice travels beside it and lands here as mode: "erase" or
// "free_space". Filesystem, image and store keys have no Config
// counterpart: the daemon owns the disk path, not the OS payload.
func recipeToConfig(recipe Recipe, mode string) (daemonConfig, error) {
	if mode != "erase" && mode != "free_space" {
		return daemonConfig{}, fmt.Errorf("unknown install mode %q", mode)
	}
	encType, err := recipeEncryptionType(recipe.Encryption.Type)
	if err != nil {
		return daemonConfig{}, err
	}
	cfg := daemonConfig{}
	if recipe.Disk != "" {
		cfg.Disk = &recipe.Disk
	}
	cfg.InstallMode = &mode
	enc := daemonEncryption{Type: encType}
	if recipe.Encryption.Passphrase != "" {
		pp := recipe.Encryption.Passphrase
		enc.Passphrase = &pp
	}
	cfg.Encryption = &enc
	if recipe.User != nil && recipe.User.Username != "" {
		u := daemonUser{Username: recipe.User.Username}
		if recipe.User.Fullname != "" {
			fn := recipe.User.Fullname
			u.FullName = &fn
		}
		if recipe.User.Password != "" {
			pw := recipe.User.Password
			u.Password = &pw
		}
		admin := true
		u.Admin = &admin
		cfg.User = &u
	}
	if recipe.Hostname != "" {
		cfg.Hostname = &recipe.Hostname
	}
	return cfg, nil
}

// fragmentToConfig maps a partial recipe (the `validate` stdin: page fields
// plus image keys) to the daemon's Config. Only the keys the daemon checks
// cross over: hostname, user, encryption, disk. Filesystem and image rules
// stay with `fisherman validate`; the daemon cannot see them.
func fragmentToConfig(frag map[string]any) (daemonConfig, error) {
	var cfg daemonConfig
	if disk, _ := frag["disk"].(string); disk != "" {
		cfg.Disk = &disk
	}
	if hostname, _ := frag["hostname"].(string); hostname != "" {
		cfg.Hostname = &hostname
	}
	if enc, ok := frag["encryption"].(map[string]any); ok {
		t, _ := enc["type"].(string)
		if t == "" {
			t = "none"
		}
		encType, err := recipeEncryptionType(t)
		if err != nil {
			return daemonConfig{}, err
		}
		e := daemonEncryption{Type: encType}
		if pp, _ := enc["passphrase"].(string); pp != "" {
			e.Passphrase = &pp
		}
		cfg.Encryption = &e
	}
	if user, ok := frag["user"].(map[string]any); ok {
		username, _ := user["username"].(string)
		if username != "" {
			u := daemonUser{Username: username}
			if fn, _ := user["fullname"].(string); fn != "" {
				u.FullName = &fn
			}
			if pw, _ := user["password"].(string); pw != "" {
				u.Password = &pw
			}
			cfg.User = &u
		}
	}
	return cfg, nil
}

// transportLabel renders the daemon's lowercase transport the way the
// fisherman probe labels it ("NVMe", "USB", "SATA").
func transportLabel(t string) string {
	switch strings.ToLower(t) {
	case "nvme":
		return "NVMe"
	case "usb":
		return "USB"
	case "sata", "ata":
		return "SATA"
	case "":
		return ""
	default:
		return strings.ToUpper(t[:1]) + t[1:]
	}
}

// daemonProbeFacts runs Requirements and Probe and folds them into the same
// ProbeFacts the recipe path builds. Daemon gate ids are ram, cpu and
// firmware; the QML knows them as ram, cpu and uefi.
func daemonProbeFacts() (ProbeFacts, error) {
	conn, err := daemonDial()
	if err != nil {
		return ProbeFacts{}, fmt.Errorf("fishermand: %v", err)
	}
	defer conn.Close()
	var req struct {
		MeetsRequirements bool         `json:"meetsRequirements"`
		Gates             []daemonGate `json:"gates"`
	}
	if err := conn.Call("io.tunaos.Fisherman.Requirements", nil, &req); err != nil {
		return ProbeFacts{}, fmt.Errorf("fishermand Requirements: %v", err)
	}
	var probe struct {
		ProtocolVersion int                `json:"protocolVersion"`
		Disks           []daemonDisk       `json:"disks"`
		Tpm             daemonTpm          `json:"tpm"`
		IntelRst        daemonIntelRst     `json:"intelRst"`
		Live            daemonLive         `json:"live"`
		Handoff         *daemonHandoffInfo `json:"handoff"`
	}
	if err := conn.Call("io.tunaos.Fisherman.Probe", nil, &probe); err != nil {
		return ProbeFacts{}, fmt.Errorf("fishermand Probe: %v", err)
	}
	facts := ProbeFacts{Disks: []ProbeDisk{}, TPMUsable: probe.Tpm.Usable,
		Unmet: []string{}, OfflineImages: []string{},
		HandoffMode: "reboot"}
	if probe.Handoff != nil {
		switch probe.Handoff.Mode {
		case "migrate", "soft_reboot", "reboot":
			facts.HandoffMode = probe.Handoff.Mode
			if probe.Handoff.Reason != nil {
				facts.HandoffReason = *probe.Handoff.Reason
			}
		}
	}
	for _, g := range req.Gates {
		if g.OK {
			continue
		}
		switch g.ID {
		case "ram":
			facts.Unmet = append(facts.Unmet, "ram")
		case "cpu":
			facts.Unmet = append(facts.Unmet, "cpu")
		case "firmware":
			facts.Unmet = append(facts.Unmet, "uefi")
		}
	}
	facts.IsLive = probe.Live.IsLive
	if probe.Live.LiveImage != nil {
		facts.LiveImage = *probe.Live.LiveImage
	}
	facts.IntelRst = probe.IntelRst.Detected
	for _, d := range probe.Disks {
		if !d.Eligible {
			continue
		}
		title := d.Model
		if title == "" {
			title = d.Path
		}
		ed := d.ExistingData
		facts.Disks = append(facts.Disks, ProbeDisk{
			Path: d.Path, Title: title, Model: d.Model,
			SizeLabel: d.SizeLabel, TransportLabel: transportLabel(d.Transport),
			Removable: d.Removable,
			HasData: ed.HasPartitionTable || len(ed.Partitions) > 0 ||
				len(ed.OperatingSystems) > 0 || ed.HasLuks,
			FreeBytes: d.FreeBytes, MinimalBytes: d.MinimalSizeBytes,
			IntelRst: d.IntelRst,
		})
	}
	return facts, nil
}

// daemonValidate checks a partial recipe through Validate with partial=true
// and prints fisherman's answer shape ({valid, errors}) for the QML.
func daemonValidate(stdin map[string]any, stdout io.Writer) (int, error) {
	cfg, err := fragmentToConfig(stdin)
	if err != nil {
		return 2, err
	}
	partial := true
	conn, err := daemonDial()
	if err != nil {
		return 2, fmt.Errorf("fishermand: %v", err)
	}
	defer conn.Close()
	var answer struct {
		Valid  bool            `json:"valid"`
		Errors []daemonProblem `json:"errors"`
	}
	if err := conn.Call("io.tunaos.Fisherman.Validate",
		map[string]any{"config": cfg, "partial": partial}, &answer); err != nil {
		return 2, fmt.Errorf("fishermand Validate: %v", err)
	}
	out, _ := json.Marshal(answer)
	fmt.Fprintln(stdout, string(out))
	if !answer.Valid {
		return 1, nil
	}
	return 0, nil
}

// daemonStepName is the English fallback label for a daemon step id. The
// QML prefers the branding copy key step_<id>; this shows when the copy has
// no line for the id (ui/progress.js stepLabel).
func daemonStepName(id string) string {
	switch id {
	case "validate_device":
		return "Checking the disk…"
	case "partition":
		return "Setting up the disk…"
	case "luks":
		return "Securing the disk…"
	case "tpm2_enroll":
		return "Setting up auto-unlock…"
	case "mount":
		return "Preparing the disk…"
	case "install_os":
		return "Installing the system…"
	case "configure":
		return "Configuring the system…"
	case "post_fixups":
		return "Applying fixes…"
	case "bootloader":
		return "Installing the bootloader…"
	case "finalize":
		return "Finishing up…"
	case "cleanup":
		return "Cleaning up…"
	default:
		return ""
	}
}

// emitInstallLine prints one fisherman-shaped JSON event for the QML log
// parser (installer.qml appendLog, ui/progress.js). The daemon streams its
// own events; this backend translates so the UI parses one protocol.
func emitInstallLine(w io.Writer, ev daemonInstallEvent) {
	line := func(v any) {
		b, _ := json.Marshal(v)
		fmt.Fprintln(w, string(b))
	}
	msg := ""
	if ev.Message != nil {
		msg = *ev.Message
	}
	stepID := ""
	if ev.StepID != nil {
		stepID = *ev.StepID
	}
	switch ev.Event {
	case "step_started":
		step, total := 0, 0
		if ev.StepIndex != nil {
			step = *ev.StepIndex + 1
		}
		if ev.TotalSteps != nil {
			total = *ev.TotalSteps
		}
		line(map[string]any{"type": "step", "step": step,
			"total_steps": total, "step_id": stepID,
			"step_name": daemonStepName(stepID), "overall_pct": ev.OverallPct})
	case "progress":
		m := map[string]any{"type": "substep", "overall_pct": ev.OverallPct}
		if msg != "" {
			m["message"] = msg
		}
		if stepID != "" {
			m["step_id"] = stepID
		}
		line(m)
	case "warning":
		if msg != "" {
			line(map[string]any{"type": "info", "message": msg})
		}
	case "step_finished":
		// No fisherman counterpart; the next step_started moves the bar.
	case "failed":
		e := map[string]any{"type": "error", "message": msg}
		if ev.Reason != nil && *ev.Reason != "" {
			e["code"] = *ev.Reason
		}
		if stepID != "" {
			e["step_id"] = stepID
		}
		line(e)
	case "complete":
		if msg == "" {
			msg = "Installation complete"
		}
		line(map[string]any{"type": "complete", "message": msg})
	}
}

// daemonInstallResult is how the translated stream ended.
type daemonInstallResult int

const (
	installComplete daemonInstallResult = iota
	installFailed
	installCancelled
)

// translateInstallStream folds a daemon Install stream into fisherman-shaped
// lines. Pure: tests feed it scripted events.
func translateInstallStream(w io.Writer, events []daemonInstallEvent) daemonInstallResult {
	result := installFailed
	for _, ev := range events {
		emitInstallLine(w, ev)
		switch ev.Event {
		case "complete":
			result = installComplete
		case "cancelled":
			result = installCancelled
		}
	}
	return result
}

// parseInstallInput reads the `install` stdin: either a bare recipe (the
// legacy shape, and what the QML sends off the daemon path's wipe page —
// always erase then) or {"recipe", "installMode"} from the wipe page.
// The mode is the daemon's name: "erase" or "free_space".
func parseInstallInput(input string) (Recipe, string, error) {
	var envelope struct {
		Recipe      json.RawMessage `json:"recipe"`
		InstallMode string          `json:"installMode"`
	}
	if err := json.Unmarshal([]byte(input), &envelope); err == nil && len(envelope.Recipe) > 0 {
		mode := envelope.InstallMode
		if mode == "" {
			mode = "erase"
		}
		recipe, err := decodeRecipe(envelope.Recipe)
		if err != nil {
			return Recipe{}, "", err
		}
		return recipe, mode, nil
	}
	recipe, err := decodeRecipe([]byte(input))
	if err != nil {
		return Recipe{}, "", err
	}
	return recipe, "erase", nil
}

// runDaemonInstall maps the recipe to a Config, streams Install, and exits
// the way the recipe path does: 0 for done, 130 for cancelled (the code the
// QML reads as the cancel, ui/progress.js installOutcome), 1 for failed.
func runDaemonInstall(recipeJSON string) {
	recipe, mode, err := parseInstallInput(recipeJSON)
	if err != nil {
		fmt.Fprintf(os.Stderr, "invalid recipe: %v\n", err)
		os.Exit(1)
	}
	normalizeRecipe(&recipe, resolveBranding().ID, accountGroups())
	cfg, err := recipeToConfig(recipe, mode)
	if err != nil {
		fmt.Fprintf(os.Stderr, "invalid recipe: %v\n", err)
		os.Exit(1)
	}
	conn, err := daemonDial()
	if err != nil {
		fmt.Fprintf(os.Stderr, "fishermand: %v\n", err)
		os.Exit(1)
	}
	defer conn.Close()
	result := installFailed
	callErr := conn.CallMore("io.tunaos.Fisherman.Install",
		map[string]any{"config": cfg, "confirmed": true},
		func(raw json.RawMessage) bool {
			var ev daemonInstallEvent
			if err := varlink.Decode(raw, &ev); err != nil {
				fmt.Fprintf(os.Stderr, "fishermand: bad install event: %v\n", err)
				return false
			}
			emitInstallLine(os.Stdout, ev)
			switch ev.Event {
			case "complete":
				result = installComplete
			case "cancelled":
				result = installCancelled
			}
			return true
		})
	if callErr != nil {
		fmt.Fprintf(os.Stderr, "fishermand Install: %v\n", callErr)
		os.Exit(1)
	}
	switch result {
	case installComplete:
		os.Exit(0)
	case installCancelled:
		os.Exit(130)
	default:
		os.Exit(1)
	}
}

// daemonCancel stops a running install. Safe when idle.
func daemonCancel() int {
	conn, err := daemonDial()
	if err != nil {
		fmt.Fprintf(os.Stderr, "fishermand: %v\n", err)
		return 1
	}
	defer conn.Close()
	var answer struct {
		WasInstalling bool `json:"wasInstalling"`
	}
	if err := conn.Call("io.tunaos.Fisherman.Cancel", nil, &answer); err != nil {
		fmt.Fprintf(os.Stderr, "fishermand Cancel: %v\n", err)
		return 1
	}
	return 0
}

// daemonConfigureTarget stores account, locale, keymap, time zone and
// autologin choices for the installed system. Reads one JSON object on
// stdin, prints {configured, errors}.
func daemonConfigureTarget(stdin map[string]any, stdout io.Writer) int {
	params := map[string]any{}
	if user, ok := stdin["user"].(map[string]any); ok {
		username, _ := user["username"].(string)
		if username != "" {
			// Normalize the recipe's "fullname" to the daemon's "fullName".
			nu := map[string]any{"username": username}
			if fn, _ := user["fullname"].(string); fn != "" {
				nu["fullName"] = fn
			} else if fn, _ := user["fullName"].(string); fn != "" {
				nu["fullName"] = fn
			}
			if pw, _ := user["password"].(string); pw != "" {
				nu["password"] = pw
			}
			if admin, ok := user["admin"].(bool); ok {
				nu["admin"] = admin
			}
			params["user"] = nu
		}
	}
	// Privacy is a nested object with locationServices (default false);
	// the QML sends it only when the user touched the toggle.
	if privacy, ok := stdin["privacy"].(map[string]any); ok {
		if ls, ok := privacy["locationServices"].(bool); ok {
			params["privacy"] = map[string]any{"locationServices": ls}
		}
	}
	for _, k := range []string{"hostname", "locale", "keymap", "timeZone", "timezone", "autologin"} {
		if v, ok := stdin[k]; ok && v != nil {
			if k == "timezone" {
				params["timeZone"] = v
			} else {
				params[k] = v
			}
		}
	}
	conn, err := daemonDial()
	if err != nil {
		fmt.Fprintf(os.Stderr, "fishermand: %v\n", err)
		return 1
	}
	defer conn.Close()
	var answer struct {
		Configured bool            `json:"configured"`
		Errors     []daemonProblem `json:"errors"`
	}
	if err := conn.Call("io.tunaos.Fisherman.ConfigureTarget", params, &answer); err != nil {
		fmt.Fprintf(os.Stderr, "fishermand ConfigureTarget: %v\n", err)
		return 1
	}
	out, _ := json.Marshal(answer)
	fmt.Fprintln(stdout, string(out))
	if !answer.Configured {
		return 1
	}
	return 0
}

// daemonRecoveryKey makes a recovery key and enrols it for node, unlocking
// with the install's passphrase ("" when the install sealed to TPM only).
// Prints {"key", "qr": {"size", "cells"}}: the key and its QR matrix for
// the recovery screen's code dialog. Exit 1 means the recovery-key-failed
// state.
func daemonRecoveryKey(stdin map[string]any, stdout io.Writer) int {
	node, _ := stdin["node"].(string)
	unlock, _ := stdin["unlock_password"].(string)
	if node == "" {
		fmt.Fprintln(os.Stderr, "recovery-key: missing node")
		return 1
	}
	conn, err := daemonDial()
	if err != nil {
		fmt.Fprintf(os.Stderr, "fishermand: %v\n", err)
		return 1
	}
	defer conn.Close()
	var made struct {
		RecoveryKey string `json:"recoveryKey"`
	}
	if err := conn.Call("io.systemd.CryptEnroll.MakeRecoveryKey", nil, &made); err != nil {
		fmt.Fprintf(os.Stderr, "fishermand MakeRecoveryKey: %v\n", err)
		return 1
	}
	if made.RecoveryKey == "" {
		fmt.Fprintln(os.Stderr, "fishermand MakeRecoveryKey: empty key")
		return 1
	}
	var enrolled struct {
		Slot int `json:"slot"`
	}
	if err := conn.Call("io.systemd.CryptEnroll.Enroll", map[string]any{
		"node": node, "mechanism": "recovery",
		"recoveryKey": made.RecoveryKey, "unlockPassword": unlock,
	}, &enrolled); err != nil {
		fmt.Fprintf(os.Stderr, "fishermand Enroll: %v\n", err)
		return 1
	}
	out, _ := json.Marshal(map[string]any{"key": made.RecoveryKey, "qr": recoveryQR(made.RecoveryKey)})
	fmt.Fprintln(stdout, string(out))
	return 0
}

// recoveryQR encodes the key as a QR grid for the QML dialog: size N and
// N*N cells row by row, 1 for a dark module. A key the encoder refuses
// (never seen) yields no grid, and the dialog stays hidden.
func recoveryQR(key string) map[string]any {
	code, err := qrcode.New(key, qrcode.Medium)
	if err != nil {
		return nil
	}
	bitmap := code.Bitmap()
	size := len(bitmap)
	cells := make([]int, 0, size*size)
	for _, row := range bitmap {
		for _, dark := range row {
			if dark {
				cells = append(cells, 1)
			} else {
				cells = append(cells, 0)
			}
		}
	}
	return map[string]any{"size": size, "cells": cells}
}

// daemonHandoff hands the installed system over. Prints the daemon's answer
// ({mode, started, sessionKeepsRunning}); the QML picks the next action.
func daemonHandoff(mode string, stdout io.Writer) int {
	if mode == "" {
		mode = "reboot"
	}
	conn, err := daemonDial()
	if err != nil {
		fmt.Fprintf(os.Stderr, "fishermand: %v\n", err)
		return 1
	}
	defer conn.Close()
	var answer struct {
		Mode              string `json:"mode"`
		Started           bool   `json:"started"`
		SessionKeepsGoing bool   `json:"sessionKeepsRunning"`
	}
	if err := conn.Call("io.tunaos.Fisherman.Handoff",
		map[string]any{"mode": mode}, &answer); err != nil {
		fmt.Fprintf(os.Stderr, "fishermand Handoff: %v\n", err)
		return 1
	}
	out, _ := json.Marshal(answer)
	fmt.Fprintln(stdout, string(out))
	if !answer.Started {
		return 1
	}
	return 0
}

// readStdinObject reads one JSON object from stdin for the daemon's
// object-taking subcommands (configure-target, recovery-key).
func readStdinObject() (map[string]any, error) {
	data, err := readOneJSON(os.Stdin, 1<<20)
	if err != nil {
		return nil, err
	}
	var obj map[string]any
	if err := json.Unmarshal(data, &obj); err != nil {
		return nil, err
	}
	return obj, nil
}

func configureTargetMain() {
	obj, err := readStdinObject()
	if err != nil {
		fmt.Fprintf(os.Stderr, "configure-target: %v\n", err)
		os.Exit(1)
	}
	os.Exit(daemonConfigureTarget(obj, os.Stdout))
}

func recoveryKeyMain() {
	obj, err := readStdinObject()
	if err != nil {
		fmt.Fprintf(os.Stderr, "recovery-key: %v\n", err)
		os.Exit(1)
	}
	os.Exit(daemonRecoveryKey(obj, os.Stdout))
}

func handoffMain() {
	mode := ""
	if len(os.Args) > 2 {
		mode = os.Args[2]
	}
	os.Exit(daemonHandoff(mode, os.Stdout))
}
