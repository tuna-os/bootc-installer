#pragma once

// The image catalog: which OS images the disk step offers, and what each
// choice implies for the rest of the wizard.
//
// The contract is shared/catalog/README.md at the monorepo root, and the
// five frontends read one fixture to one set of answers
// (shared/catalog/fixtures; test_backend's catalogContract* tests). In
// short: a tree of groups and leaves, each per-image field taken from the
// nearest node that sets it; a leaf is `imgref`, or `tag` with a `registry`
// in scope; `flatpaks` is a list, or an `@alias` that names a list, and
// anything else leaves the recipe key out; `needs_user_creation` is TRUE
// when no node sets it.

#include <QByteArray>
#include <QJsonObject>
#include <QList>
#include <QString>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>

namespace imagecatalog
{

// Test seam: a file holding an images.json manifest. When set, no search
// path is read. The E2E driver and the capture harness use it.
inline constexpr const char *IMAGES_ENV = "FISHERMAN_IMAGES_PATH";

// One selectable image: a leaf of the manifest tree with every inherited
// field resolved.
struct Leaf {
    QString name;              // the leaf's own `name` ("Stable")
    QString imgref;            // full OCI reference, tag+registry already composed
    QString nvidiaImgref;      // the NVIDIA build of the same image, or ""
    QString desc;              // the leaf's `desc`, may be empty
    QString searchText;        // lowercased "group names + name + desc + imgref" for filtering
    QString icon;              // inherited `icon` spec, may be empty
    // Row labels (shared/catalog/README.md, "Row labels").
    QString product;           // name of the nearest registry-owning node
    QString channel;           // a tag leaf's name, "" for an imgref leaf
    QString label;             // "product channel": the confirm page
    QString breadcrumb;        // every name from the root: the flat list
    // `flatpaks` resolved offline. hasFlatpaks is false for a URL, an alias
    // that names none or no value: the recipe then has no `flatpaks` key and
    // fisherman applies its own default. An empty list with hasFlatpaks is
    // "copy no Flatpak".
    bool hasFlatpaks = false;
    QStringList flatpaks;
    bool needsUserCreation = true;
    bool composefs = false;
    QString imageType = QStringLiteral("bootc");
    QString bootloader;        // "grub2", "systemd", or ""
    QString filesystem;        // selected before the user picks; "" = our default
    QStringList filesystems;   // what the user may pick; empty = our own list
    QString flatpakVarPath;    // override for the writable var path, or ""
    QString defaultHostname;   // suggested hostname, or ""
    // `extras` of the nearest node that has the object: the desktop steps
    // fisherman does after the install ("Desktop extras" of the contract).
    // hasExtras is false when no node has one: the recipe then has no
    // `extras` key and fisherman looks the image up itself. With it, extras
    // holds the four switches, each true or false.
    bool hasExtras = false;
    QJsonObject extras;
    QVariantList carousel; // the leaf's `carousel` slides, as QVariantMaps
};

struct Catalog {
    bool valid = false;        // a JSON object with an `images` list
    QString defaultImage;
    QList<Leaf> leaves;

    // The leaf for a reference, or nullptr.
    const Leaf *find(const QString &imgref) const;
    // Index of the leaf selected at start: the branding's default_image,
    // then the catalog's, else -1 (nothing is selected; the user chooses).
    int defaultIndex(const QString &brandingDefaultImage) const;
    // Whether an install of `imgref` creates the first account. An image
    // the catalog does not have: true.
    bool needsUserCreation(const QString &imgref) const;
};

// What a leaf puts into the recipe's `image` and `targetImgref` on this
// machine (shared/catalog/README.md, "Image and NVIDIA image").
struct ImageChoice {
    QString image;
    QString targetImgref;
};
ImageChoice sourceAndTarget(const Leaf &leaf, bool hasNvidia, bool isLive,
                            const QStringList &offlineImages);

// The leaf "install this system" applies on live media: the catalog's leaf
// for the running image (or none), with the layout the ISO builder probed
// from that image written over it. The operator recipe's (<etc>/bootc-
// installer/recipe.json, account::readOperatorRecipe) `bootloader`,
// `composeFsBackend` and `filesystem` win when set, as in the GNOME
// frontend (bootc_installer/utils/processor.py); a key that is missing,
// empty or of another type leaves the leaf's value. fisherman does not find
// the backend from the image, so without them a composefs-native image goes
// down bootc's ostree path (tuna-os/tunaOS#4485, XFCE #343). A `filesystem`
// is the one choice, as for a leaf that names one.
Leaf liveLeaf(const Leaf *catalogLeaf, const QByteArray &operatorRecipe);

// True when a PCI display device of vendor 0x10de is below
// `<sysRoot>/bus/pci/devices`. The probe does not report the GPU yet.
bool hasNvidiaGpu(const QString &sysRoot = QStringLiteral("/sys"));

// The registry host of an image reference ("ghcr.io" of
// "ghcr.io/owner/image:tag"), or "" when the reference names none.
QString registryHost(const QString &imgref);

// Where load() looks, in order (shared/catalog/README.md): the system
// file, its legacy name, the user's file, then the packaged catalog. `etc`
// is /run/host/etc in a Flatpak. The packaged catalog is fisherman's
// images.json, at /app/share in the Flatpak and /usr/share natively.
QStringList searchPaths(bool flatpak, const QString &xdgConfigHome);
QStringList defaultSearchPaths(bool flatpak);

// Parses one manifest document. Pure: no filesystem, no environment.
Catalog parse(const QByteArray &json);

// Loads the catalog: IMAGES_ENV alone when set, else the first of
// defaultSearchPaths() that is a catalog. A file that is missing or that
// does not parse does not stop the search. No catalog at all is an empty
// one, not an error: live media and branding-default installs go on.
Catalog load();
// The same, over an explicit list (tests).
Catalog loadFirst(const QStringList &paths);

} // namespace imagecatalog
