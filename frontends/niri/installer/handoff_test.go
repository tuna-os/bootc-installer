package main

// handoff: after the install and the recovery key, the daemon hands the new
// system over. The call runs once on entry with no mode; Continue quits
// into a kept session, Restart boots the new system. Read as text.

import (
	"strings"
	"testing"
)

func TestHandoffPage(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		`objectName: "handoffTitle"`,
		`objectName: "handoffBody"`,
		`objectName: "handoffContinueButton"`,
		`objectName: "handoffNotNowButton"`,
		`objectName: "handoffRebootButton"`,
		`objectName: "handoffRetryButton"`,
		// The call runs once on entry with no mode: the daemon decides.
		`if (root.currentPage === 14) root.startHandoff()`,
		`command: [root.backendBin, "handoff"]`,
		`answer.sessionKeepsRunning === true`,
		// The page matches Probe's handoff hint: migrate, soft-reboot,
		// or reboot when the hint is missing.
		`root.handoffMode = facts.handoffMode || "reboot"`,
		`root.handoffMode === "soft_reboot"`,
		`if (root.showHandoffScreen) pages.push(14)`,
		`case 14: if (root.handoffKeepsRunning && root.handoffError === "") Qt.quit(); break`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("installer.qml has no %q", want)
		}
	}
}
