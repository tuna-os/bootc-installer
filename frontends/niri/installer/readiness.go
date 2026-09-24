package main

// Readiness stamp: a machine-readable record that the UI really came up.
//
// # Why this exists
//
// tunaOS's installer-smoke.yml proves the frontend is up with `flatpak ps`,
// which answers "is the process alive". That is not the same question as "did
// the user get a window", and the two have already diverged in production: the
// COSMIC leg had the installer process running with no window ever appearing
// on screen, and the check stayed green. The only thing that noticed was a
// human looking at a screenshot.
//
// Inferring it from pixels is the other half of the same problem — it needs a
// compositor that renders, and four of the five desktops need a DRM render
// node that GitHub-hosted runners do not have. So the frontend says so itself,
// in a file any runner can read over SSH with no GPU and no OCR.
//
// # Why the Go side writes it
//
// The window lives in QML, not here. QML is where the signal comes from and Go
// is where it gets written, for two reasons: Quickshell's file-writing surface
// varies across versions in a way a stamp cannot afford to depend on, and
// putting the write here makes it unit-testable — which, for the one file a
// smoke test will trust, is worth an extra process spawn at startup.
//
// # What this stamp claims
//
// `signal=frame-swapped`, and the distinction is deliberate. The five
// frontends cannot all make the same claim:
//
//	gtk-map        the GTK `map` signal — the widget was mapped.
//	                (bootc-installer, tuna-installer-xfce)
//	first-frame    the toolkit asked us to build a frame. Proves the event
//	                loop runs; does NOT prove a surface was presented.
//	                (tuna-installer-cosmic — libcosmic is iced-on-wgpu and
//	                offers no map equivalent)
//	frame-swapped  Qt's QQuickWindow::frameSwapped — a frame was actually
//	                swapped to the compositor. (here)
//
// Flattening these would let the smoke test believe a frame callback proves a
// mapped window, on the very frontend whose window never appeared.

import (
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// $XDG_RUNTIME_DIR is per-user, tmpfs, and cleared between sessions, so a
// stale stamp cannot survive a reboot and be read as a fresh success.
const stampName = "tuna-installer-ready"

const appID = "org.tunaos.InstallerNiri"

// writeReadinessStamp records that a frame reached the compositor.
//
// runtimeDir and now are parameters rather than being read from the
// environment and the clock, so the test can assert the exact bytes a smoke
// test will parse.
func writeReadinessStamp(runtimeDir, page string, now time.Time) error {
	if runtimeDir == "" {
		return fmt.Errorf("XDG_RUNTIME_DIR is not set")
	}
	if page == "" {
		page = "unknown"
	}

	body := fmt.Sprintf(
		"app_id=%s\nwindow=ApplicationWindow\nsignal=frame-swapped\nmapped_at=%.3f\npage=%s\n",
		appID, float64(now.UnixNano())/1e9, page,
	)

	// Write to a temp file and rename, so a reader over SSH never sees a
	// half-written stamp and concludes the wrong thing came up.
	path := filepath.Join(runtimeDir, stampName)
	tmp := fmt.Sprintf("%s.tmp%d", path, os.Getpid())
	if err := os.WriteFile(tmp, []byte(body), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// readinessStamp is the `readiness` subcommand, invoked by the QML layer from
// ApplicationWindow.onFrameSwapped.
//
// Best-effort by design: it reports failure on stderr and exits 0 regardless.
// A frontend that cannot write its stamp must still install — this is
// observability, and failing the UI's startup path because a tmpfs was
// read-only would be a far worse bug than the one it detects.
func readinessStamp(page string) {
	if err := writeReadinessStamp(os.Getenv("XDG_RUNTIME_DIR"), page, time.Now()); err != nil {
		fmt.Fprintf(os.Stderr, "readiness: could not write stamp: %v\n", err)
	}
}
