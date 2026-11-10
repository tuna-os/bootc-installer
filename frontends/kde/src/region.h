#pragma once

// Region & language data for the welcome step's preflight section.
//
// The welcome step picks a language, a keyboard layout and a time zone. They
// go into the recipe as `locale`, `keyboard.layout` and `timezone`, and
// fisherman writes them to the installed system (#292). The confirm step
// lists them.
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

namespace region
{

struct Language {
    QString id;      // "en", "de", ...
    QString display; // native name, "English", "Deutsch", ...
};
QList<Language> availableLanguages();
QString systemLanguage(); // id of the live session's language, "" when unknown
// The recipe's `locale` for a language id: the language's default territory
// in UTF-8 ("de" -> "de_DE.UTF-8"). "" when Qt has no locale name of the
// form fisherman accepts for it: the recipe then has no `locale`.
QString localeName(const QString &languageId);

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

// Plain-POSIX TCP reachability: no QtNetwork link for one three-second
// probe. Not the portal's answer: the sandbox has the network share, and a
// portal says what the sandbox sees, not what fisherman on the host will.
bool hostReachable(const char *host, int port, int timeoutMs);

// One host and port the connectivity check tries.
struct Target {
    QString host;
    int port;
    bool operator==(const Target &other) const { return host == other.host && port == other.port; }
};
// The targets, in order: the registry of the selected image on 443 when
// there is one, then the targets the GNOME, COSMIC and XFCE frontends try
// (ghcr.io:443, then 8.8.8.8:53). The registry is first because it is the
// host the download needs (#301).
QList<Target> connectivityTargets(const QString &registryHost);
// True when one of the targets answers.
bool networkReachable(const QList<Target> &targets);

// The Plasma network settings, then two fallbacks, as one host command. The
// caller wraps it with flatpak-spawn --host in a Flatpak. Best effort: a
// desktop with none of the three opens nothing.
QStringList networkSettingsCommand();

} // namespace region
