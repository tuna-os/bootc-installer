package main

// rst: Probe reports Intel RST, so the wizard names the missing disk before
// the disk list. Warns and continues; never blocks. Read as text.

import (
	"strings"
	"testing"
)

func TestRstPage(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		`objectName: "rstTitle"`,
		`qsTr("Intel RST is on")`,
		`objectName: "rstContinueButton"`,
		`objectName: "rstPowerButton"`,
		`objectName: "rstFirmwareButton"`,
		`case 9: flowNext(); break`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("installer.qml has no %q", want)
		}
	}
}
