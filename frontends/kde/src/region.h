#pragma once

// Region & language data for the welcome step's preflight section.
//
// The GNOME frontend collects a language, a keyboard layout and a timezone on
// dedicated steps (bootc_installer/defaults/language.py, keyboard.py,
// timezone.py) and shows them back on its confirm screen; its finals travel
// in the recipe dict, which fisherman silently ignores — its Recipe struct
// has no such fields, and this frontend's recipe stays field-identical to
// that struct (tests/unit/test_shared_recipe_schema.py pins it). So these
// values are wizard state, not recipe state: they are shown on the confirm
// screen, exactly where GNOME shows them, and not written anywhere else.
//
// Lists come from Qt and the platform, not from a bundled copy: languages
// from QLocale's own database, timezones from QTimeZone, keyboard layouts
// from the X server's evdev list (the host's when sandboxed) with a small
// built-in fallback. Keyboard *variants* are deliberately not offered: the
// GNOME list carries them per layout, but a first-install default layout is
// what the picker is for, and a variant picker doubles the UI for a value
// the installed desktop's own settings own afterwards.

#include <QList>
#include <QString>
#include <QStringList>

#include <optional>

namespace region
{

struct Language {
    QString id;      // "en", "de", ...
    QString display; // native name, "English", "Deutsch", ...
};
QList<Language> availableLanguages();
QString systemLanguage(); // id of the live session's language, "" when unknown

struct Keymap {
    QString id;          // "us", "de", ...
    QString description; // "English (US)", ...
};
QList<Keymap> availableKeyboardLayouts();
QString systemKeyboardLayout(); // "us": the GNOME fallback, detection owned by the desktop

QStringList availableTimezones(); // IANA ids, "America/New_York"
QString systemTimezone();         // the live session's id, "UTC" when unknown

// Pretty form of an IANA id for the pickers ("America/New_York" watches the
// underscore; GNOME shows city names from its own table, Qt has none).
QString timezoneDisplay(const QString &ianaId);

// Plain-POSIX TCP reachability: no QtNetwork link for one five-second
// probe. Not the portal's answer: the sandbox has the network share, and a
// portal says what the sandbox sees, not what fisherman on the host will.
bool hostReachable(const char *host, int port, int timeoutMs);

// One host and port the connectivity check tries.
struct Target {
    QString host;
    int port;
    bool operator==(const Target &other) const { return host == other.host && port == other.port; }
};
// shared/network/targets.json: the five frontends probe the same targets,
// wait the same time and honour the same variables.
inline constexpr int CONNECT_TIMEOUT_MS = 5000;
inline constexpr const char *SKIP_ENV_VARS[] = {"VANILLA_SKIP_CONN_CHECK",
                                                "TUNA_INSTALLER_SKIP_CONN_CHECK"};
// The registry that serves an image reference (shared/network/README.md):
// ostree prefixes and docker:// go, a local transport, a path or another
// URL has none, a name with no registry is Docker Hub's, and the port of
// the reference is kept (443 without one).
std::optional<Target> registryTarget(const QString &imgref);
// The targets, in order: the registry of the image when it has one, then
// the shared targets (ghcr.io:443, then 8.8.8.8:53). The registry is first
// because it is the host the download needs (#301). No target twice.
QList<Target> connectivityTargets(const QString &imgref);
// Whether a harness turned the check off: one of SKIP_ENV_VARS is set to a
// value that is not empty and not "0".
bool connectivityCheckSkipped();
// True when one of the targets answers within CONNECT_TIMEOUT_MS.
bool networkReachable(const QList<Target> &targets);

// The Plasma network settings, then two fallbacks, as one host command. The
// caller wraps it with flatpak-spawn --host in a Flatpak. Best effort: a
// desktop with none of the three opens nothing.
QStringList networkSettingsCommand();

} // namespace region
