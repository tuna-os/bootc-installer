package main

// The translation lint (#300). Every line of text the wizard shows goes
// through one of two calls: `root.text("key")` for a line the product can
// rebrand (shared/branding copy keys), and qsTr() for the rest. This test
// reads ui/*.qml and fails on a string literal that looks like prose and is
// in neither.
//
// It lives with the Go tests because `go test ./...` is the check CI runs
// for this frontend on every change.

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

var (
	qmlString = regexp.MustCompile(`"(?:[^"\\\n]|\\.)*"`)
	// Prose: a capital letter first, or two words.
	qmlProse = regexp.MustCompile(`^[A-Z][a-z]|[A-Za-z]{2,}[,.:;!?…]* +[A-Za-z]{2,}`)
	// A property whose string is not shown: an object's name, a key
	// sequence, a font stack.
	qmlNotText = regexp.MustCompile(`(\bobjectName|\bsequence|[fF]ontFamily):$`)
	qmlImport  = regexp.MustCompile(`^\s*import\b`)
)

// notProse are literals that match the pattern and are not text: the neutral
// product name the branding contract falls back to, and the key names the
// hint bar keeps for its own logic beside the translated ones.
var notProse = map[string]bool{
	`"Linux"`: true, `"Enter"`: true, `"Shift+Enter"`: true, `"Tab"`: true,
}

// stripQMLComments removes // comments, leaving string literals intact.
func stripQMLComments(line string) string {
	inString := false
	for i := 0; i < len(line); i++ {
		switch {
		case line[i] == '\\' && inString:
			i++
		case line[i] == '"':
			inString = !inString
		case !inString && strings.HasPrefix(line[i:], "//"):
			return line[:i]
		}
	}
	return line
}

// bareLiterals returns the prose literals of one QML source that no
// translation call wraps, as "line: literal".
func bareLiterals(source string) []string {
	found := []string{}
	generated := false
	for n, raw := range strings.Split(source, "\n") {
		// The copy table is generated from shared/branding/copy-defaults.json
		// and is read only through root.text().
		if strings.Contains(raw, "COPY-DEFAULTS-BEGIN") {
			generated = true
		}
		if strings.Contains(raw, "COPY-DEFAULTS-END") {
			generated = false
			continue
		}
		if generated {
			continue
		}
		line := stripQMLComments(raw)
		if qmlImport.MatchString(line) {
			continue
		}
		for _, loc := range qmlString.FindAllStringIndex(line, -1) {
			literal := line[loc[0]:loc[1]]
			body := literal[1 : len(literal)-1]
			if !qmlProse.MatchString(body) || notProse[literal] || strings.HasPrefix(body, "<") {
				continue
			}
			before := strings.TrimRight(line[:loc[0]], " ")
			if strings.HasSuffix(before, "qsTr(") || qmlNotText.MatchString(before) {
				continue
			}
			found = append(found, strings.TrimSpace(strings.Join([]string{itoa(n + 1), literal}, ": ")))
		}
	}
	return found
}

func TestEveryUserFacingStringIsTranslatable(t *testing.T) {
	files, err := filepath.Glob(filepath.Join("..", "ui", "*.qml"))
	if err != nil || len(files) < 5 {
		t.Fatalf("ui/*.qml: %v (%d files)", err, len(files))
	}
	wrapped := 0
	for _, file := range files {
		data, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		wrapped += strings.Count(string(data), "qsTr(")
		for _, literal := range bareLiterals(string(data)) {
			t.Errorf("%s:%s is user-facing text outside qsTr() and root.text()", filepath.Base(file), literal)
		}
	}
	// Guards the guard: with no qsTr at all the scan above proves nothing
	// about the files it was meant to read.
	if wrapped < 100 {
		t.Errorf("only %d qsTr() calls in ui/: the wizard's text is not marked", wrapped)
	}
}

// The lint itself: it must see a bare literal in each property that shows
// text, and must leave the wrapped and the non-text ones alone.
func TestTranslationLintCatchesABareLiteral(t *testing.T) {
	bare := `
        StyledText { text: "Your account" }
        DankCard { title: "Summary" }
        DankTextField { placeholderText: "Enter passphrase" }
        DankListItem { primaryText: "Power off"; secondaryText: "Shut down this computer" }
        StyledText { text: root.ok ? qsTr("Fine") : "Passwords do not match." }
        StyledText { text: "step " + n + " of the install" }
        StyledText { objectName: "accountTitle"; text: "Account" }
    `
	if got := bareLiterals(bare); len(got) != 8 {
		t.Errorf("found %d bare literals, want 8: %v", len(got), got)
	}
	fine := `
        import "progress.js" as BarMath
        StyledText { text: qsTr("Your account") }
        StyledText { text: root.text("welcome_title") }
        StyledText { objectName: "Account Title"; color: "#D0BCFF" }
        Shortcut { sequence: "Shift+Return" }
        // text: "A comment is not text"
        StyledText { text: "⚠  " + root.text("confirm_warning", { disk: "—" }) }
        property string fs: "xfs"
    `
	if got := bareLiterals(fine); len(got) != 0 {
		t.Errorf("flagged what is not a bare literal: %v", got)
	}
}
