package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ../../../shared/progress/recovery-key-cases.json: the redacted form is
// the same in every frontend that keeps a log, byte for byte (#337).
var recoveryKeyDir = filepath.Join("..", "..", "..", "shared", "progress")

type recoveryKeySpec struct {
	Key           string `json:"key"`
	Placeholder   string `json:"placeholder"`
	Transcript    string `json:"transcript"`
	RedactedEvent string `json:"redacted_event"`
	Lines         []struct {
		Name     string `json:"name"`
		KnownKey bool   `json:"known_key"`
		Line     string `json:"line"`
		Redacted string `json:"redacted"`
	} `json:"lines"`
}

func loadRecoveryKeySpec(t *testing.T) recoveryKeySpec {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(recoveryKeyDir, "recovery-key-cases.json"))
	if err != nil {
		t.Skipf("shared/progress not available: %v", err)
	}
	var spec recoveryKeySpec
	if err := json.Unmarshal(data, &spec); err != nil {
		t.Fatal(err)
	}
	return spec
}

func TestRedactRecoveryKeyFollowsTheSharedCases(t *testing.T) {
	spec := loadRecoveryKeySpec(t)
	if spec.Placeholder != redactedKey {
		t.Fatalf("placeholder %q, shared %q", redactedKey, spec.Placeholder)
	}
	if len(spec.Lines) < 5 {
		t.Fatalf("only %d cases", len(spec.Lines))
	}
	for _, c := range spec.Lines {
		known := ""
		if c.KnownKey {
			known = spec.Key
		}
		if got := redactRecoveryKey(c.Line, known); got != c.Redacted {
			t.Errorf("%s:\n got %q\nwant %q", c.Name, got, c.Redacted)
		}
	}
	if redactRecoveryKey("", spec.Key) != "" {
		t.Error("empty text must stay empty")
	}
}

// The transcript through the same writers runInstall gives fisherman, read
// back from install.log: the key is not in the file, the redacted event is,
// and every other line is as fisherman wrote it.
func TestRecoveryKeyIsNotInTheInstallLog(t *testing.T) {
	spec := loadRecoveryKeySpec(t)
	events, err := os.ReadFile(filepath.Join(recoveryKeyDir, spec.Transcript))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(events, []byte(spec.Key)) {
		t.Fatal("the transcript has no key to redact")
	}
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	file, err := openInstallLog()
	if err != nil {
		t.Fatal(err)
	}
	log := newRedactedLog(file)
	stdout, stderr := log.Stream(), log.Stream()
	// A pipe hands over arbitrary pieces: split the stream mid-line.
	half := len(events) / 2
	if _, err := stdout.Write(events[:half]); err != nil {
		t.Fatal(err)
	}
	if _, err := stdout.Write(events[half:]); err != nil {
		t.Fatal(err)
	}
	// stderr repeats the key after the event, without a newline at the end.
	if _, err := stderr.Write([]byte("enrolled slot 1 with " + spec.Key + ".\nRecovery key: " + spec.Key)); err != nil {
		t.Fatal(err)
	}
	if err := stdout.Flush(); err != nil {
		t.Fatal(err)
	}
	if err := stderr.Flush(); err != nil {
		t.Fatal(err)
	}
	file.Close()

	written, err := os.ReadFile(installLogDisplayPath())
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(written, []byte(spec.Key)) {
		t.Fatalf("the recovery key is in install.log:\n%s", written)
	}
	var want []string
	redacted := 0
	for _, line := range strings.Split(strings.TrimSuffix(string(events), "\n"), "\n") {
		if strings.Contains(line, `"recovery_key"`) {
			line = spec.RedactedEvent
			redacted++
		}
		want = append(want, line)
	}
	if redacted != 1 {
		t.Fatalf("%d recovery_key events in the transcript, want 1", redacted)
	}
	want = append(want, "enrolled slot 1 with [redacted].", "Recovery key: [redacted]")
	if got := string(written); got != strings.Join(want, "\n")+"\n" {
		t.Errorf("install.log:\n%s\nwant:\n%s", got, strings.Join(want, "\n"))
	}
	if !strings.Contains(string(written), `"type":"recovery_key"`) {
		t.Error("the event type must stay in the log")
	}
}

// The Copy log button copies the in-memory log, which shows the key; the
// clipboard gets the redacted form.
func TestCopyLogIsRedactedInTheUI(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "ui", "installer.qml"))
	if err != nil {
		t.Fatal(err)
	}
	qml := string(data)
	for _, want := range []string{"function sharedLog()", "text: root.sharedLog()", `"[redacted]"`} {
		if !strings.Contains(qml, want) {
			t.Errorf("ui/installer.qml lacks %q", want)
		}
	}
	if strings.Contains(qml, "text: root.installLog\n                }") {
		t.Error("the hidden clipboard TextEdit still copies root.installLog")
	}
}
