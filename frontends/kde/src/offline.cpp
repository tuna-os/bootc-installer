#include "offline.h"

#include <QFile>
#if QT_CONFIG(process)
#include <QProcess>
#endif
#ifdef Q_OS_UNIX
#include <unistd.h>
#endif

namespace offline {

bool inFlatpak()
{
    return QFile::exists(QStringLiteral("/.flatpak-info"));
}

#if QT_CONFIG(process)
void startInOwnProcessGroup(QProcess &process)
{
#ifdef Q_OS_UNIX
    // The wrapper is the only process of the install this user can signal.
    // The shared contract is "kill your wrapper's process group", which
    // must never be the installer's own group.
    process.setChildProcessModifier([] { ::setpgid(0, 0); });
#else
    Q_UNUSED(process);
#endif
}
#endif

QStringList hostCommand(const QStringList &argv)
{
    if (!inFlatpak())
        return argv;
    QStringList wrapped{QStringLiteral("flatpak-spawn"), QStringLiteral("--host")};
    wrapped += argv;
    return wrapped;
}

} // namespace offline
