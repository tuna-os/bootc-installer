#include "tpm.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>

namespace tpm {

bool probe2(const QString &root)
{
    QFile version(QDir(root).filePath(QString::fromLatin1(VERSION_FILE)));
    if (version.open(QIODevice::ReadOnly | QIODevice::Text)) {
        return QString::fromUtf8(version.readAll()).trimmed() == QLatin1String("2");
    }
    return QFileInfo::exists(QDir(root).filePath(QString::fromLatin1(RESOURCE_MANAGER)));
}

}
