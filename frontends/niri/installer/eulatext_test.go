package main

import (
	"os"
	"strings"
	"testing"
)

// The AppStream file is shown as its terms, not as XML (the walk showed
// the raw XML on the eula page).
func TestEulaPlainTextReadsTheAgreement(t *testing.T) {
	data, err := os.ReadFile("../../kde/tests/testdata/eula-agreement.xml")
	if err != nil {
		t.Fatal(err)
	}
	got, err := eulaPlainText(data)
	if err != nil {
		t.Fatal(err)
	}
	want := "Use of this system\n\nDo not use this experiment for anything important.\n\n" +
		"You agree to the following:\n\n  • File bugs when it breaks.\n  • Keep backups of anything you keep.\n\n" +
		"Updates\n\nUpdates arrive automatically.\n\n  1. First the base system.\n  2. Then the applications."
	if got != want {
		t.Errorf("got:\n%s\nwant:\n%s", got, want)
	}
	if strings.Contains(got, "<") {
		t.Errorf("markup in the text: %q", got)
	}
}

func TestEulaPlainTextKeepsPlainText(t *testing.T) {
	got, err := eulaPlainText([]byte("  Terms.\n\nMore terms.\n"))
	if err != nil || got != "Terms.\n\nMore terms." {
		t.Errorf("got %q, %v", got, err)
	}
}

func TestEulaPlainTextWithoutAnEulaIsAnError(t *testing.T) {
	if _, err := eulaPlainText([]byte(`<component><agreement type="privacy"><agreement_section><p>x</p></agreement_section></agreement></component>`)); err == nil {
		t.Error("an XML file with no eula agreement is no terms of use")
	}
	if _, err := eulaPlainText([]byte(`<component><agreement type="eula">`)); err == nil {
		t.Error("broken XML must not pass")
	}
}
