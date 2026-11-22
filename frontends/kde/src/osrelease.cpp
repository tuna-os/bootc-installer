#include "osrelease.h"

#include "branding.h"

#include <QCoreApplication>
#include <QFile>

namespace osrelease
{

QString readText()
{
    const QString override = qEnvironmentVariable(FILE_ENV);
    if (!override.isEmpty()) {
        QFile file(override);
        if (file.open(QIODevice::ReadOnly))
            return QString::fromUtf8(file.readAll());
        return {};
    }
    // The same search branding::resolve() uses (host first in a Flatpak).
    // branding.h owns no path list, so the files are asked one by one.
    for (const QString &path :
         {QStringLiteral("/run/host/etc/os-release"), QStringLiteral("/run/host/usr/lib/os-release"),
          QStringLiteral("/etc/os-release"), QStringLiteral("/usr/lib/os-release")}) {
        QFile file(path);
        if (file.open(QIODevice::ReadOnly))
            return QString::fromUtf8(file.readAll());
    }
    return {};
}

QHash<QString, QString> read()
{
    return branding::parseOsRelease(readText());
}

bool isPrerelease(const QHash<QString, QString> &osRelease)
{
    const QString type = osRelease.value(QStringLiteral("RELEASE_TYPE")).toLower();
    if (type == QLatin1String("pre-release") || type == QLatin1String("experiment"))
        return true;
    // gnome-setup's test hooks: an override of either key wins over the file.
    const QString overrideType = qEnvironmentVariable("SETUP_OVERRIDE_OS_RELEASE_TYPE").toLower();
    return overrideType == QLatin1String("pre-release") || overrideType == QLatin1String("experiment");
}

QString experimentText(const QHash<QString, QString> &osRelease)
{
    const QString override = qEnvironmentVariable("SETUP_OVERRIDE_OS_EXPERIMENT");
    if (!override.isEmpty())
        return override;
    return osRelease.value(QStringLiteral("EXPERIMENT"));
}

} // namespace osrelease
