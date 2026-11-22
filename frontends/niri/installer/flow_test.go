package main

// The conditional-screen flow: prerelease, eula, rst, wipe-or-free,
// recovery-key and handoff join the wizard only when they have something to
// show. Read as text — there is no Qt runtime in CI — like the parity tests.

import (
	"strings"
	"testing"
)

func TestConditionalFlowPages(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		// New StackLayout slots live at the end; 0-8 never move.
		`"rst", "wipe-or-free", "prerelease", "eula", "recovery-key", "handoff"`,
		`qsTr("Intel RST")`, `qsTr("Existing data")`, `qsTr("Disclaimer")`,
		`qsTr("Terms of use")`, `qsTr("Recovery key")`, `qsTr("Handoff")`,
		// The flow skips what has nothing to show.
		`if (root.showPrerelease) pages.push(11)`,
		`if (root.showEula) pages.push(12)`,
		`if (root.showRst) pages.push(9)`,
		`if (root.showWipe) pages.push(10)`,
		// Post-install screens join after the install ends.
		`if (root.showRecoveryScreen) pages.push(13)`,
		`if (root.showHandoffScreen) pages.push(14)`,
		// Back covers the new pages; the install and after do not go back.
		`root.currentPage !== 13 && root.currentPage !== 14`,
		// detect reports the screen conditions.
		`root.intelRst = facts.intelRst === true`,
		`root.releaseType = facts.releaseType`,
		`root.daemonMode = facts.daemon === true`,
		// The EULA arrives from its own subcommand at startup.
		`command: [root.backendBin, "eula"]`,
		`eulaProc.running = true`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("installer.qml has no %q", want)
		}
	}
}
