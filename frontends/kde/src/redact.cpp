#include "redact.h"

#include <QRegularExpression>
#include <QStringList>

namespace redact {

const QString kPlaceholder = QStringLiteral("[redacted]");

QString recoveryKey(const QString &text, const QString &knownKey)
{
    if (text.isEmpty())
        return text;
    // {"type":"recovery_key","key":"..."}: the value, with its escapes.
    static const QRegularExpression keyEvent(
        QStringLiteral(R"(("key"\s*:\s*")(?:[^"\\]|\\.)*("))"),
        QRegularExpression::UseUnicodePropertiesOption);
    // The line a frontend renders for that event.
    static const QRegularExpression keyLine(
        QStringLiteral(R"((Recovery key:\s*)\S.*)"),
        QRegularExpression::UseUnicodePropertiesOption);

    QStringList lines = text.split(QLatin1Char('\n'));
    for (QString &line : lines) {
        if (line.contains(QLatin1String("\"recovery_key\"")))
            line.replace(keyEvent, QStringLiteral("\\1") + kPlaceholder + QStringLiteral("\\2"));
        line.replace(keyLine, QStringLiteral("\\1") + kPlaceholder);
    }
    QString out = lines.join(QLatin1Char('\n'));
    const QString known = knownKey.trimmed();
    if (!known.isEmpty())
        out.replace(known, kPlaceholder);
    return out;
}

} // namespace redact
