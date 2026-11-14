package main

// Every component in ui/ is listed in ui/qmldir.
//
// installer.qml finds its siblings through the directory import, and a
// directory with a qmldir exposes ONLY the types that qmldir lists. The
// bundle published from a5396bbe listed Theme alone, so on a live Niri
// session Quickshell stopped at
//
//	ERROR: Failed to load configuration
//	ERROR:   caused by @installer.qml[1540:21]: DankButton is not a type
//
// and no installer window ever opened (marlin:niri, iso-builder run
// 43577526657). The docs capture harness and the browser build never saw it:
// they do not run Quickshell's loader. Reproduced offscreen with the
// published bundle's own quickshell in the org.kde.Platform 6.11 runtime, and
// fixed by listing the types.
//
// Falsification: delete a `Dank*` line from ui/qmldir and this test fails
// naming the file; the offscreen load of the published bundle prints
// "<Type> is not a type" for the same omission.

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

func TestQmldirListsEveryComponent(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "ui", "qmldir"))
	if err != nil {
		t.Fatal(err)
	}
	listed := map[string]string{}
	for _, line := range strings.Split(string(raw), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 || strings.HasPrefix(fields[0], "#") {
			continue
		}
		// "singleton Name 1.0 File.qml" or "Name File.qml".
		if fields[0] == "singleton" || fields[0] == "internal" {
			fields = fields[1:]
		}
		listed[fields[len(fields)-1]] = fields[0]
	}
	files, err := filepath.Glob(filepath.Join("..", "ui", "*.qml"))
	if err != nil {
		t.Fatal(err)
	}
	component := regexp.MustCompile(`^[A-Z]`)
	for _, file := range files {
		name := filepath.Base(file)
		if name == "installer.qml" || !component.MatchString(name) {
			continue
		}
		if listed[name] != strings.TrimSuffix(name, ".qml") {
			t.Errorf("ui/qmldir does not list %s as %s", name, strings.TrimSuffix(name, ".qml"))
		}
	}
	if len(listed) == 0 {
		t.Fatal("ui/qmldir lists nothing")
	}
}
