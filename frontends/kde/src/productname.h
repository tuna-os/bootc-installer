#pragma once

// The product name shown to the user — "Skipjack", "Bonito", "Yellowfin", …
//
// tunaOS builds a per-variant PRETTY_NAME in build_scripts/90-image-info.sh and
// writes it into /etc/os-release. Hardcoding "TunaOS" in the UI means a
// Skipjack ISO shows the wrong name, which is the whole reason this exists.

#include <QString>

namespace product {

// Reads PRETTY_NAME from os-release, preferring the HOST's copy under
// /run/host/etc/os-release: this app ships as the flatpak
// org.tunaos.InstallerKde, and inside the sandbox /etc/os-release is the
// runtime's (Freedesktop/KDE), not the variant's.
//
// Falls back to "TunaOS" when neither file is readable or PRETTY_NAME is empty
// or unset. The fallback is load-bearing: an unreadable file must never produce
// "Install " with a blank after it.
QString resolve();

// The parsing half, exposed so it can be exercised without touching the real
// filesystem. Returns an empty string when the text has no usable PRETTY_NAME.
QString prettyNameFrom(const QString &osReleaseText);

} // namespace product
