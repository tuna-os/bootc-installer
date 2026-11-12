#pragma once

#include <QLocale>
#include <QStringList>

class QTranslator;

// The Qt catalogs of this frontend (#300). CMake compiles each
// i18n/tuna-installer-kde_<lang>.ts to a .qm file and installs it in
// share/tuna-installer-kde/translations; shared/i18n/catalogs.py writes the
// .ts files.
namespace translations {

// "tuna-installer-kde": the base name of each .qm file.
QString domain();

// Each share/tuna-installer-kde/translations directory on the data path
// (in a Flatpak /app/share comes first), in order.
QStringList directories();

// Load the catalog for `locale` from the first of `dirs` that has one.
// QTranslator tries each of the locale's UI languages ("fr_FR", then "fr").
// False when no directory has one: the UI then shows the English text.
bool load(QTranslator &translator, const QLocale &locale, const QStringList &dirs);

} // namespace translations
