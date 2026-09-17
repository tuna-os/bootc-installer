package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestInstallLogDirUsesXDGStateHome(t *testing.T) {
	t.Setenv("XDG_STATE_HOME", "/state")
	if got, want := installLogDir(), filepath.Join("/state", "tuna-installer"); got != want {
		t.Errorf("installLogDir() = %q, want %q", got, want)
	}
}

func TestInstallLogDirFallsBackToHome(t *testing.T) {
	t.Setenv("XDG_STATE_HOME", "")
	t.Setenv("HOME", "/home/tuna")
	if got, want := installLogDir(), filepath.Join("/home/tuna", ".local", "state", "tuna-installer"); got != want {
		t.Errorf("installLogDir() = %q, want %q", got, want)
	}
}

// A retried install must not clobber the previous attempt's output — that's
// the run most worth keeping, since it's the one that failed.
func TestOpenInstallLogAppendsAcrossCalls(t *testing.T) {
	t.Setenv("XDG_STATE_HOME", t.TempDir())

	f1, err := openInstallLog()
	if err != nil {
		t.Fatalf("openInstallLog() (1st) failed: %v", err)
	}
	if _, err := f1.WriteString("first attempt\n"); err != nil {
		t.Fatal(err)
	}
	f1.Close()

	f2, err := openInstallLog()
	if err != nil {
		t.Fatalf("openInstallLog() (2nd) failed: %v", err)
	}
	if _, err := f2.WriteString("second attempt\n"); err != nil {
		t.Fatal(err)
	}
	f2.Close()

	data, err := os.ReadFile(filepath.Join(installLogDir(), "install.log"))
	if err != nil {
		t.Fatal(err)
	}
	if got, want := string(data), "first attempt\nsecond attempt\n"; got != want {
		t.Errorf("install.log = %q, want %q", got, want)
	}
}

func TestOpenInstallLogModeIsPrivate(t *testing.T) {
	t.Setenv("XDG_STATE_HOME", t.TempDir())

	f, err := openInstallLog()
	if err != nil {
		t.Fatalf("openInstallLog() failed: %v", err)
	}
	defer f.Close()

	info, err := f.Stat()
	if err != nil {
		t.Fatal(err)
	}
	if perm := info.Mode().Perm(); perm != 0o600 {
		t.Errorf("install.log mode = %o, want 0600", perm)
	}
}
