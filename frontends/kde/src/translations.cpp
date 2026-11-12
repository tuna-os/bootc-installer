#include "translations.h"

#include <QStandardPaths>
#include <QTranslator>

using namespace Qt::StringLiterals;

namespace translations {

QString domain()
{
    return u"tuna-installer-kde"_s;
}

QStringList directories()
{
    return QStandardPaths::locateAll(QStandardPaths::GenericDataLocation,
                                     u"tuna-installer-kde/translations"_s,
                                     QStandardPaths::LocateDirectory);
}

bool load(QTranslator &translator, const QLocale &locale, const QStringList &dirs)
{
    for (const QString &dir : dirs) {
        if (translator.load(locale, domain(), u"_"_s, dir))
            return true;
    }
    return false;
}

} // namespace translations
