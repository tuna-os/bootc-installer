#pragma once

// Product branding: a branding.json first, os-release second, neutral last.
//
// The contract, the key table and the fixtures are in shared/branding/ at the
// monorepo root; every frontend resolves the same way and this is the C++
// copy, tested against the shared fixtures by tests/test_backend.cpp.
// Nothing in this file names a product.

#include <QHash>
#include <QJsonObject>
#include <QString>
#include <QStringList>

namespace branding {

struct Branding {
    QString name;
    QString id;
    QString vendor;
    QString homeUrl;
    QString docsUrl;
    QString supportUrl;
    QString logo;
    QString defaultHostname;
    QString defaultImage;
};

// The branding for this machine: $BOOTC_INSTALLER_BRANDING or the standard
// branding.json paths (host first, this ships as a Flatpak), then os-release,
// then a neutral "Linux". $BOOTC_INSTALLER_PRODUCT_NAME overrides `name` only
// (screenshot harness).
Branding resolve();

// The same, with explicit search lists; what resolve() calls.
Branding resolveFrom(const QStringList &brandingPaths, const QStringList &osReleasePaths,
                     const QString &nameOverride);

// The pure merge rule from shared/branding/README.md, exposed for tests.
Branding fromSources(const QJsonObject &file, const QString &osReleaseText,
                     const QString &nameOverride = QString());

// KEY=value pairs from os-release text, quotes and backslash escapes removed.
QHash<QString, QString> parseOsRelease(const QString &text);

} // namespace branding
