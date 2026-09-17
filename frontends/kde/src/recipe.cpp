#include "recipe.h"
#include <QJsonArray>
#include <QJsonDocument>

QJsonObject Recipe::toJson() const
{
    QJsonObject obj;
    obj["disk"] = disk;
    obj["filesystem"] = filesystem;
    obj["btrfsSubvolumes"] = btrfsSubvolumes;
    QJsonObject enc;
    enc["type"] = encryption.type;
    if (!encryption.passphrase.isEmpty())
        enc["passphrase"] = encryption.passphrase;
    obj["encryption"] = enc;
    if (!liveMode || !image.isEmpty())
        obj["image"] = image;
    if (!targetImgref.isEmpty())
        obj["targetImgref"] = targetImgref;
    if (!bootloader.isEmpty())
        obj["bootloader"] = bootloader;
    if (composeFsBackend)
        obj["composeFsBackend"] = true;
    if (!flatpaks.isEmpty())
        obj["flatpaks"] = QJsonArray::fromStringList(flatpaks);
    if (!additionalImageStores.isEmpty())
        obj["additionalImageStores"] = QJsonArray::fromStringList(additionalImageStores);
    obj["distroID"] = distroID;
    obj["selinuxDisabled"] = selinuxDisabled;
    obj["hostname"] = hostname;
    return obj;
}

Recipe Recipe::fromJson(const QJsonObject &obj)
{
    Recipe r;
    r.disk = obj["disk"].toString();
    r.filesystem = obj["filesystem"].toString("xfs");
    r.btrfsSubvolumes = obj["btrfsSubvolumes"].toBool(false);
    auto enc = obj["encryption"].toObject();
    r.encryption.type = enc["type"].toString("none");
    r.encryption.passphrase = enc["passphrase"].toString();
    r.image = obj["image"].toString();
    r.targetImgref = obj["targetImgref"].toString();
    r.bootloader = obj["bootloader"].toString();
    r.composeFsBackend = obj["composeFsBackend"].toBool(false);
    for (const auto &val : obj["flatpaks"].toArray()) {
        r.flatpaks.append(val.toString());
    }
    for (const auto &val : obj["additionalImageStores"].toArray()) {
        r.additionalImageStores.append(val.toString());
    }
    r.distroID = obj["distroID"].toString("tunaos");
    r.selinuxDisabled = obj["selinuxDisabled"].toBool(true);
    r.hostname = obj["hostname"].toString("tunaos");
    return r;
}

bool Recipe::isValid() const
{
    return validationError().isEmpty();
}

QString Recipe::validationError() const
{
    if (disk.isEmpty())
        return QStringLiteral("No disk selected");
    if (image.isEmpty() && !liveMode)
        return QStringLiteral("No OS image specified");
    if (hostname.isEmpty())
        return QStringLiteral("Hostname is required");
    static const QStringList kEncTypes = {
        QStringLiteral("none"), QStringLiteral("luks-passphrase"),
        QStringLiteral("tpm2-luks"), QStringLiteral("tpm2-luks-passphrase")};
    if (!kEncTypes.contains(encryption.type))
        return QStringLiteral("Unknown encryption type: %1").arg(encryption.type);
    if (encryption.type.endsWith(QLatin1String("passphrase")) && encryption.passphrase.isEmpty())
        return QStringLiteral("Encryption passphrase is required");
    return {};
}
