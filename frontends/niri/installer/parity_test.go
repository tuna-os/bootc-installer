package main

// QML/CLI parity contract for the GNOME/XFCE alignment: every feature the
// wizard promises in docs has a backend command behind it and a QML surface
// above it. Read as text — there is no Qt runtime in CI — the way
// TestQMLHoldsTheAccountStep already does for the account step.

import (
	"strings"
	"testing"
)

// Every new subcommand is dispatched and advertised: a command the usage
// text does not name is one the QML cannot discover.
func TestCLIAdvertisesParityCommands(t *testing.T) {
	got := runCLI(t, nil)
	if got.code != 1 {
		t.Fatalf("code = %d, want the usage exit", got.code)
	}
	for _, want := range []string{
		"catalog", "session-get", "session-set", "cancel", "log-path",
		"poweroff", "firmware", "netcheck", "network-settings",
	} {
		if !strings.Contains(got.stderr, want) {
			t.Errorf("usage text is missing %q; stderr = %q", want, got.stderr)
		}
	}
}

// The QML half: the filesystem choice, the catalog step with its
// conditional account, the blocking gates with power dialog, log copy and
// cancel, the session preflight, and the tour — each present by name, so a
// deletion fails here instead of silently dropping a step.
func TestQMLHoldsParitySteps(t *testing.T) {
	qml := readQML(t)
	for _, want := range []string{
		// (a) filesystem choice defaulting from the leaf.
		`root.filesystem`, `applySelection`, `btrfsSubvolumes`,
		`the choices of the selected image`,
		// (b) catalog step and conditional account.
		`catalogProc`, `sortedLeaves`, `needs_user_creation`,
		`needsUserCreation`, `chooseAndNext`, `"Source"`,
		`composeFsBackend`, `imageRecipe`, `selectLeaf`, `sourceSearch`,
		`sourceChooseHint`, `confirmTargetImage`,
		// (c) blocking gates, poweroff dialog, log copy, cancel.
		`gateOpen`, `Continue anyway`, `Firmware setup`,
		`powerOpen`, `poweroffProc`, `firmwareProc`,
		`Copy log`, `cancelProc`, `cancelInstallButton`,
		// The cancel that asks first, and its own done page (#299).
		`cancelOpen`, `cancelConfirmButton`, `confirmCancel`,
		`installCancelled`, `"done_cancelled_title"`,
		// (d) locale/keyboard/timezone/network preflight.
		`sessionProc`, `sessionSetProc`, `applySession`,
		`Recheck`, `sessionError`, `sessionChanges`, `withCurrent`,
		`sessionFailed`,
		// The offline gate and the network tool (#301).
		`downloadBlocked`, `netProc`, `netToolProc`, `OfflineNotice`,
		`Network settings`,
		// (e) tour carousel.
		`tourSlides`, `tourOpen`, `Take a tour`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("ui/installer.qml lacks %q", want)
		}
	}
}

// The old hardcoded behaviors are gone: the confirm summary and the
// recipe read the filesystem property, never a literal. (The property's
// own "xfs" default stays: it is the fallback when no leaf names one,
// mirroring XFCE's `or "xfs"`.)
func TestQMLDroppedTheHardcodedPaths(t *testing.T) {
	qml := readQML(t)
	if strings.Contains(qml, `text: "xfs"; isMonospace: true`) {
		t.Errorf("ui/installer.qml still shows a hardcoded xfs on confirm")
	}
	if !strings.Contains(qml, `filesystem: root.filesystem`) {
		t.Errorf("ui/installer.qml recipe does not read the filesystem property")
	}
}
