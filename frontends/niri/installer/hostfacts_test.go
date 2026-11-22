package main

// Tests for hostfacts.go: release type parsing and the EULA lookup.

import (
	"os"
	"path/filepath"
	"testing"
)

func writeTemp(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "os-release")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv(osReleaseEnv, path)
	return path
}

func TestOsReleaseType(t *testing.T) {
	for content, want := range map[string]string{
		"NAME=X\nRELEASE_TYPE=pre-release\n": "pre-release",
		"RELEASE_TYPE=experiment\n":          "experiment",
		"RELEASE_TYPE=\"pre-release\"\n":     "pre-release",
		"NAME=X\n":                           "stable",
		"RELEASE_TYPE=lts\n":                 "stable",
		"RELEASE_TYPE=bogus\n":               "stable",
	} {
		writeTemp(t, content)
		if got := osReleaseType(); got != want {
			t.Errorf("%q: got %q, want %q", content, got, want)
		}
	}
}

func TestOsReleaseTypeMissingFile(t *testing.T) {
	t.Setenv(osReleaseEnv, filepath.Join(t.TempDir(), "absent"))
	if got := osReleaseType(); got != "stable" {
		t.Errorf("missing file: got %q, want stable", got)
	}
}

func TestOsReleaseExperiment(t *testing.T) {
	writeTemp(t, "RELEASE_TYPE=experiment\nEXPERIMENT=\"Try our new thing\"\n")
	if got := osReleaseExperiment(); got != "Try our new thing" {
		t.Errorf("got %q", got)
	}
	writeTemp(t, "NAME=X\n")
	if got := osReleaseExperiment(); got != "" {
		t.Errorf("no key: got %q", got)
	}
}

func TestEulaPathsPreferEnv(t *testing.T) {
	t.Setenv(eulaEnv, "/tmp/custom-eula.xml")
	if got := eulaPaths(); len(got) != 1 || got[0] != "/tmp/custom-eula.xml" {
		t.Errorf("got %v", got)
	}
}

func TestEulaPathIsShared(t *testing.T) {
	t.Setenv(eulaEnv, "")
	if got := eulaPaths(); len(got) != 1 || got[0] != "/usr/share/tuna-installer/eula.xml" {
		t.Errorf("every frontend reads one path: got %v", got)
	}
}
