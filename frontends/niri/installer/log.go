// Persistent install log.
//
// installProc's stdout/stderr in the QML frontend only ever fill an
// in-memory `installLog` property, shown on the Done page. Nothing lands on
// disk: close the window before reading it, or crash before reaching the
// Done page, and fisherman's full output — including which step failed and
// any recovery_key line — is gone. Support has nothing to ask for.
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
	// 0600: fisherman's output can include install-time details the LUKS
	// recovery_key line is meant to be read once and stored elsewhere for.
	return os.OpenFile(filepath.Join(dir, "install.log"), os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0o600)
}
