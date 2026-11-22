// Size text from a toolkit, made comparable (projectbluefin/utah#1437).
// GLib's g_format_size puts U+00A0 between the number and the unit. Some
// locales use U+202F. Same cases as shared/client/fixtures/sizes.json.
#pragma once

#include <QRegularExpression>
#include <QString>
#include <optional>

namespace tuna {

inline bool isSpaceLike(QChar c)
{
    const ushort u = c.unicode();
    return c.isSpace() || u == 0x00a0 || u == 0x1680 || (u >= 0x2000 && u <= 0x200a) || u == 0x202f
        || u == 0x205f || u == 0x3000;
}

inline bool isInvisible(QChar c)
{
    const ushort u = c.unicode();
    return (u >= 0x200b && u <= 0x200f) || u == 0x2060 || (u >= 0x2066 && u <= 0x2069) || u == 0xfeff
        || u == 0x00ad;
}

// One plain space for each run of space-like characters; trimmed; no invisible marks.
inline QString normalizeSizeText(const QString &text)
{
    QString out;
    bool pendingSpace = false;
    for (const QChar c : text) {
        if (isInvisible(c)) {
            continue;
        }
        if (isSpaceLike(c)) {
            pendingSpace = !out.isEmpty();
            continue;
        }
        if (pendingSpace) {
            out += QLatin1Char(' ');
            pendingSpace = false;
        }
        out += c;
    }
    return out;
}

inline std::optional<double> unitFactor(const QString &unit)
{
    static const QHash<QString, double> units = {
        {"b", 1}, {"byte", 1}, {"bytes", 1},
        {"kb", 1e3}, {"mb", 1e6}, {"gb", 1e9}, {"tb", 1e12}, {"pb", 1e15},
        {"kib", 1024.0}, {"mib", 1048576.0}, {"gib", 1073741824.0},
        {"tib", 1099511627776.0}, {"pib", 1125899906842624.0},
    };
    const auto it = units.constFind(unit.toLower());
    return it == units.cend() ? std::nullopt : std::optional<double>(*it);
}

// Bytes, or nullopt when the text is not one size. SI units are powers of 1000.
inline std::optional<qint64> parseSize(const QString &text)
{
    static const QRegularExpression re(QStringLiteral("^(\\d[\\d.,]*) ?([A-Za-z]+)$"));
    const auto m = re.match(normalizeSizeText(text));
    if (!m.hasMatch()) {
        return std::nullopt;
    }
    QString num = m.captured(1);
    if (num.contains('.') && num.contains(',')) {
        num.remove(',');
    } else if (num.contains(',')) {
        const int i = num.lastIndexOf(',');
        QString head = num.left(i).remove(',');
        const QString tail = num.mid(i + 1);
        num = tail.size() == 3 ? head + tail : head + '.' + tail;
    }
    bool ok = false;
    const double value = num.toDouble(&ok);
    const auto factor = unitFactor(m.captured(2));
    if (!ok || !factor) {
        return std::nullopt;
    }
    return qint64(qRound64(value * *factor));
}

} // namespace tuna
