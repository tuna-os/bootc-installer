#include "plan.h"

#include "branding.h"

#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include <QtGlobal>
#if QT_CONFIG(process)
#include <QProcess>
#endif

#include <cmath>

namespace plan {

namespace {

// The effects with a line of their own; another is read as a format: the
// device's data is still lost.
const QHash<QString, QString> &effectKeys()
{
    static const QHash<QString, QString> keys{
        {QStringLiteral("wipe_disk"), QStringLiteral("confirm_plan_wipe_disk")},
        {QStringLiteral("format"), QStringLiteral("confirm_plan_format")},
        {QStringLiteral("mkswap"), QStringLiteral("confirm_plan_mkswap")},
    };
    return keys;
}

QJsonObject target(const QJsonObject &plan)
{
    return plan.value(QLatin1String("target")).toObject();
}

// A string the plan knows: not "unknown", not empty.
bool known(const QJsonValue &v)
{
    return v.isString() && !v.toString().isEmpty() && v.toString() != QLatin1String(UNKNOWN);
}

// A positive whole number of bytes, or 0.
qint64 sizeOf(const QJsonValue &v)
{
    if (!v.isDouble())
        return 0;
    const double d = v.toDouble();
    if (d <= 0 || std::floor(d) != d)
        return 0;
    return static_cast<qint64>(d);
}

} // namespace

Result failed(const QString &why)
{
    Result r;
    r.error = why;
    return r;
}

QStringList arguments()
{
    return {QStringLiteral("plan"), QStringLiteral("--json"), QStringLiteral("-")};
}

Result parse(const QByteArray &json)
{
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(json, &err);
    if (err.error != QJsonParseError::NoError)
        return failed(QStringLiteral("fisherman plan printed invalid JSON"));
    if (!doc.isObject())
        return failed(QStringLiteral("fisherman plan did not print a JSON object"));
    const QJsonObject root = doc.object();
    const QJsonValue version = root.value(QLatin1String("protocol_version"));
    if (!version.isDouble() || version.toDouble() != PROTOCOL_VERSION)
        return failed(QStringLiteral("fisherman plan protocol_version is not %1").arg(PROTOCOL_VERSION));
    const QJsonValue valid = root.value(QLatin1String("valid"));
    const QJsonValue errors = root.value(QLatin1String("errors"));
    if (!valid.isBool() || !errors.isArray())
        return failed(QStringLiteral("fisherman plan printed no valid flag or errors list"));
    const QJsonValue planValue = root.value(QLatin1String("plan"));
    if (valid.toBool() && !planValue.isObject())
        return failed(QStringLiteral("fisherman plan is valid but printed no plan"));
    Result r;
    r.ok = true;
    r.valid = valid.toBool();
    for (const QJsonValue &e : errors.toArray()) {
        const QJsonValue code = e.toObject().value(QLatin1String("code"));
        if (code.isString())
            r.errorCodes << code.toString();
    }
    if (r.valid)
        r.plan = planValue.toObject();
    return r;
}

Result fromExit(bool normalExit, int exitCode, const QByteArray &stdoutData, const QByteArray &stderrData)
{
    if (!normalExit)
        return failed(QStringLiteral("fisherman plan did not exit"));
    if (exitCode != 0 && exitCode != 1) {
        const QString detail = QString::fromUtf8(stderrData).trimmed().section(QLatin1Char('\n'), 0, 0);
        return failed(QStringLiteral("fisherman plan failed (exit %1): %2")
                           .arg(exitCode)
                           .arg(detail.isEmpty() ? QStringLiteral("no message") : detail));
    }
    return parse(stdoutData);
}

Result run(const QStringList &argv, const QByteArray &recipeJson, int timeoutMs)
{
#if QT_CONFIG(process)
    if (argv.isEmpty())
        return failed(QStringLiteral("no fisherman to ask"));
    QProcess p;
    p.start(argv.first(), argv.mid(1));
    if (!p.waitForStarted(5000))
        return failed(QStringLiteral("cannot run %1").arg(argv.first()));
    // The recipe on stdin, never argv: it can hold the passphrase.
    p.write(recipeJson);
    p.closeWriteChannel();
    if (!p.waitForFinished(timeoutMs)) {
        p.kill();
        p.waitForFinished(1000);
        return failed(QStringLiteral("fisherman plan gave no answer in %1 s").arg(timeoutMs / 1000.0));
    }
    return fromExit(p.exitStatus() == QProcess::NormalExit, p.exitCode(), p.readAllStandardOutput(),
                    p.readAllStandardError());
#else
    Q_UNUSED(argv);
    Q_UNUSED(recipeJson);
    Q_UNUSED(timeoutMs);
    return failed(QStringLiteral("this build cannot start fisherman"));
#endif
}

QJsonObject identity(const QJsonObject &plan)
{
    return target(plan).value(QLatin1String("identity")).toObject();
}

QJsonObject diskIdentity(const QJsonObject &plan)
{
    const QJsonObject ident = identity(plan);
    QJsonObject out;
    for (const char *key : {"serial", "wwn"}) {
        const QJsonValue v = ident.value(QLatin1String(key));
        if (known(v))
            out.insert(QLatin1String(key), v);
    }
    if (const qint64 size = sizeOf(ident.value(QLatin1String("size_bytes"))))
        out.insert(QLatin1String("sizeBytes"), size);
    return out;
}

QJsonObject bind(const QJsonObject &recipe, const QJsonObject &plan)
{
    const QJsonObject binding = diskIdentity(plan);
    const QString disk = target(plan).value(QLatin1String("disk")).toString();
    if (binding.isEmpty() || disk.isEmpty() || disk != recipe.value(QLatin1String("disk")).toString())
        return recipe;
    QJsonObject bound = recipe;
    bound.insert(QLatin1String("diskIdentity"), binding);
    return bound;
}

QList<QPair<QString, QString>> destroys(const QJsonObject &plan)
{
    QList<QPair<QString, QString>> out;
    for (const QJsonValue &v : plan.value(QLatin1String("destroys")).toArray()) {
        const QJsonObject entry = v.toObject();
        const QString device = entry.value(QLatin1String("device")).toString();
        if (!device.isEmpty())
            out.append({device, entry.value(QLatin1String("effect")).toString()});
    }
    return out;
}

Rows targetRows(const QJsonObject &plan, const branding::Branding &copy)
{
    const QJsonObject ident = identity(plan);
    if (ident.isEmpty())
        return {};
    QString unknown = copy.text(QStringLiteral("confirm_plan_unknown"));
    if (unknown.isEmpty())
        unknown = QLatin1String(UNKNOWN);
    const QString disk = target(plan).value(QLatin1String("disk")).toString();
    const qint64 size = sizeOf(ident.value(QLatin1String("size_bytes")));
    const QHash<QString, QString> values{
        {QStringLiteral("disk"), disk.isEmpty() ? unknown : disk},
        {QStringLiteral("model"),
         known(ident.value(QLatin1String("model"))) ? ident.value(QLatin1String("model")).toString() : unknown},
        {QStringLiteral("size"), size > 0 ? formatSize(size) : unknown},
        {QStringLiteral("serial"),
         known(ident.value(QLatin1String("serial"))) ? ident.value(QLatin1String("serial")).toString() : unknown},
    };
    Rows rows{{copy.text(QStringLiteral("confirm_plan_target"), values),
               copy.text(QStringLiteral("confirm_plan_target_detail"), values)}};
    const QJsonObject binding = diskIdentity(plan);
    const bool bound = binding.contains(QLatin1String("serial")) || binding.contains(QLatin1String("wwn"));
    rows.append({copy.text(bound ? QStringLiteral("confirm_plan_bound") : QStringLiteral("confirm_plan_unbound"),
                           values),
                 QString()});
    Rows out;
    for (const auto &row : rows) {
        if (!row.first.isEmpty())
            out.append(row);
    }
    return out;
}

Rows destroyRows(const QJsonObject &plan, const branding::Branding &copy)
{
    Rows out;
    for (const auto &[device, effect] : destroys(plan)) {
        const QString key = effectKeys().value(effect, QStringLiteral("confirm_plan_format"));
        const QString line = copy.text(key, {{QStringLiteral("disk"), device}});
        if (!line.isEmpty())
            out.append({line, QString()});
    }
    return out;
}

Rows rows(const QJsonObject &plan, const branding::Branding &copy)
{
    return targetRows(plan, copy) + destroyRows(plan, copy);
}

QString formatSize(qint64 bytes)
{
    static const char *units[] = {"B", "KiB", "MiB", "GiB", "TiB", "PiB"};
    double value = static_cast<double>(bytes);
    int i = 0;
    while (value >= 1024 && i < 5) {
        value /= 1024;
        ++i;
    }
    if (i == 0)
        return QStringLiteral("%1 B").arg(bytes);
    QString text = QString::number(value, 'f', 1);
    if (text.endsWith(QLatin1String(".0")))
        text.chop(2);
    return text + QLatin1Char(' ') + QLatin1String(units[i]);
}

}
