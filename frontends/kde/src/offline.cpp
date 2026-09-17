#include "offline.h"
#include "log.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QProcessEnvironment>

namespace offline {

bool inFlatpak()
{
    return QFile::exists(QStringLiteral("/.flatpak-info"));
}

QStringList fishermanCommand()
{
    // Flatpak runtimes ship no pkexec; escalate host-side. The live ISO
    // symlinks the flatpak-bundled fisherman to /usr/local/bin and installs
    // the polkit policy for it (tunaOS customize-live.sh).
    if (inFlatpak())
        return {QStringLiteral("flatpak-spawn"), QStringLiteral("--host"),
                QStringLiteral("pkexec"), QStringLiteral("/usr/local/bin/fisherman")};
    return {QStringLiteral("sudo"), QStringLiteral("/usr/local/bin/fisherman")};
}

QStringList hostCommand(const QStringList &argv)
{
    if (!inFlatpak())
        return argv;
    QStringList wrapped{QStringLiteral("flatpak-spawn"), QStringLiteral("--host")};
    wrapped += argv;
    return wrapped;
}

// Every caller treats an empty return as "nothing there": no live image, no
// offline stores. A helper that was missing, denied by the sandbox, or hung
// produced exactly the same empty string as a helper that ran fine and had
// nothing to report — so an install that quietly lost live-ISO mode looked
// identical to one that never had it. The result is still empty (callers all
// have a sane no-data path); it is now said out loud.
static QString runHost(const QStringList &argv, int timeoutMs = 10000)
{
    const QStringList cmd = hostCommand(argv);
    QProcess p;
    p.start(cmd.first(), cmd.mid(1));

    if (!p.waitForFinished(timeoutMs)) {
        qCWarning(logInstaller) << "helper did not finish within" << timeoutMs
                                << "ms, treating its output as empty:" << cmd;
        // waitForFinished timing out leaves the child running; do not hand a
        // stray process to the destructor.
        p.kill();
        p.waitForFinished(1000);
        return {};
    }

    if (p.exitStatus() != QProcess::NormalExit || p.exitCode() != 0) {
        qCWarning(logInstaller) << "helper failed, treating its output as empty:" << cmd
                                << (p.exitStatus() == QProcess::CrashExit
                                        ? "crashed, exit"
                                        : "exit")
                                << p.exitCode()
                                << "stderr" << QString::fromUtf8(p.readAllStandardError()).trimmed();
        return {};
    }

    return QString::fromUtf8(p.readAllStandardOutput());
}

QString liveIsoImage()
{
    const QString out = runHost({QStringLiteral("bootc"), QStringLiteral("status"),
                                 QStringLiteral("--json")});
    if (out.isEmpty())
        return {};
    const QJsonObject status = QJsonDocument::fromJson(out.toUtf8()).object();
    const QString ref = status[QLatin1String("status")].toObject()
                              [QLatin1String("booted")].toObject()
                              [QLatin1String("image")].toObject()
                              [QLatin1String("image")].toObject()
                              [QLatin1String("image")].toString();
    if (ref.isEmpty())
        return {};

    bool live = QFile::exists(QStringLiteral("/run/ostree-live"));
    QFile cmdline(QStringLiteral("/proc/cmdline"));
    if (!live && cmdline.open(QIODevice::ReadOnly))
        live = QString::fromUtf8(cmdline.readAll()).contains(QLatin1String("rd.live.image"));
    return live ? ref : QString();
}

QStringList offlineStores()
{
    QStringList stores;
    const QString env = QProcessEnvironment::systemEnvironment()
                            .value(QStringLiteral("TUNA_OFFLINE_STORES"));
    if (!env.isEmpty())
        stores += env.split(QLatin1Char(':'), Qt::SkipEmptyParts);

    QFile listFile(QStringLiteral("/etc/tuna-installer/offline-stores"));
    if (listFile.open(QIODevice::ReadOnly)) {
        const QStringList lines = QString::fromUtf8(listFile.readAll())
                                      .split(QLatin1Char('\n'), Qt::SkipEmptyParts);
        for (const QString &line : lines) {
            const QString t = line.trimmed();
            if (!t.isEmpty() && !t.startsWith(QLatin1Char('#')))
                stores << t;
        }
    }
    stores << QStringLiteral("/usr/share/tuna-installer/oci-store");

    QStringList existing;
    for (const QString &s : std::as_const(stores))
        if (!existing.contains(s) && QDir(s).exists())
            existing << s;
    return existing;
}

QSet<QString> offlineImages(const QStringList &stores)
{
    QSet<QString> refs;
    for (const QString &store : stores) {
        const QString out = runHost({QStringLiteral("podman"), QStringLiteral("images"),
                                     QStringLiteral("--root"), store,
                                     QStringLiteral("--format"), QStringLiteral("json")},
                                    30000);
        const QJsonArray imgs = QJsonDocument::fromJson(out.toUtf8()).array();
        for (const QJsonValue &img : imgs) {
            const QJsonArray names = img.toObject()[QLatin1String("Names")].toArray();
            for (const QJsonValue &n : names)
                refs.insert(n.toString());
        }
    }
    return refs;
}

} // namespace offline
