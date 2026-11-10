package main

// Live-session preflight.
//
// The pinned fisherman's recipe has no language, keyboard or time zone keys
// yet, so this backend offers the part that works without them: it reads and
// applies the LIVE session's keyboard layout, locale and time zone
// (localectl and timedatectl on the host), and it checks that the registry
// of the selected image answers.
//
// `session-get` reports the current values and what can be chosen.
// `session-set` applies one JSON object from stdin ({keyboard, locale,
// timezone}); the QML sends only the fields the user changed. The rules
// (#291):
//
//   - Off live media nothing is applied: the host is somebody's installed
//     system, and the wizard has no business with its keymap.
//   - A value that fails is reported on stderr and by exit 1, the rest still
//     apply, and the wizard treats the failure as a warning.
//
// `netcheck [image]` is the connectivity check, and `network-settings`
// opens the desktop's own network tool on the host (#301).

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"
)

// sessionTimeout bounds one host query. Listing timezones shells out, so this
// bounds a hung flatpak-spawn, not computation.
const sessionTimeout = 10 * time.Second

// netcheckFallbacks are the shared targets every frontend tries: the
// registry most images come from, then a public DNS server as a plain "is
// there a network". GNOME's conn_check, COSMIC and XFCE use the same two.
var netcheckFallbacks = []string{"ghcr.io:443", "8.8.8.8:53"}

// netcheckTimeout bounds one handshake.
const netcheckTimeout = 5 * time.Second

// SessionState is what the QML Session step renders and edits.
type SessionState struct {
	Keyboard  SessionChoice `json:"keyboard"`
	Locale    SessionChoice `json:"locale"`
	Timezone  SessionChoice `json:"timezone"`
	Connected bool          `json:"connected"`
}

// SessionChoice is one setting: what the session uses now, and what it may
// be changed to. Available is empty when the listing tool is missing.
type SessionChoice struct {
	Current   string   `json:"current"`
	Available []string `json:"available"`
}

func emptyChoice() SessionChoice {
	return SessionChoice{Available: []string{}}
}

// runHostQuery runs argv on the host with a timeout and returns stdout. A
// failure yields "" rather than an error: every session fact is optional,
// and the QML renders what it got.
func runHostQuery(timeout time.Duration, argv ...string) string {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	var out bytes.Buffer
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		return ""
	}
	return out.String()
}

// nonEmptyLines splits command output into its non-blank lines.
func nonEmptyLines(out string) []string {
	lines := []string{}
	for _, line := range strings.Split(out, "\n") {
		if trimmed := strings.TrimSpace(line); trimmed != "" {
			lines = append(lines, trimmed)
		}
	}
	return lines
}

// parseLocalectlStatus reads `localectl status`: the System Locale's LANG
// value, and the X11 layout (falling back to the console keymap).
func parseLocalectlStatus(out string) (locale, keyboard string) {
	for _, line := range strings.Split(out, "\n") {
		name, value, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		switch strings.TrimSpace(name) {
		case "System Locale":
			for _, field := range strings.Fields(value) {
				if lang, found := strings.CutPrefix(strings.TrimSpace(field), "LANG="); found {
					locale = lang
				}
			}
		case "X11 Layout":
			keyboard = strings.TrimSpace(value)
		case "VC Keymap":
			if keyboard == "" {
				keyboard = strings.TrimSpace(value)
			}
		}
	}
	return locale, keyboard
}

// parseTimedatectlTimezone reads `timedatectl show -p Timezone --value`.
func parseTimedatectlTimezone(out string) string {
	return strings.TrimSpace(out)
}

// registryAddress is the host:port of the registry an image reference is
// pulled from, or "" when the reference names none. 443 unless the reference
// has a port. A reference with no registry is Docker Hub's.
func registryAddress(image string) string {
	ref := strings.TrimSpace(image)
	for _, transport := range []string{"docker://", "ostree-unverified-registry:", "ostree-remote-registry:",
		"ostree-image-signed:docker://", "registry:"} {
		ref = strings.TrimPrefix(ref, transport)
	}
	if ref == "" || strings.Contains(ref, "://") || strings.HasPrefix(ref, "/") ||
		strings.HasPrefix(ref, "containers-storage:") || strings.HasPrefix(ref, "oci:") ||
		strings.HasPrefix(ref, "oci-archive:") || strings.HasPrefix(ref, "dir:") {
		return ""
	}
	first, _, hasPath := strings.Cut(ref, "/")
	if !hasPath || !(strings.ContainsAny(first, ".:") || first == "localhost") {
		return "registry-1.docker.io:443"
	}
	if _, _, err := net.SplitHostPort(first); err == nil {
		return first
	}
	return first + ":443"
}

// netcheckTargets is what to dial for an image: its own registry first (the
// one host the download needs), then the shared targets.
func netcheckTargets(image string) []string {
	targets := []string{}
	if own := registryAddress(image); own != "" {
		targets = append(targets, own)
	}
	for _, fallback := range netcheckFallbacks {
		if !contains(targets, fallback) {
			targets = append(targets, fallback)
		}
	}
	return targets
}

// dialer opens one TCP connection; tests replace it.
type dialer func(address string, timeout time.Duration) error

func tcpDial(address string, timeout time.Duration) error {
	conn, err := net.DialTimeout("tcp", address, timeout)
	if err != nil {
		return err
	}
	return conn.Close()
}

// checkConnectivity dials the targets in order and reports the first that
// answers ("" and false when none does). A TCP handshake downloads nothing.
func checkConnectivity(image string, dial dialer) (connected bool, target string) {
	for _, address := range netcheckTargets(image) {
		if dial(address, netcheckTimeout) == nil {
			return true, address
		}
	}
	return false, ""
}

// netcheckMain is the `netcheck [image]` subcommand: always exit 0, the
// answer is the JSON.
func netcheckMain(image string) {
	connected, target := checkConnectivity(image, tcpDial)
	answer := map[string]any{
		"connected": connected,
		"target":    target,
		"tried":     netcheckTargets(image),
	}
	if err := json.NewEncoder(os.Stdout).Encode(answer); err != nil {
		fmt.Fprintf(os.Stderr, "encode output: %v\n", err)
		os.Exit(1)
	}
}

// networkTools are the desktops' own network settings, in the order tried.
// The first that is installed on the host is started; which one that is
// depends on the image, and this frontend ships none.
var networkTools = [][]string{
	{"nm-connection-editor"},
	{"cosmic-settings", "network"},
	{"gnome-control-center", "wifi"},
	{"systemsettings", "kcm_networkmanagement"},
	{"iwgtk"},
	{"connman-gtk"},
}

// openNetworkSettings starts the first network tool the host has, detached,
// and returns its name. Best effort: an error says none was found.
func openNetworkSettings(host []string) (string, error) {
	for _, tool := range networkTools {
		lookup := append(append([]string{}, host...), "sh", "-c", `command -v "$1"`, "sh", tool[0])
		if runHostQuery(sessionTimeout, lookup...) == "" {
			continue
		}
		argv := append(append([]string{}, host...), tool...)
		cmd := exec.Command(argv[0], argv[1:]...)
		// A group of its own: the tool outlives this short-lived backend.
		cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
		if err := cmd.Start(); err != nil {
			continue
		}
		go func() { _ = cmd.Wait() }()
		return tool[0], nil
	}
	return "", errors.New("no network settings tool was found on this system")
}

func networkSettingsMain() {
	tool, err := openNetworkSettings(hostCommand())
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}
	fmt.Println(tool)
}

// sessionGet gathers the live session's state. The list commands come from
// the host tools every installer already shells out to; each is optional.
func sessionGet() SessionState {
	state := SessionState{
		Keyboard: emptyChoice(), Locale: emptyChoice(), Timezone: emptyChoice(),
	}
	host := hostCommand()
	run := func(args ...string) string {
		return runHostQuery(sessionTimeout, append(append([]string{}, host...), args...)...)
	}
	locale, keyboard := parseLocalectlStatus(run("localectl", "status"))
	state.Locale.Current = locale
	state.Locale.Available = nonEmptyLines(run("localectl", "list-locales"))
	state.Keyboard.Current = keyboard
	state.Keyboard.Available = nonEmptyLines(run("localectl", "list-keymaps"))
	state.Timezone.Current = parseTimedatectlTimezone(run("timedatectl", "show", "-p", "Timezone", "--value"))
	state.Timezone.Available = nonEmptyLines(run("timedatectl", "list-timezones"))
	state.Connected, _ = checkConnectivity("", tcpDial)
	return state
}

// sessionApply carries one `session-set` request: every field is optional,
// and only the fields present (not empty) are applied.
type sessionApply struct {
	Keyboard string `json:"keyboard"`
	Locale   string `json:"locale"`
	Timezone string `json:"timezone"`
}

func (want sessionApply) empty() bool {
	return want.Keyboard == "" && want.Locale == "" && want.Timezone == ""
}

// hostRunner runs one command on the host.
type hostRunner func(args ...string) error

// applySession writes the requested settings to the live session through
// the host tools. setxkbmap covers Xwayland where it exists; localectl
// owns the console and the requested default. A field that fails is
// returned with its reason and the rest still apply.
func applySession(want sessionApply, run hostRunner, hasSetxkbmap func() bool) map[string]string {
	failures := map[string]string{}
	if want.Keyboard != "" {
		if err := run("localectl", "set-keymap", want.Keyboard); err != nil {
			failures["keyboard"] = err.Error()
		} else if hasSetxkbmap() {
			// Best-effort: no X11 session means nothing to set.
			_ = run("setxkbmap", want.Keyboard)
		}
	}
	if want.Locale != "" {
		if err := run("localectl", "set-locale", "LANG="+want.Locale); err != nil {
			failures["locale"] = err.Error()
		}
	}
	if want.Timezone != "" {
		if err := run("timedatectl", "set-timezone", want.Timezone); err != nil {
			failures["timezone"] = err.Error()
		}
	}
	return failures
}

// errNotLive is why `session-set` changed nothing.
var errNotLive = errors.New("this is not live media: the settings of the running system were not changed")

// applySessionOn is the whole `session-set` rule: nothing to do is success,
// off live media nothing is applied, and on live media each field is tried.
func applySessionOn(live bool, want sessionApply, run hostRunner, hasSetxkbmap func() bool) (map[string]string, error) {
	if want.empty() {
		return nil, nil
	}
	if !live {
		return nil, errNotLive
	}
	return applySession(want, run, hasSetxkbmap), nil
}

func sessionGetMain() {
	state := sessionGet()
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(state); err != nil {
		fmt.Fprintf(os.Stderr, "encode output: %v\n", err)
		os.Exit(1)
	}
}

func sessionSetMain() {
	data, err := io.ReadAll(io.LimitReader(os.Stdin, 1<<16))
	if err != nil {
		fmt.Fprintf(os.Stderr, "read settings: %v\n", err)
		os.Exit(1)
	}
	var want sessionApply
	if err := json.Unmarshal(data, &want); err != nil {
		fmt.Fprintf(os.Stderr, "settings are not valid JSON: %v\n", err)
		os.Exit(1)
	}
	if want.empty() {
		return
	}
	host := hostCommand()
	run := func(args ...string) error {
		argv := append(append([]string{}, host...), args...)
		ctx, cancel := context.WithTimeout(context.Background(), sessionTimeout)
		defer cancel()
		return exec.CommandContext(ctx, argv[0], argv[1:]...).Run()
	}
	hasSetxkbmap := func() bool {
		return runHostQuery(sessionTimeout, append(append([]string{}, host...), "which", "setxkbmap")...) != ""
	}
	// Live media is fisherman's answer. A probe that fails is "not live".
	facts, _ := runProbe()
	failures, err := applySessionOn(facts.IsLive, want, run, hasSetxkbmap)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}
	if len(failures) > 0 {
		for _, field := range []string{"keyboard", "locale", "timezone"} {
			if reason, ok := failures[field]; ok {
				fmt.Fprintf(os.Stderr, "%s: %s\n", field, reason)
			}
		}
		os.Exit(1)
	}
}
