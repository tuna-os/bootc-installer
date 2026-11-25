#pragma once

// A small QR Code generator for the recovery key: byte mode, EC level M,
// automatic version (1-6), mask by the standard penalty rules.
//
// The key is 71 ASCII bytes; anything longer than a version 6 symbol is
// refused (ok == false). This is not a general-purpose encoder: one mode,
// one level, six versions.

#include <QString>
#include <QStringList>
#include <vector>

namespace qrcode
{

struct Code {
    bool ok = false;
    int version = 0;
    int size = 0; // modules per side
    std::vector<char> modules; // row-major, 1 is dark
    bool at(int x, int y) const { return modules[size_t(y) * size_t(size) + size_t(x)] != 0; }
    // Rows of '0' and '1', for QML and for the golden tests.
    QStringList rows() const;
};

Code encode(const QString &text);

} // namespace qrcode
