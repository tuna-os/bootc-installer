package main

// ConfigureTarget wiring: the session and account steps store their picks
// for the installed system on the daemon path, and the session page owns
// the privacy toggle. Read as text.

import (
	"strings"
	"testing"
)

func TestConfigureTargetWiring(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		// The call and its warning.
		`command: [root.backendBin, "configure-target"]`,
		`objectName: "configureWarning"`,
		`objectName: "accountConfigureWarning"`,
		// The session stores its effective region; unchanged still stores.
		`if (root.daemonMode) root.runConfigure(root.regionTarget())`,
		// The account stores user and hostname, then moves on.
		`function applyAccount()`,
		`hostname: root.hostname`,
		`username: root.username`,
		`case 5: root.applyAccount(); break`,
		// Privacy: the location toggle travels with the region.
		`objectName: "privacyLocationRow"`,
		`qsTr("Location services")`,
		`locationServices: root.locationEnabled`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("installer.qml has no %q", want)
		}
	}
}
