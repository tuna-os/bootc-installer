#ifndef RECIPE_H
#define RECIPE_H

#include "account.h"

#include <QJsonObject>
#include <QString>
#include <QStringList>

struct Recipe {
    QString disk;
    QString filesystem = "xfs";
    bool btrfsSubvolumes = false;
    struct {
        // One of encryptionTypes().
        QString type = "none";
        QString passphrase;
    } encryption;
    QString image; // may stay empty in live-ISO mode (bootc installs the running container)
    QString targetImgref;
    QString bootloader;        // "", "grub2", "systemd"
    bool composeFsBackend = false;
    // `flatpaks` has three states (shared/catalog/README.md): no key, and
    // fisherman applies its own default; an empty list, and it copies no
    // Flatpak; a list. flatpaksSet is what tells the first two apart.
    bool flatpaksSet = false;
    QStringList flatpaks;
    // The catalog's flatpak_var_path and image_type. Written only when set,
    // and for the type only when it is not "bootc".
    QString flatpakVarPath;
    QString imageType;
    // Offline OCI stores. Left empty (so absent), fisherman exposes the
    // stores it finds on the host; the wizard never fills it.
    QStringList additionalImageStores;
    QString distroID;            // filled from the branding contract by the controller
    // true makes bootc boot the installed system with selinux=0. Keep SELinux on.
    bool selinuxDisabled = false;
    QString hostname;            // likewise: branding default_hostname
    // The account fisherman creates (the schema's `user`). An empty username
    // leaves the whole block out, which fisherman reads as "create no user";
    // the account step holds Next until one is typed. The password reaches
    // fisherman only on stdin, like the passphrase.
    struct {
        QString username;
        QString fullname;
        QString password;
        // The shared default list (shared/account/groups.json): the admin
        // groups of both distro families and the developer groups.
        // fisherman drops each group the image does not have.
        QStringList groups = account::defaultGroups();
    } user;
    // False when the selected image creates its own first user
    // (needs_user_creation in the catalog, mirrored from the GNOME image step
    // and the XFCE IdentityPage): the `user` block is then omitted even with
    // a typed username, the way the XFCE build_recipe omits it. Defaults to
    // true — no catalog means the account step is required, as before.
    bool userRequired = true;
    // fisherman's probe says the host booted from live media: an empty image
    // installs the running system, and is left out of the JSON.
    bool liveMode = false;

    QJsonObject toJson() const;
    static Recipe fromJson(const QJsonObject &obj);
    bool isValid() const;
    QString validationError() const;

    // The encryption types fisherman accepts, in the order the encryption
    // step offers them: the compiled-in copy of fisherman's
    // encryption-choices.json (tests/unit/test_encryption_choices.py).
    static const QStringList &encryptionTypes();
    // That file's needs_passphrase and needs_tpm2 for a type ("" is none).
    static bool needsPassphrase(const QString &type);
    static bool needsTpm2(const QString &type);
};

#endif // RECIPE_H
