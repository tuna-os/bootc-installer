package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestStampBodyMatchesTheContract(t *testing.T) {
	dir := t.TempDir()
	at := time.Unix(1786215232, 825000000)

	if err := writeReadinessStamp(dir, "welcome", at); err != nil {
		t.Fatalf("writeReadinessStamp: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(dir, stampName))
	if err != nil {
		t.Fatalf("reading stamp: %v", err)
	}

	// Exact bytes, because a smoke test parses these and the whole point of
	// the contract is that the five frontends agree on the format.
	want := "app_id=org.tunaos.InstallerNiri\n" +
		"window=ApplicationWindow\n" +
		"signal=frame-swapped\n" +
		"mapped_at=1786215232.825\n" +
		"page=welcome\n"
	if string(got) != want {
		t.Errorf("stamp body mismatch:\ngot:\n%s\nwant:\n%s", got, want)
	}
}

func TestSignalIsNotOverclaimed(t *testing.T) {
	// This frontend stamps from Qt's frameSwapped — a frame actually reaching
	// the compositor. If that ever becomes `gtk-map` (a stronger claim this
	// toolkit cannot make) or `first-frame` (a weaker one it does not need to
	// make), the smoke test would weigh this frontend's evidence wrongly.
	dir := t.TempDir()
	if err := writeReadinessStamp(dir, "welcome", time.Now()); err != nil {
		t.Fatalf("writeReadinessStamp: %v", err)
	}
	body, _ := os.ReadFile(filepath.Join(dir, stampName))
	if !strings.Contains(string(body), "signal=frame-swapped") {
		t.Errorf("expected signal=frame-swapped, got:\n%s", body)
	}
}

func TestMissingPageDoesNotProduceAnEmptyField(t *testing.T) {
	// A trailing `page=` would parse as a real page named "" downstream.
	dir := t.TempDir()
	if err := writeReadinessStamp(dir, "", time.Now()); err != nil {
		t.Fatalf("writeReadinessStamp: %v", err)
	}
	body, _ := os.ReadFile(filepath.Join(dir, stampName))
	if !strings.Contains(string(body), "page=unknown") {
		t.Errorf("expected page=unknown, got:\n%s", body)
	}
}

func TestMissingRuntimeDirIsAnErrorNotAPanic(t *testing.T) {
	// The installer must survive this — see the best-effort note in
	// readiness.go. readinessStamp swallows the error; this asserts the error
	// is actually produced rather than a stamp being written somewhere odd.
	if err := writeReadinessStamp("", "welcome", time.Now()); err == nil {
		t.Error("expected an error when XDG_RUNTIME_DIR is unset")
	}
}

func TestStampIsWrittenAtomically(t *testing.T) {
	// Written via rename, so a reader over SSH never catches a partial file.
	// Asserted by proving no temp file survives a successful write.
	dir := t.TempDir()
	if err := writeReadinessStamp(dir, "welcome", time.Now()); err != nil {
		t.Fatalf("writeReadinessStamp: %v", err)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 || entries[0].Name() != stampName {
		var names []string
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Errorf("expected only %q to remain, found %v", stampName, names)
	}
}
