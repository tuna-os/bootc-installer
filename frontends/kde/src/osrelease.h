#pragma once

// Release facts from os-release: whether this product is a pre-release or
// an experiment (shared/flow/screens.yaml `prerelease`).
//
// gnome-setup reads RELEASE_TYPE and EXPERIMENT the same way, plus
// SETUP_OVERRIDE_OS_RELEASE_TYPE and SETUP_OVERRIDE_OS_EXPERIMENT for its
// tests; this reader honours those overrides too, so one harness drives
// every frontend.

#include <QHash>
#include <QString>

namespace osrelease
{

// Test seam: an os-release file to read instead of the host's.
inline constexpr const char *FILE_ENV = "TUNA_OS_RELEASE_FILE";

// The host's os-release text: TUNA_OS_RELEASE_FILE first, then the standard
// paths (the same list branding::resolve() reads).
QString readText();

// The parsed file.
QHash<QString, QString> read();

// True when RELEASE_TYPE is `pre-release` or `experiment`. Anything else —
// `stable`, `lts`, unset, or a value this reader does not know — counts as
// stable.
bool isPrerelease(const QHash<QString, QString> &osRelease);

// The EXPERIMENT text, for the disclaimer page. Empty when unset.
QString experimentText(const QHash<QString, QString> &osRelease);

} // namespace osrelease
