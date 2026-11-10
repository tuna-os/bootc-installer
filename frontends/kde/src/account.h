#pragma once

// The first account's supplementary groups (shared/account/README.md).
//
// The default list is shared by the five frontends: CMake compiles
// shared/account/groups.json in (TUNA_SHARED_DIR).
// fisherman removes each group the image does not have, so the full list
// goes into the recipe whatever the image is. An ISO builder replaces the
// list with `user.groups` in <etc>/bootc-installer/recipe.json.

#include <QByteArray>
#include <QString>
#include <QStringList>

namespace account {

// `default_groups` of the compiled-in file.
QStringList defaultGroups();

// The compiled-in file itself, for the test that holds it to the shared one.
QByteArray groupsJson();

// The groups for an operator recipe file's contents. A null QByteArray is
// "no file". A list of strings at `user.groups` replaces the default, an
// empty list included; anything else is the default.
QStringList groups(const QByteArray &operatorRecipe);

// <etc>/bootc-installer/recipe.json; <etc> is /run/host/etc in a Flatpak.
QString operatorRecipePath(bool flatpak);

// groups() of the file at `path`.
QStringList groupsFromFile(const QString &path);

} // namespace account
