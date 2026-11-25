package main

// wipe-or-free: the chosen disk holds data, so the wizard asks before it
// writes. Free space fits: choose. Too tight: only the whole disk, behind
// a three second countdown. Read as text.

import (
	"strings"
	"testing"
)

func TestWipePage(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		`objectName: "wipeTitle"`,
		`qsTr("Existing data found")`,
		`objectName: "wipeFreeRow"`,
		`qsTr("Install to Free Space")`,
		`objectName: "wipeEraseRow"`,
		`qsTr("Use Entire Disk")`,
		`objectName: "wipeContinueButton"`,
		`qsTr("Erase and Install (%1)")`,
		`root.installMode = root.wipeTight ? "erase" : "free_space"`,
		// The choice travels beside the recipe: the shared schema is exact.
		`installMode: root.installMode`,
		`case 10: flowNext(); break`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("installer.qml has no %q", want)
		}
	}
}
