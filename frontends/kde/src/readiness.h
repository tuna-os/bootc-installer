#pragma once

// Readiness stamp: a machine-readable record that the UI really came up.
//
// WHY THIS EXISTS
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
// WHAT THIS STAMP CLAIMS
//
// `signal=frame-swapped`. The five frontends cannot all make the same claim,
// and the field records which one this is rather than flattening them:
//
//   gtk-map        the GTK `map` signal — the widget was mapped.
//                  (bootc-installer, tuna-installer-xfce)
//   first-frame    the toolkit asked us to build a frame. Proves the event
//                  loop runs; does NOT prove a surface was presented.
//                  (tuna-installer-cosmic — libcosmic is iced-on-wgpu and
//                  offers no map equivalent)
//   frame-swapped  QQuickWindow::frameSwapped — a frame actually reached the
//                  compositor. (here, and tuna-installer-niri)
//
// Flattening these would let the smoke test believe a frame callback proves a
// mapped window, on the very frontend whose window never appeared.

#include <QObject>
#include <QString>

namespace readiness
{

/// Write the stamp for @p page into @p runtimeDir.
///
/// Split out from armStamp() so the format — which a smoke test parses — is
/// reachable from a test without standing up a window. Returns false and
/// writes nothing if @p runtimeDir is empty or unwritable.
bool writeStamp(const QString &runtimeDir, const QString &page, qint64 msSinceEpoch);

/// Connect to @p root's frameSwapped and stamp once, the first time a frame
/// reaches the compositor.
///
/// frameSwapped rather than the engine's objectCreated: an object tree that
/// finished building is not a window anyone saw, and stamping there would
/// reproduce exactly the gap this closes. It fires every frame, so the
/// connection is single-shot.
///
/// Best-effort by design. A frontend that cannot write its stamp must still
/// install: this is observability, and failing startup because a tmpfs was
/// read-only would be a far worse bug than the one it detects.
void armStamp(QObject *root);

} // namespace readiness
