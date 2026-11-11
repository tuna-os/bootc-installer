#include "region.h"

#include <QFile>
#include <QLocale>
#include <QRegularExpression>
#include <QSet>
#include <QTimeZone>

#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <cstring>

namespace region
{

QList<Language> availableLanguages()
{
    // One row per language, not per locale: matchingLocales returns every
    // territory variant separately, and a first-install picker wants
    // "Deutsch" once, not thirty times.
    QList<Language> out;
    QSet<QString> seen;
    const QList<QLocale> locales =
        QLocale::matchingLocales(QLocale::AnyLanguage, QLocale::AnyScript, QLocale::AnyCountry);
    for (const QLocale &locale : locales) {
        const QString id = QLocale::languageToCode(locale.language());
        if (id.isEmpty() || seen.contains(id))
            continue;
        seen.insert(id);
        QString display = locale.nativeLanguageName();
        if (display.isEmpty())
            display = id;
        else
            display = display.left(1).toUpper() + display.mid(1);
        out << Language{id, display};
    }
    std::sort(out.begin(), out.end(),
              [](const Language &a, const Language &b) { return a.display < b.display; });
    return out;
}

QString systemLanguage()
{
    return QLocale::languageToCode(QLocale::system().language());
}

QString localeName(const QString &languageId)
{
    if (languageId.isEmpty())
        return {};
    const QLocale::Language language = QLocale::codeToLanguage(languageId);
    if (language == QLocale::AnyLanguage || language == QLocale::C)
        return {};
    // name() is "language_TERRITORY"; fisherman's rule is
    // language[_TERRITORY][.codeset] with a 2-3 letter lower-case language.
    const QString name = QLocale(language).name();
    static const QRegularExpression valid(QStringLiteral("^[a-z]{2,3}(_[A-Z]{2,3})?$"));
    if (!valid.match(name).hasMatch())
        return {};
    return name + QStringLiteral(".UTF-8");
}

namespace
{

// The X server's layout table, the same source the desktop's own keyboard
// settings read. The host's copy when sandboxed: the runtime's table is the
// Flatpak's, not the machine's.
QStringList evdevPaths(bool flatpak)
{
    QStringList paths;
    if (flatpak)
        paths << QStringLiteral("/run/host/usr/share/X11/xkb/rules/evdev.lst");
    paths << QStringLiteral("/usr/share/X11/xkb/rules/evdev.lst");
    paths << QStringLiteral("/etc/X11/xkb/rules/evdev.lst");
    return paths;
}

QList<Keymap> parseEvdev(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
        return {};
    QList<Keymap> out;
    bool inLayouts = false;
    while (!f.atEnd()) {
        const QString line = QString::fromUtf8(f.readLine()).trimmed();
        if (line.startsWith(QLatin1Char('!'))) {
            inLayouts = line.contains(QStringLiteral("layout"));
            continue;
        }
        if (!inLayouts || line.isEmpty())
            continue;
        // "  us              English (US)": code, then whitespace, then the name.
        const int split = line.indexOf(QRegularExpression(QStringLiteral("\\s{2,}")));
        if (split < 0)
            continue;
        const QString id = line.left(split).trimmed();
        const QString description = line.mid(split).trimmed();
        if (!id.isEmpty() && !description.isEmpty() && !id.contains(QLatin1Char(' ')))
            out << Keymap{id, description};
    }
    return out;
}

} // namespace

QList<Keymap> availableKeyboardLayouts()
{
    const bool flatpak = QFile::exists(QStringLiteral("/.flatpak-info"));
    for (const QString &path : evdevPaths(flatpak)) {
        QList<Keymap> layouts = parseEvdev(path);
        if (!layouts.isEmpty())
            return layouts;
    }
    // No XKB table (a container without xkeyboard-config): the GNOME step's
    // fallback is us/pc105, so the list at least offers the common layouts.
    // Kept short on purpose — see the header on variants.
    return {
        {QStringLiteral("us"), QStringLiteral("English (US)")},
        {QStringLiteral("gb"), QStringLiteral("English (UK)")},
        {QStringLiteral("de"), QStringLiteral("German")},
        {QStringLiteral("fr"), QStringLiteral("French")},
        {QStringLiteral("es"), QStringLiteral("Spanish")},
        {QStringLiteral("it"), QStringLiteral("Italian")},
        {QStringLiteral("pt"), QStringLiteral("Portuguese")},
        {QStringLiteral("ru"), QStringLiteral("Russian")},
        {QStringLiteral("ua"), QStringLiteral("Ukrainian")},
        {QStringLiteral("pl"), QStringLiteral("Polish")},
        {QStringLiteral("cz"), QStringLiteral("Czech")},
        {QStringLiteral("se"), QStringLiteral("Swedish")},
        {QStringLiteral("no"), QStringLiteral("Norwegian")},
        {QStringLiteral("dk"), QStringLiteral("Danish")},
        {QStringLiteral("fi"), QStringLiteral("Finnish")},
        {QStringLiteral("nl"), QStringLiteral("Dutch")},
        {QStringLiteral("be"), QStringLiteral("Belgian")},
        {QStringLiteral("ch"), QStringLiteral("Swiss")},
        {QStringLiteral("at"), QStringLiteral("Austrian")},
        {QStringLiteral("ca"), QStringLiteral("Canadian")},
        {QStringLiteral("br"), QStringLiteral("Brazilian")},
        {QStringLiteral("jp"), QStringLiteral("Japanese")},
        {QStringLiteral("cn"), QStringLiteral("Chinese")},
        {QStringLiteral("kr"), QStringLiteral("Korean")},
        {QStringLiteral("in"), QStringLiteral("Indian")},
        {QStringLiteral("tr"), QStringLiteral("Turkish")},
        {QStringLiteral("gr"), QStringLiteral("Greek")},
        {QStringLiteral("hu"), QStringLiteral("Hungarian")},
        {QStringLiteral("ro"), QStringLiteral("Romanian")},
    };
}

QString systemKeyboardLayout()
{
    return QStringLiteral("us");
}

QStringList availableTimezones()
{
    QStringList out;
#if QT_CONFIG(timezone)
    for (const QByteArray &id : QTimeZone::availableTimeZoneIds())
        out << QString::fromLatin1(id);
#else
    // Qt for WebAssembly is built without the timezone backend (QT_CONFIG
    // disables it, so the IANA ID APIs do not exist there at all), and that
    // build only renders the wizard in a browser (wasm-kde.yml). Offer a
    // short curated list there; every desktop build uses the real database
    // above.
    out << QStringLiteral("UTC")
        << QStringLiteral("America/New_York")
        << QStringLiteral("America/Chicago")
        << QStringLiteral("America/Denver")
        << QStringLiteral("America/Los_Angeles")
        << QStringLiteral("America/Anchorage")
        << QStringLiteral("Pacific/Honolulu")
        << QStringLiteral("America/Sao_Paulo")
        << QStringLiteral("Europe/London")
        << QStringLiteral("Europe/Berlin")
        << QStringLiteral("Europe/Paris")
        << QStringLiteral("Europe/Moscow")
        << QStringLiteral("Africa/Cairo")
        << QStringLiteral("Asia/Dubai")
        << QStringLiteral("Asia/Karachi")
        << QStringLiteral("Asia/Kolkata")
        << QStringLiteral("Asia/Singapore")
        << QStringLiteral("Asia/Tokyo")
        << QStringLiteral("Australia/Sydney")
        << QStringLiteral("Pacific/Auckland");
#endif
    out.sort();
    return out;
}

QString systemTimezone()
{
#if QT_CONFIG(timezone)
    const QByteArray id = QTimeZone::systemTimeZoneId();
    return id.isEmpty() ? QStringLiteral("UTC") : QString::fromLatin1(id);
#else
    return QStringLiteral("UTC");
#endif
}

QString timezoneDisplay(const QString &ianaId)
{
    QString display = ianaId;
    display.replace(QLatin1Char('_'), QLatin1Char(' '));
    const int slash = display.lastIndexOf(QLatin1Char('/'));
    if (slash >= 0)
        display = display.mid(slash + 1) + QStringLiteral(" (") + display.left(slash) + QLatin1Char(')');
    return display;
}

bool hostReachable(const char *host, int port, int timeoutMs)
{
    addrinfo hints{};
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_family = AF_UNSPEC;
    addrinfo *list = nullptr;
    if (getaddrinfo(host, nullptr, &hints, &list) != 0 || !list)
        return false;
    bool ok = false;
    for (addrinfo *ai = list; ai && !ok; ai = ai->ai_next) {
        if (ai->ai_family == AF_INET)
            reinterpret_cast<sockaddr_in *>(ai->ai_addr)->sin_port = htons(port);
        else if (ai->ai_family == AF_INET6)
            reinterpret_cast<sockaddr_in6 *>(ai->ai_addr)->sin6_port = htons(port);
        else
            continue;
        const int fd = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (fd < 0)
            continue;
        const int flags = fcntl(fd, F_GETFL, 0);
        fcntl(fd, F_SETFL, flags | O_NONBLOCK);
        int rc = connect(fd, ai->ai_addr, ai->ai_addrlen);
        if (rc == 0) {
            ok = true;
        } else if (errno == EINPROGRESS) {
            fd_set wfds;
            FD_ZERO(&wfds);
            FD_SET(fd, &wfds);
            timeval tv{};
            tv.tv_sec = timeoutMs / 1000;
            tv.tv_usec = (timeoutMs % 1000) * 1000;
            if (select(fd + 1, nullptr, &wfds, nullptr, &tv) > 0) {
                int err = 0;
                socklen_t len = sizeof(err);
                if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) == 0 && err == 0)
                    ok = true;
            }
        }
        close(fd);
    }
    freeaddrinfo(list);
    return ok;
}

QList<Target> connectivityTargets(const QString &registryHost)
{
    QList<Target> targets;
    if (!registryHost.isEmpty())
        targets << Target{registryHost, 443};
    for (const Target &shared : {Target{QStringLiteral("ghcr.io"), 443}, Target{QStringLiteral("8.8.8.8"), 53}}) {
        if (!targets.contains(shared))
            targets << shared;
    }
    return targets;
}

bool networkReachable(const QList<Target> &targets)
{
    for (const Target &t : targets) {
        if (hostReachable(t.host.toUtf8().constData(), t.port, 3000))
            return true;
    }
    return false;
}

QStringList networkSettingsCommand()
{
    return {QStringLiteral("sh"), QStringLiteral("-c"),
            QStringLiteral("kcmshell6 kcm_networkmanagement || systemsettings kcm_networkmanagement"
                           " || nm-connection-editor")};
}

} // namespace region
