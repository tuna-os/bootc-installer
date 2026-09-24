#pragma once

// One logging category for the whole frontend.
//
// Warnings are on by default, so a helper that failed or an install that never
// started shows up in the journal (or on stderr) without anyone enabling
// anything. Debug output is opt-in:
//   QT_LOGGING_RULES="tunaos.installer.debug=true" tuna-installer-kde

#include <QLoggingCategory>

Q_DECLARE_LOGGING_CATEGORY(logInstaller)
