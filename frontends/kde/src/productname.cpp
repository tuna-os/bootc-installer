#include "productname.h"

#include <QByteArray>
#include <QFile>
#include <QStringList>

namespace product {

QString prettyNameFrom(const QString &osReleaseText)
{
    const QStringList lines = osReleaseText.split(QLatin1Char('\n'));
    for (const QString &raw : lines) {
        const QString line = raw.trimmed();
        if (!line.startsWith(QLatin1String("PRETTY_NAME=")))
            continue;
        QString value = line.mid(QLatin1String("PRETTY_NAME=").size()).trimmed();
        // os-release values are usually quoted; either quote style is legal.
        if (value.size() >= 2
            && ((value.startsWith(QLatin1Char('"')) && value.endsWith(QLatin1Char('"')))
                || (value.startsWith(QLatin1Char('\'')) && value.endsWith(QLatin1Char('\''))))) {
            value = value.mid(1, value.size() - 2);
        }
        value = value.trimmed();
        if (!value.isEmpty())
            return value;
    }
    return QString();
}

QString resolve()
{
    // Test/documentation override, same precedent as TUNA_INSTALLER_FAKE_LSBLK:
    // the screenshot harness renders the docs images with a neutral name, and
    // it is the only way to exercise a variant's branding on a machine that is
    // not running that variant.
    const QByteArray override = qgetenv("TUNA_INSTALLER_PRODUCT_NAME");
    if (!override.trimmed().isEmpty())
        return QString::fromUtf8(override).trimmed();

    // Host first. Inside the flatpak /etc/os-release describes the runtime, so
    // trusting it would brand every variant with the runtime's name.
    const QStringList candidates = {
        QStringLiteral("/run/host/etc/os-release"),
        QStringLiteral("/run/host/usr/lib/os-release"),
        QStringLiteral("/etc/os-release"),
        QStringLiteral("/usr/lib/os-release"),
    };
    for (const QString &path : candidates) {
        QFile f(path);
        if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
            continue;
        const QString name = prettyNameFrom(QString::fromUtf8(f.readAll()));
        if (!name.isEmpty())
            return name;
    }
    return QStringLiteral("TunaOS");
}

} // namespace product
