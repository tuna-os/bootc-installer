// Persistent install log.
//
// installProc's stdout/stderr in the QML frontend only ever fill an
// in-memory `installLog` property, shown on the Done page. Nothing lands on
// disk: close the window before reading it, or crash before reaching the
// Done page, and fisherman's full output — including which step failed —
// is gone. Support has nothing to ask for. The recovery key is the one thing
// the file does not keep (redact.go).
//
// This mirrors the fix already applied to the KDE, COSMIC, and Asahi
// frontends, which wrap fisherman (or its Python-backend equivalent) the
// same way and had the same gap.

package main

import (
	"fmt"
	"os"
	"path/filepath"
)

// installLogDir returns $XDG_STATE_HOME/tuna-installer, defaulting to
// ~/.local/state/tuna-installer per the XDG Base Directory spec — state that
// should survive the session, unlike $XDG_RUNTIME_DIR (tmpfs, used elsewhere
// in this package for the passphrase-bearing recipe, which must NOT survive).
func installLogDir() string {
	if base := os.Getenv("XDG_STATE_HOME"); base != "" {
		return filepath.Join(base, "tuna-installer")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".local", "state", "tuna-installer")
}

// installLogDisplayPath is the file openInstallLog appends to, for `detect`
// ("logPath") and `log-path`: the QML names it next to its Copy button, the
// way dialog_output.py shows the same file. "" when no home is known — a
// log path the UI cannot name is a missing affordance, not a failure.
func installLogDisplayPath() string {
	dir := installLogDir()
	if dir == "" {
		return ""
	}
	return filepath.Join(dir, "install.log")
}

// openInstallLog opens the persistent install log for appending, creating
// its directory if needed. Appending (not truncating) keeps an earlier
// failed attempt's output on disk instead of overwriting it when the user
// retries.
func openInstallLog() (*os.File, error) {
	dir := installLogDir()
	if dir == "" {
		return nil, fmt.Errorf("could not determine install log directory: no home")
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	// 0600: the log records a privileged install. runInstall writes it
	// through redactedLog, so the LUKS recovery key is not in it (#337).
	return os.OpenFile(filepath.Join(dir, "install.log"), os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0o600)
}
