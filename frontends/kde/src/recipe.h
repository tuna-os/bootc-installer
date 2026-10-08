#ifndef RECIPE_H
#define RECIPE_H

#include <QJsonObject>
#include <QString>
#include <QStringList>

struct Recipe {
    QString disk;
    QString filesystem = "xfs";
    bool btrfsSubvolumes = false;
    struct {
        // "none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"
        QString type = "none";
        QString passphrase;
    } encryption;
    QString image; // may stay empty in live-ISO mode (bootc installs the running container)
    QString targetImgref;
    QString bootloader;        // "", "grub2", "systemd"
    bool composeFsBackend = false;
    QStringList flatpaks;
    QStringList additionalImageStores; // embedded OCI stores for offline installs
    QString distroID;            // filled from the branding contract by the controller
    // true makes bootc boot the installed system with selinux=0. Keep SELinux on.
    bool selinuxDisabled = false;
    QString hostname;            // likewise: branding default_hostname
    bool liveMode = false; // true when installing the running live system

    QJsonObject toJson() const;
    static Recipe fromJson(const QJsonObject &obj);
    bool isValid() const;
    QString validationError() const;
};

#endif // RECIPE_H
