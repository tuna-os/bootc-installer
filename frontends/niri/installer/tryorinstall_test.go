package main

// try-or-install: on live media the welcome page offers Try and Install now.
// Read as text — there is no Qt runtime in CI — like the parity tests.

import (
	"strings"
	"testing"
)

func TestTryOrInstallButtons(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		// The two live-media actions, by object name.
		`objectName: "tryButton"`, `objectName: "installNowButton"`,
		// Try quits into the live session; Install advances the wizard.
		`qsTr("Try %1")`, `qsTr("Install now")`, `onClicked: Qt.quit()`,
		// Off live media the single button keeps its branding copy.
		`visible: root.isLive`, `visible: !root.isLive`,
		// The readiness stamp names the spec screen id.
		`"try-or-install"`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("installer.qml has no %q", want)
		}
	}
}
