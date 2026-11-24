package main

// prerelease and eula: conditional screens before the disk list. The
// disclaimer informs; the terms page gates Continue on the accept tick and
// offers only power off when the file cannot load. Read as text.

import (
	"strings"
	"testing"
)

func TestPrereleasePage(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		`objectName: "prereleaseTitle"`,
		`qsTr("Disclaimer")`,
		`objectName: "prereleaseContinueButton"`,
		`case 11: flowNext(); break`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("installer.qml has no %q", want)
		}
	}
}

func TestEulaPage(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		`objectName: "eulaTitle"`,
		`qsTr("Terms of use")`,
		`objectName: "eulaText"`,
		`objectName: "eulaAckButton"`,
		`qsTr("I have read and accept the Terms of Use")`,
		`objectName: "eulaContinueButton"`,
		`objectName: "eulaPowerButton"`,
		`case 12: if (root.eulaAccepted) flowNext(); break`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("installer.qml has no %q", want)
		}
	}
}
