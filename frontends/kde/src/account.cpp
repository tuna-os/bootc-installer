#include "account.h"

#include "account_groups.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

namespace account {

QByteArray groupsJson()
{
    return QByteArray(kAccountGroupsJson);
}

QStringList defaultGroups()
{
    QStringList out;
    const QJsonArray list = QJsonDocument::fromJson(groupsJson()).object()
                                .value(QLatin1String("default_groups")).toArray();
    for (const QJsonValue &v : list)
        out << v.toString();
    return out;
}

QStringList groups(const QByteArray &operatorRecipe)
{
    if (operatorRecipe.isNull())
        return defaultGroups();
    const QJsonValue value = QJsonDocument::fromJson(operatorRecipe).object()
                                 .value(QLatin1String("user")).toObject()
                                 .value(QLatin1String("groups"));
    if (!value.isArray())
        return defaultGroups();
    QStringList out;
    for (const QJsonValue &v : value.toArray()) {
        if (!v.isString())
            return defaultGroups();
        out << v.toString();
    }
    return out;
}

QString operatorRecipePath(bool flatpak)
{
    return (flatpak ? QStringLiteral("/run/host/etc") : QStringLiteral("/etc"))
        + QStringLiteral("/bootc-installer/recipe.json");
}

QByteArray readOperatorRecipe(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return {};
    const QByteArray data = f.readAll();
    // An empty file is a file that does not parse, not "no file".
    return data.isNull() ? QByteArray("") : data;
}

} // namespace account
