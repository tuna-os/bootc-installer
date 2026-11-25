package main

// recovery-key: an encrypted install lands on its own screen with the key,
// a copy button, an acknowledgement tick, a QR dialog and a retry when the
// fetch failed. Read as text.

import (
	"strings"
	"testing"
)

func TestRecoveryScreen(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		`objectName: "recoveryTitle"`,
		`qsTr("Back Up Recovery Key")`,
		`objectName: "recoveryQrButton"`,
		`qsTr("Show QR Code for Recovery Key")`,
		`objectName: "recoveryQrOverlay"`,
		`objectName: "recoveryQrDoneButton"`,
		`objectName: "recoveryRetryButton"`,
		`objectName: "recoveryError"`,
		`objectName: "recoveryContinueButton"`,
		// The fetch runs after a daemon install; the key shapes the flow.
		`root.startRecoveryFetch()`,
		`command: [root.backendBin, "recovery-key"]`,
		`root.recoveryQr = answer.qr || ({})`,
		`if (root.showRecoveryScreen) pages.push(13)`,
		`case 13: if (root.recoveryKey !== "" && root.recoveryAck) flowNext(); break`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("installer.qml has no %q", want)
		}
	}
}
