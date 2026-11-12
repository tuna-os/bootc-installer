#include "imagecatalog.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QProcessEnvironment>
#include <QStandardPaths>
#include <QVariant>

namespace imagecatalog
{

namespace
{

// The contract's fallback product name for a leaf with no name anywhere:
// the last path component of the reference, "atlas-dx" -> "Atlas DX".
QString prettyFromImgref(const QString &imgref)
{
    QString slug = imgref.section(QLatin1Char('/'), -1);
    slug = slug.section(QLatin1Char('@'), 0, 0).section(QLatin1Char(':'), 0, 0);
    const QStringList parts =
        slug.replace(QLatin1Char('_'), QLatin1Char('-')).split(QLatin1Char('-'), Qt::SkipEmptyParts);
    if (parts.isEmpty())
        return imgref;
    QStringList words;
    for (int i = 0; i < parts.size(); ++i) {
        words << (i == 0 ? parts.at(i).left(1).toUpper() + parts.at(i).mid(1).toLower()
                         : parts.at(i).toUpper());
    }
    return words.join(QLatin1Char(' '));
}

// What a group hands to its children: each per-image field of the contract
// table, under the manifest's own names, plus the page-only icon and slides.
struct Context {
    QJsonValue flatpaks{QJsonValue::Undefined}; // as written: a list, "@alias", a URL
    QVariantList carousel;
    QString icon;
    bool needsUserCreation = true; // the contract's default (#288)
    bool composefs = false;
    QString imageType = QStringLiteral("bootc");
    QString bootloader;
    QString filesystem;
    QStringList filesystems;
    QString flatpakVarPath;
    QString nvidiaImgref;
    QString registry;
    QString defaultHostname;
    bool hasExtras = false;
    QJsonObject extras;
};

// The four switches of an `extras` object, or false when the value is not
// an object or a switch is not a boolean. Only these keys are copied:
// fisherman refuses a recipe key that it does not know. A switch that the
// object leaves out is off.
bool resolveExtras(const QJsonValue &value, QJsonObject &out)
{
    if (!value.isObject())
        return false;
    const QJsonObject object = value.toObject();
    QJsonObject extras;
    for (const char *key : {"printServices", "oemSetup", "audioNames", "bootSplash"}) {
        const QJsonValue v = object.value(QLatin1String(key));
        if (!v.isUndefined() && !v.isBool())
            return false;
        extras.insert(QLatin1String(key), v.toBool(false));
    }
    out = extras;
    return true;
}

// A value of false, "" or [] is a value and stops the search; null is not.
bool sets(const QJsonObject &node, const char *key)
{
    const auto it = node.constFind(QLatin1String(key));
    return it != node.constEnd() && !it->isNull();
}

// `flatpaks` as the recipe may carry it, or false: a list is the list, an
// `@name` whose alias is a list is that list. A URL, an alias that names a
// URL or nothing, and no value cannot be read offline. A frontend never
// downloads a list and never sends `fallback_flatpaks`.
bool resolveFlatpaks(QJsonValue value, const QJsonObject &aliases, QStringList &out)
{
    if (value.isString() && value.toString().startsWith(QLatin1Char('@')))
        value = aliases.value(value.toString().mid(1));
    if (!value.isArray())
        return false;
    QStringList list;
    for (const QJsonValue &v : value.toArray()) {
        if (!v.isString())
            return false;
        list << v.toString();
    }
    out = list;
    return true;
}

void collectLeaves(const QJsonObject &node, const QStringList &path, const Context &ctx,
                   const QString &product, const QString &searchCtx, const QJsonObject &aliases,
                   QList<Leaf> &out)
{
    Context child = ctx;
    if (sets(node, "carousel")) {
        child.carousel.clear();
        for (const QJsonValue &v : node.value(QLatin1String("carousel")).toArray()) {
            if (v.isObject())
                child.carousel << QVariant(v.toObject().toVariantMap());
        }
    }
    if (sets(node, "flatpaks"))
        child.flatpaks = node.value(QLatin1String("flatpaks"));
    if (sets(node, "icon"))
        child.icon = node.value(QLatin1String("icon")).toString();
    if (sets(node, "needs_user_creation"))
        child.needsUserCreation = node.value(QLatin1String("needs_user_creation")).toBool(true);
    if (sets(node, "composefs"))
        child.composefs = node.value(QLatin1String("composefs")).toBool(false);
    if (sets(node, "image_type"))
        child.imageType = node.value(QLatin1String("image_type")).toString();
    if (sets(node, "bootloader"))
        child.bootloader = node.value(QLatin1String("bootloader")).toString();
    if (sets(node, "filesystem"))
        child.filesystem = node.value(QLatin1String("filesystem")).toString();
    if (sets(node, "filesystems")) {
        child.filesystems.clear();
        for (const QJsonValue &v : node.value(QLatin1String("filesystems")).toArray())
            child.filesystems << v.toString();
    }
    if (sets(node, "flatpak_var_path"))
        child.flatpakVarPath = node.value(QLatin1String("flatpak_var_path")).toString();
    if (sets(node, "nvidia_imgref"))
        child.nvidiaImgref = node.value(QLatin1String("nvidia_imgref")).toString();
    if (sets(node, "registry"))
        child.registry = node.value(QLatin1String("registry")).toString();
    if (sets(node, "default_hostname"))
        child.defaultHostname = node.value(QLatin1String("default_hostname")).toString();
    // The nearest object replaces the parent's whole: the two are not merged.
    if (sets(node, "extras")) {
        child.extras = QJsonObject();
        child.hasExtras = resolveExtras(node.value(QLatin1String("extras")), child.extras);
    }

    const QString name = node.value(QLatin1String("name")).toString().trimmed();
    QStringList here = path;
    if (!name.isEmpty())
        here << name;
    // The product is the name of the nearest node that sets `registry`.
    const bool ownsRegistry = !node.value(QLatin1String("registry")).toString().isEmpty();
    const QString nodeProduct = ownsRegistry ? name : product;

    const QString own = node.value(QLatin1String("imgref")).toString();
    const bool tagLeaf = node.contains(QLatin1String("tag")) && !child.registry.isEmpty();
    // A node with a reference is a leaf, even with children.
    if (!own.isEmpty() || tagLeaf) {
        Leaf leaf;
        leaf.name = name;
        if (!own.isEmpty()) {
            leaf.imgref = own;
            leaf.product = name.isEmpty() ? prettyFromImgref(own) : name;
        } else {
            leaf.imgref = child.registry + QLatin1Char(':') + node.value(QLatin1String("tag")).toString();
            leaf.channel = ownsRegistry ? QString() : name;
            leaf.product = nodeProduct.isEmpty() ? prettyFromImgref(leaf.imgref) : nodeProduct;
        }
        leaf.label = (leaf.product + QLatin1Char(' ') + leaf.channel).trimmed();
        leaf.breadcrumb = here.join(QStringLiteral(" › "));
        leaf.nvidiaImgref = child.nvidiaImgref;
        leaf.desc = node.value(QLatin1String("desc")).toString();
        leaf.searchText = (searchCtx + QLatin1Char(' ') + name + QLatin1Char(' ') + leaf.desc
                           + QLatin1Char(' ') + leaf.imgref).toLower();
        leaf.icon = child.icon;
        leaf.hasFlatpaks = resolveFlatpaks(child.flatpaks, aliases, leaf.flatpaks);
        leaf.needsUserCreation = child.needsUserCreation;
        leaf.composefs = child.composefs;
        leaf.imageType = child.imageType;
        leaf.bootloader = child.bootloader;
        // The choices are `filesystems`, else the one `filesystem`. The
        // selected value is `filesystem`, else the first choice.
        leaf.filesystems = child.filesystems;
        if (leaf.filesystems.isEmpty() && !child.filesystem.isEmpty())
            leaf.filesystems << child.filesystem;
        leaf.filesystem = child.filesystem.isEmpty() ? child.filesystems.value(0) : child.filesystem;
        leaf.flatpakVarPath = child.flatpakVarPath;
        leaf.defaultHostname = child.defaultHostname;
        leaf.hasExtras = child.hasExtras;
        leaf.extras = child.extras;
        leaf.carousel = child.carousel;
        out << leaf;
        return;
    }

    QString childSearch = searchCtx + QLatin1Char(' ') + name;
    const QString extra = node.value(QLatin1String("search_extra")).toString();
    if (!extra.isEmpty())
        childSearch += QLatin1Char(' ') + extra;
    for (const QJsonValue &v : node.value(QLatin1String("children")).toArray()) {
        if (v.isObject())
            collectLeaves(v.toObject(), here, child, nodeProduct, childSearch, aliases, out);
    }
}

QString xdgConfigHome(const QProcessEnvironment &env)
{
    const QString xdg = env.value(QStringLiteral("XDG_CONFIG_HOME"));
    if (!xdg.isEmpty())
        return xdg;
    return QStandardPaths::writableLocation(QStandardPaths::HomeLocation) + QStringLiteral("/.config");
}

} // namespace

const Leaf *Catalog::find(const QString &imgref) const
{
    if (imgref.isEmpty())
        return nullptr;
    for (const Leaf &leaf : leaves) {
        if (leaf.imgref == imgref)
            return &leaf;
    }
    // The NVIDIA image of a leaf is that leaf: live media that holds only
    // the NVIDIA image boots it, and its account flag and layout are the
    // leaf's (shared/catalog/README.md, "The account").
    for (const Leaf &leaf : leaves) {
        if (!leaf.nvidiaImgref.isEmpty() && leaf.nvidiaImgref == imgref)
            return &leaf;
    }
    return nullptr;
}

int Catalog::defaultIndex(const QString &brandingDefaultImage) const
{
    for (const QString &candidate : {brandingDefaultImage, defaultImage}) {
        if (candidate.isEmpty())
            continue;
        for (int i = 0; i < leaves.size(); ++i) {
            if (leaves.at(i).imgref == candidate)
                return i;
        }
    }
    return -1;
}

bool Catalog::needsUserCreation(const QString &imgref) const
{
    const Leaf *leaf = find(imgref);
    return leaf ? leaf->needsUserCreation : true;
}

ImageChoice sourceAndTarget(const Leaf &leaf, bool hasNvidia, bool isLive,
                            const QStringList &offlineImages)
{
    const QString &base = leaf.imgref;
    const QString &nvidia = leaf.nvidiaImgref;
    if (nvidia.isEmpty())
        return {base, base};
    if (hasNvidia)
        return {nvidia, nvidia};
    // The ISO that holds only the NVIDIA image: install it offline and let
    // the first update move the system to the base image. Off live media
    // this would download the larger image for no gain (#314).
    if (isLive && offlineImages.contains(nvidia) && !offlineImages.contains(base))
        return {nvidia, base};
    return {base, base};
}

Leaf liveLeaf(const Leaf *catalogLeaf, const QByteArray &operatorRecipe)
{
    Leaf leaf = catalogLeaf ? *catalogLeaf : Leaf{};
    const QJsonObject recipe = QJsonDocument::fromJson(operatorRecipe).object();
    const QJsonValue bootloader = recipe.value(QLatin1String("bootloader"));
    if (bootloader.isString() && !bootloader.toString().isEmpty())
        leaf.bootloader = bootloader.toString();
    const QJsonValue composefs = recipe.value(QLatin1String("composeFsBackend"));
    if (composefs.isBool())
        leaf.composefs = composefs.toBool();
    const QJsonValue filesystem = recipe.value(QLatin1String("filesystem"));
    if (filesystem.isString() && !filesystem.toString().isEmpty()) {
        leaf.filesystem = filesystem.toString();
        leaf.filesystems = {leaf.filesystem};
    }
    return leaf;
}

bool hasNvidiaGpu(const QString &sysRoot)
{
    return hasNvidiaGpuInDevices(sysRoot + QStringLiteral("/bus/pci/devices"));
}

bool hasNvidiaGpuInDevices(const QString &pciDevices)
{
    const QDir devices(pciDevices);
    const auto read = [](const QString &path) {
        QFile f(path);
        return f.open(QIODevice::ReadOnly) ? QString::fromLatin1(f.readAll()).trimmed().toLower()
                                           : QString();
    };
    for (const QString &entry : devices.entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
        const QString dir = devices.filePath(entry);
        // PCI base class 0x03 is a display controller.
        if (read(dir + QStringLiteral("/vendor")) == QLatin1String("0x10de")
            && read(dir + QStringLiteral("/class")).startsWith(QLatin1String("0x03")))
            return true;
    }
    return false;
}

QStringList searchPaths(bool flatpak, const QString &xdgConfigHome, const QString &override)
{
    // The system file is first: an ISO that ships a catalog must get that
    // catalog, and a file in a home directory must not replace it. In a
    // Flatpak the runtime's /etc is not the host's.
    const QString etc = flatpak ? QStringLiteral("/run/host/etc") : QStringLiteral("/etc");
    QString xdg = xdgConfigHome;
    while (xdg.size() > 1 && xdg.endsWith(QLatin1Char('/')))
        xdg.chop(1);
    QStringList paths;
    if (!override.isEmpty())
        paths << override;
    paths << etc + QStringLiteral("/bootc-installer/images.json")
          << etc + QStringLiteral("/tuna-installer/images.json")
          << xdg + QStringLiteral("/bootc-installer/images.json")
          << (flatpak ? QStringLiteral("/app/share/fisherman/data/images.json")
                      : QStringLiteral("/usr/share/fisherman/data/images.json"));
    return paths;
}

QStringList defaultSearchPaths(bool flatpak)
{
    const QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    return searchPaths(flatpak, xdgConfigHome(env), env.value(QString::fromLatin1(IMAGES_ENV)));
}

Catalog parse(const QByteArray &json)
{
    Catalog catalog;
    QJsonParseError err{};
    const QJsonDocument doc = QJsonDocument::fromJson(json, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject())
        return catalog;
    const QJsonObject root = doc.object();
    if (!root.value(QLatin1String("images")).isArray())
        return catalog;
    catalog.valid = true;
    const QJsonObject aliases = root.value(QLatin1String("aliases")).toObject();
    catalog.defaultImage = root.value(QLatin1String("default_image")).toString();
    const Context top;
    for (const QJsonValue &v : root.value(QLatin1String("images")).toArray()) {
        if (v.isObject())
            collectLeaves(v.toObject(), {}, top, QString(), QString(), aliases, catalog.leaves);
    }
    return catalog;
}

Catalog loadFirst(const QStringList &paths)
{
    for (const QString &path : paths) {
        QFile f(path);
        if (!f.open(QIODevice::ReadOnly))
            continue;
        const Catalog catalog = parse(f.readAll());
        if (catalog.valid)
            return catalog;
    }
    return Catalog{};
}

Catalog load()
{
    // Flatpak detection without fisherman.h: the sentinel file. imagecatalog
    // stays dependency-free so the tests link only QtCore-adjacent units.
    // The IMAGES_ENV file is first; a missing or broken one does not stop
    // the search (it used to: the override was the only file tried).
    return loadFirst(defaultSearchPaths(QFile::exists(QStringLiteral("/.flatpak-info"))));
}

} // namespace imagecatalog
