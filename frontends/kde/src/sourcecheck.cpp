#include "sourcecheck.h"

#include "branding.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include <QRegularExpression>
#include <QSet>

#include <cmath>

namespace sourcecheck {

namespace {

const QSet<QString> &knownFeatures()
{
    static const QSet<QString> names{
        QStringLiteral("bootc_image_storage"), QStringLiteral("deployment_mount"),
        QStringLiteral("finalization"), QStringLiteral("install_configuration"),
        QStringLiteral("native_inspection"), QStringLiteral("unified_storage"),
    };
    return names;
}

QString str(const QJsonValue &v)
{
    return v.isString() ? v.toString() : QString();
}

bool isTrue(const QJsonValue &v)
{
    return v.isBool() && v.toBool();
}

// An integer number; -1 when the value is not one.
bool integer(const QJsonValue &v, qint64 *out)
{
    if (!v.isDouble())
        return false;
    const double d = v.toDouble();
    if (std::floor(d) != d)
        return false;
    *out = static_cast<qint64>(d);
    return true;
}

QString token(const QJsonValue &v)
{
    static const QRegularExpression re(QStringLiteral("^[a-z0-9_]{1,64}$"));
    const QString s = str(v);
    return re.match(s).hasMatch() ? s : QStringLiteral("unknown");
}

QString reasonKey(const QString &reason)
{
    const QString key = QStringLiteral("source_check_reason_") + token(QJsonValue(reason));
    return branding::copyDefaults().contains(key) ? key : QStringLiteral("source_check_reason_unknown");
}

QJsonObject newCheck(const QString &state, const QString &reason)
{
    return QJsonObject{
        {QStringLiteral("state"), state},
        {QStringLiteral("reason"), reason},
        {QStringLiteral("reason_key"), reasonKey(reason)},
        {QStringLiteral("install_from"), QString()},
        {QStringLiteral("update_ref"), QString()},
        {QStringLiteral("live_host_image"), QString()},
        {QStringLiteral("source_digest"), QString()},
        {QStringLiteral("defaults"), QJsonArray()},
        {QStringLiteral("blockers"), QJsonArray()},
    };
}

bool isStale(const QJsonObject &caps, const Request &req)
{
    const QJsonObject source = caps.value(QLatin1String("source")).toObject();
    const QJsonObject target = caps.value(QLatin1String("target")).toObject();
    if (req.liveRoot) {
        if (str(source.value(QLatin1String("transport"))) != QLatin1String("live-root"))
            return true;
    } else if (!req.source.isEmpty()) {
        if (str(source.value(QLatin1String("ref"))) != req.source
            || str(source.value(QLatin1String("transport"))) == QLatin1String("live-root"))
            return true;
    } else if (isTrue(source.value(QLatin1String("selected")))) {
        return true;
    }
    const bool fromTarget = str(target.value(QLatin1String("update_ref_from"))) == QLatin1String("target_imgref");
    if (!req.target.isEmpty())
        return !fromTarget || str(target.value(QLatin1String("update_ref"))) != req.target;
    return fromTarget;
}

bool parseObject(bool ok, const QByteArray &data, QJsonObject *out)
{
    if (!ok)
        return false;
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(data, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject())
        return false;
    *out = doc.object();
    return true;
}

QJsonObject defaultLine(const QString &key, const QString &value)
{
    return QJsonObject{{QStringLiteral("key"), key}, {QStringLiteral("value"), value}};
}

}

QString plainRef(const QString &ref)
{
    const QString trimmed = ref.trimmed();
    static const QString transport = QStringLiteral("docker://");
    return trimmed.startsWith(transport) ? trimmed.mid(transport.size()) : trimmed;
}

Request fromRecipe(const QJsonObject &recipe, bool isLive)
{
    Request r;
    r.source = str(recipe.value(QLatin1String("image")));
    if (recipe.value(QLatin1String("sourceReuse")).isObject()) {
        // A copy of this computer's system: reuseSource() offers only the
        // item whose ref is the update reference, so the probe asks about it.
        r.source = plainRef(str(recipe.value(QLatin1String("targetImgref"))));
        isLive = false;
    }
    r.liveRoot = r.source.isEmpty() && isLive;
    r.target = str(recipe.value(QLatin1String("targetImgref")));
    if (isTrue(recipe.value(QLatin1String("unifiedStorage"))))
        r.features << QStringLiteral("unified_storage");
    return r;
}

QStringList probeArguments(const Request &req)
{
    QStringList args;
    if (req.liveRoot)
        args << QStringLiteral("--live-root");
    else if (!req.source.isEmpty())
        args << QStringLiteral("--source") << req.source;
    else
        return {};
    if (!req.target.isEmpty())
        args << QStringLiteral("--target-imgref") << req.target;
    return args;
}

QJsonObject check(bool ok, const QByteArray &probeOutput, const Request &req)
{
    QJsonObject result;
    if (!parseObject(ok, probeOutput, &result))
        return newCheck(QStringLiteral("unavailable"), QStringLiteral("probe_failed"));
    if (!result.contains(QLatin1String("capabilities")))
        return newCheck(QStringLiteral("unsupported"), QStringLiteral("backend_too_old"));
    const QJsonValue capsValue = result.value(QLatin1String("capabilities"));
    qint64 version = 0;
    if (!capsValue.isObject() || !integer(capsValue.toObject().value(QLatin1String("version")), &version))
        return newCheck(QStringLiteral("unavailable"), QStringLiteral("malformed"));
    if (version != 1)
        return newCheck(QStringLiteral("unsupported"), QStringLiteral("version_unsupported"));
    const QJsonObject caps = capsValue.toObject();
    if (isStale(caps, req))
        return newCheck(QStringLiteral("stale"), QStringLiteral("reply_for_other_source"));

    const QJsonObject source = caps.value(QLatin1String("source")).toObject();
    const QJsonObject root = caps.value(QLatin1String("execution_root")).toObject();
    const QJsonObject features = caps.value(QLatin1String("features")).toObject();
    QJsonArray blockers;
    for (const QString &name : req.features) {
        if (knownFeatures().contains(name)
            && str(features.value(name).toObject().value(QLatin1String("status"))) == QLatin1String("unsupported"))
            blockers.append(name);
    }
    QString state, reason;
    if (!blockers.isEmpty()) {
        state = QStringLiteral("blocked");
        reason = QStringLiteral("feature_unsupported");
    } else if (!isTrue(source.value(QLatin1String("selected")))) {
        state = QStringLiteral("unavailable");
        reason = QStringLiteral("no_source_selected");
    } else if (!isTrue(root.value(QLatin1String("established")))) {
        state = QStringLiteral("unavailable");
        reason = token(root.value(QLatin1String("reason")));
        const QString digestReason = str(source.value(QLatin1String("digest_reason")));
        if (reason == QLatin1String("source_digest_unknown") && !digestReason.isEmpty())
            reason = token(QJsonValue(digestReason));
    } else {
        state = QStringLiteral("ready");
        reason = token(root.value(QLatin1String("reason")));
    }
    QJsonObject view = newCheck(state, reason);
    view[QStringLiteral("install_from")] = str(source.value(QLatin1String("ref")));
    view[QStringLiteral("update_ref")] = str(caps.value(QLatin1String("target")).toObject().value(QLatin1String("update_ref")));
    view[QStringLiteral("live_host_image")] = str(caps.value(QLatin1String("live_host")).toObject().value(QLatin1String("image")));
    view[QStringLiteral("source_digest")] = str(source.value(QLatin1String("digest")));
    view[QStringLiteral("blockers")] = blockers;
    const QJsonObject defaults = caps.value(QLatin1String("install_defaults")).toObject();
    if (state == QLatin1String("ready") && isTrue(defaults.value(QLatin1String("observed")))) {
        QJsonArray lines;
        const QString fs = str(defaults.value(QLatin1String("root_filesystem")));
        if (!fs.isEmpty())
            lines.append(defaultLine(QStringLiteral("source_check_default_filesystem"), fs));
        const QJsonValue setupsValue = defaults.value(QLatin1String("block_setups"));
        if (setupsValue.isArray()) {
            QStringList setups;
            for (const QJsonValue &s : setupsValue.toArray()) {
                if (!str(s).isEmpty())
                    setups << s.toString();
            }
            if (!setups.isEmpty())
                lines.append(defaultLine(QStringLiteral("source_check_default_block_setups"), setups.join(QStringLiteral(", "))));
        }
        const QString loader = str(defaults.value(QLatin1String("bootloader")));
        if (!loader.isEmpty())
            lines.append(defaultLine(QStringLiteral("source_check_default_bootloader"), loader));
        view[QStringLiteral("defaults")] = lines;
    }
    return view;
}

bool blocksInstall(const QJsonObject &checkView)
{
    return checkView.value(QLatin1String("state")).toString() == QLatin1String("blocked");
}

QJsonObject bootcStore(bool ok, const QByteArray &probeOutput)
{
    auto view = [](const QString &state, const QString &reason) {
        return QJsonObject{{QStringLiteral("state"), state}, {QStringLiteral("reason"), reason},
                           {QStringLiteral("items"), QJsonArray()}, {QStringLiteral("hidden"), 0}};
    };
    QJsonObject result;
    if (!parseObject(ok, probeOutput, &result))
        return view(QStringLiteral("unavailable"), QStringLiteral("probe_failed"));
    if (!result.contains(QLatin1String("bootc_store")))
        return view(QStringLiteral("unsupported"), QStringLiteral("backend_too_old"));
    const QJsonValue storeValue = result.value(QLatin1String("bootc_store"));
    qint64 version = 0;
    if (!storeValue.isObject() || !integer(storeValue.toObject().value(QLatin1String("version")), &version))
        return view(QStringLiteral("unavailable"), QStringLiteral("malformed"));
    if (version != 1)
        return view(QStringLiteral("unsupported"), QStringLiteral("version_unsupported"));
    const QJsonObject store = storeValue.toObject();
    if (!isTrue(store.value(QLatin1String("available"))))
        return view(QStringLiteral("unavailable"), token(store.value(QLatin1String("reason"))));
    if (!store.value(QLatin1String("items")).isArray())
        return view(QStringLiteral("unavailable"), QStringLiteral("malformed"));
    QJsonArray items;
    int hidden = 0;
    for (const QJsonValue &entry : store.value(QLatin1String("items")).toArray()) {
        const QJsonObject item = entry.toObject();
        const QString ref = str(item.value(QLatin1String("ref")));
        if (ref.isEmpty() || str(item.value(QLatin1String("owner"))) != QLatin1String("bootc")
            || str(item.value(QLatin1String("context"))) != QLatin1String("live-host")) {
            ++hidden;
            continue;
        }
        bool booted = false;
        for (const QJsonValue &role : item.value(QLatin1String("roles")).toArray())
            booted = booted || str(role) == QLatin1String("booted");
        QString availability = str(item.value(QLatin1String("availability")));
        if (availability != QLatin1String("deployed") && availability != QLatin1String("stored")
            && availability != QLatin1String("listed"))
            availability = QStringLiteral("listed");
        QString storage = str(item.value(QLatin1String("storage")));
        if (storage.isEmpty())
            storage = QStringLiteral("unknown");
        items.append(QJsonObject{
            {QStringLiteral("ref"), ref},
            {QStringLiteral("kind"), booted ? QStringLiteral("booted") : availability},
            {QStringLiteral("availability"), availability},
            {QStringLiteral("storage"), storage},
            {QStringLiteral("digest"), str(item.value(QLatin1String("digest")))},
            {QStringLiteral("platform"), str(item.value(QLatin1String("platform")))},
            {QStringLiteral("matches_machine"), isTrue(item.value(QLatin1String("matches_machine")))},
            {QStringLiteral("installable"), false},
        });
    }
    QJsonObject out = view(items.isEmpty() ? QStringLiteral("empty") : QStringLiteral("listed"),
                           QStringLiteral("observed"));
    out[QStringLiteral("items")] = items;
    out[QStringLiteral("hidden")] = hidden;
    return out;
}

QJsonObject verification(const QByteArray &data, const QString &expectedInstallId)
{
    auto view = [](const QString &state, const QString &reason) {
        return QJsonObject{{QStringLiteral("state"), state}, {QStringLiteral("reason"), reason}};
    };
    QJsonObject result;
    if (!parseObject(true, data, &result)
        || str(result.value(QLatin1String("schema"))) != QLatin1String("fisherman.boot-verification"))
        return view(QStringLiteral("unavailable"), QStringLiteral("result_malformed"));
    qint64 version = 0;
    if (!integer(result.value(QLatin1String("version")), &version))
        return view(QStringLiteral("unavailable"), QStringLiteral("result_malformed"));
    if (version != 1)
        return view(QStringLiteral("unsupported"), QStringLiteral("result_version_unsupported"));
    if (!expectedInstallId.isEmpty() && str(result.value(QLatin1String("install_id"))) != expectedInstallId)
        return view(QStringLiteral("unavailable"), QStringLiteral("other_install"));
    const QString reason = token(result.value(QLatin1String("reason")));
    static const QHash<QString, QString> outcomes{
        {QStringLiteral("verified"), QStringLiteral("verified")},
        {QStringLiteral("mismatch"), QStringLiteral("mismatch")},
        {QStringLiteral("unsupported"), QStringLiteral("unsupported")},
        {QStringLiteral("unavailable"), QStringLiteral("unavailable")},
        {QStringLiteral("not-yet-run"), QStringLiteral("pending")},
    };
    const QString outcome = str(result.value(QLatin1String("outcome")));
    if (!outcomes.contains(outcome))
        return view(QStringLiteral("unavailable"), QStringLiteral("outcome_unknown"));
    const QString state = outcomes.value(outcome);
    if (state == QLatin1String("verified")) {
        const QString evidence = str(result.value(QLatin1String("evidence")));
        if (evidence != QLatin1String("live_status") && evidence != QLatin1String("collected_status"))
            return view(QStringLiteral("unavailable"), QStringLiteral("wrong_execution_context"));
        const QJsonValue checks = result.value(QLatin1String("checks"));
        if (!checks.isObject())
            return view(QStringLiteral("unavailable"), QStringLiteral("result_inconsistent"));
        for (const QJsonValue &c : checks.toObject()) {
            if (str(c) == QLatin1String("mismatch"))
                return view(QStringLiteral("unavailable"), QStringLiteral("result_inconsistent"));
        }
    }
    return view(state, reason);
}

// The receipt event (#269): bootc_shared.progress.receipt_of().
QJsonObject receiptOf(const QJsonObject &event)
{
    auto view = [](const QString &state, const QString &installId = QString(), const QString &reason = QString()) {
        return QJsonObject{{QStringLiteral("state"), state}, {QStringLiteral("install_id"), installId},
                           {QStringLiteral("reason"), reason}};
    };
    qint64 version = 0;
    if (!integer(event.value(QLatin1String("version")), &version) || version != 1)
        return view(QStringLiteral("unreadable"));
    const QJsonValue written = event.value(QLatin1String("written"));
    if (!written.isBool())
        return view(QStringLiteral("unreadable"));
    static const QRegularExpression code(QStringLiteral("^[a-z0-9_]{1,64}$"));
    static const QRegularExpression id(QStringLiteral("^[0-9a-f]{32}$"));
    QString reason = str(event.value(QLatin1String("reason")));
    if (!code.match(reason).hasMatch())
        reason.clear();
    if (!written.toBool())
        return view(QStringLiteral("not_written"), QString(), reason);
    const QString installId = str(event.value(QLatin1String("install_id")));
    if (!id.match(installId).hasMatch())
        return view(QStringLiteral("unreadable"));
    if (isTrue(event.value(QLatin1String("first_boot_check"))))
        return view(QStringLiteral("check_set_up"), installId);
    return view(QStringLiteral("written_no_check"), installId, reason);
}

// bootc_shared.completion.receipt_lines(): the done page's copy keys.
QList<QPair<QString, QString>> receiptLines(const QJsonValue &receipt)
{
    QList<QPair<QString, QString>> lines{{QStringLiteral("done_verification"), QString()}};
    if (!receipt.isObject()) {
        lines.append({QStringLiteral("done_receipt_none"), QString()});
        return lines;
    }
    const QJsonObject r = receipt.toObject();
    const QString state = str(r.value(QLatin1String("state")));
    if (state != QLatin1String("check_set_up") && state != QLatin1String("written_no_check")
        && state != QLatin1String("not_written")) {
        lines.append({QStringLiteral("done_receipt_unreadable"), QString()});
        return lines;
    }
    lines.append({QStringLiteral("done_receipt_") + state, str(r.value(QLatin1String("install_id")))});
    if (state != QLatin1String("check_set_up")) {
        const QString reason = str(r.value(QLatin1String("reason")));
        const QString key = QStringLiteral("done_receipt_reason_") + (reason.isEmpty() ? QStringLiteral("unknown") : reason);
        lines.append({branding::copyDefaults().contains(key) ? key : QStringLiteral("done_receipt_reason_unknown"), QString()});
    }
    return lines;
}

QJsonObject errorOf(const QJsonObject &event)
{
    const QJsonValue changed = event.value(QLatin1String("disk_changed"));
    QJsonValue cleanup(QJsonValue::Null);
    if (event.value(QLatin1String("cleanup")).isObject()) {
        const QJsonObject c = event.value(QLatin1String("cleanup")).toObject();
        const QString status = str(c.value(QLatin1String("status")));
        const bool known = status == QLatin1String("ok") || status == QLatin1String("failed")
            || status == QLatin1String("timed_out");
        cleanup = QJsonObject{
            {QStringLiteral("status"), known ? status : QString()},
            {QStringLiteral("message"), str(c.value(QLatin1String("message")))},
        };
    }
    return QJsonObject{
        {QStringLiteral("message"), str(event.value(QLatin1String("message")))},
        {QStringLiteral("code"), str(event.value(QLatin1String("code")))},
        {QStringLiteral("field"), str(event.value(QLatin1String("field")))},
        {QStringLiteral("step_id"), str(event.value(QLatin1String("step_id")))},
        {QStringLiteral("disk_changed"), changed.isBool() ? changed : QJsonValue(QJsonValue::Null)},
        {QStringLiteral("cleanup"), cleanup},
    };
}

QStringList failureLines(const QJsonObject &error)
{
    QStringList lines;
    const QJsonValue changed = error.value(QLatin1String("disk_changed"));
    if (changed.isBool())
        lines << (changed.toBool() ? QStringLiteral("done_failed_disk_changed")
                                   : QStringLiteral("done_failed_disk_unchanged"));
    const QString status = str(error.value(QLatin1String("cleanup")).toObject().value(QLatin1String("status")));
    if (status == QLatin1String("failed"))
        lines << QStringLiteral("done_failed_cleanup_failed");
    else if (status == QLatin1String("timed_out"))
        lines << QStringLiteral("done_failed_cleanup_timed_out");
    return lines;
}

namespace {

// A byte count or a time in ms: a whole number >= 0, else null.
QJsonValue count(const QJsonValue &v)
{
    qint64 n = 0;
    if (!integer(v, &n) || n < 0)
        return QJsonValue(QJsonValue::Null);
    return QJsonValue(n);
}

QString gib(qint64 bytes)
{
    return QString::number(static_cast<double>(bytes) / (1LL << 30), 'f', 1);
}

}

// bootc_shared.progress.source_reuse_of().
QJsonValue sourceReuseOf(const QJsonObject &event, const QJsonValue &view)
{
    static const QRegularExpression code(QStringLiteral("^[a-z0-9_]{1,64}$"));
    static const QRegularExpression digest(QStringLiteral("^sha256:[0-9a-f]{64}$"));
    QJsonObject out = view.isObject() ? view.toObject()
                                      : QJsonObject{{QStringLiteral("phase"), QString()},
                                                    {QStringLiteral("required_bytes"), QJsonValue::Null},
                                                    {QStringLiteral("destination_digest"), QString()},
                                                    {QStringLiteral("copy_ms"), QJsonValue::Null},
                                                    {QStringLiteral("used_bytes"), QJsonValue::Null},
                                                    {QStringLiteral("code"), QString()},
                                                    {QStringLiteral("released"), QString()},
                                                    {QStringLiteral("destination"), QString()}};
    qint64 version = 0;
    if (!integer(event.value(QLatin1String("version")), &version) || version != 1) {
        out[QStringLiteral("phase")] = QStringLiteral("unreadable");
        return out;
    }
    const QString phase = str(event.value(QLatin1String("phase")));
    static const QStringList phases{QStringLiteral("planned"), QStringLiteral("copying"),
                                    QStringLiteral("verified"), QStringLiteral("failed"),
                                    QStringLiteral("released")};
    if (!phases.contains(phase))
        return view;
    const QString destination = str(event.value(QLatin1String("destination")));
    if (!destination.isEmpty())
        out[QStringLiteral("destination")] = destination;
    if (phase == QLatin1String("released")) {
        const QString reason = str(event.value(QLatin1String("reason")));
        out[QStringLiteral("released")] =
            (reason == QLatin1String("removed") || reason == QLatin1String("remove_failed")) ? reason
                                                                                              : QStringLiteral("unknown");
        return out;
    }
    out[QStringLiteral("phase")] = phase;
    const QJsonObject estimate = event.value(QLatin1String("estimate")).toObject();
    if (estimate.contains(QLatin1String("required_bytes")))
        out[QStringLiteral("required_bytes")] = count(estimate.value(QLatin1String("required_bytes")));
    if (phase == QLatin1String("verified")) {
        const QString d = str(event.value(QLatin1String("destination_digest")));
        out[QStringLiteral("destination_digest")] = digest.match(d).hasMatch() ? d : QString();
        const QJsonObject measured = event.value(QLatin1String("measured")).toObject();
        out[QStringLiteral("copy_ms")] = count(measured.value(QLatin1String("copy_ms")));
        const QJsonValue scratch = count(measured.value(QLatin1String("scratch_peak_bytes")));
        const QJsonValue store = count(measured.value(QLatin1String("store_peak_bytes")));
        if (scratch.isNull() || store.isNull())
            out[QStringLiteral("used_bytes")] = QJsonValue::Null;
        else if (estimate.value(QLatin1String("same_filesystem")) == QJsonValue(false))
            out[QStringLiteral("used_bytes")] = QJsonValue(scratch.toInteger() + store.toInteger());
        else
            out[QStringLiteral("used_bytes")] = QJsonValue(qMax(scratch.toInteger(), store.toInteger()));
    }
    if (phase == QLatin1String("failed")) {
        const QString c = str(event.value(QLatin1String("code")));
        out[QStringLiteral("code")] = code.match(c).hasMatch() ? c : QString();
    }
    return out;
}

// bootc_shared.progress.source_reuse_lines().
QList<QPair<QString, QString>> sourceReuseLines(const QJsonValue &view)
{
    QList<QPair<QString, QString>> lines;
    if (!view.isObject())
        return lines;
    const QJsonObject v = view.toObject();
    const QString prefix = QStringLiteral("progress_reuse_");
    const QString phase = str(v.value(QLatin1String("phase")));
    const QJsonValue required = v.value(QLatin1String("required_bytes"));
    const bool hasSpace = required.isDouble();
    const QPair<QString, QString> space{prefix + QStringLiteral("planned"), hasSpace ? gib(required.toInteger()) : QString()};
    if (phase == QLatin1String("unreadable")) {
        lines.append({prefix + QStringLiteral("unreadable"), QString()});
    } else if (phase == QLatin1String("planned") || phase == QLatin1String("copying")) {
        lines.append(hasSpace ? space : qMakePair(prefix + QStringLiteral("planned_unknown"), QString()));
        if (phase == QLatin1String("copying"))
            lines.append({prefix + QStringLiteral("copying"), QString()});
    } else if (phase == QLatin1String("verified")) {
        lines.append({prefix + QStringLiteral("verified"), QString()});
        const QString digest = str(v.value(QLatin1String("destination_digest")));
        if (!digest.isEmpty())
            lines.append({prefix + QStringLiteral("verified_digest"), digest});
        if (v.value(QLatin1String("copy_ms")).isDouble())
            lines.append({prefix + QStringLiteral("measured_time"),
                          QString::number((v.value(QLatin1String("copy_ms")).toInteger() + 500) / 1000)});
        if (v.value(QLatin1String("used_bytes")).isDouble())
            lines.append({prefix + QStringLiteral("measured_space"), gib(v.value(QLatin1String("used_bytes")).toInteger())});
    } else if (phase == QLatin1String("failed")) {
        if (hasSpace)
            lines.append(space);
        const QString c = str(v.value(QLatin1String("code")));
        const QString family = QStringLiteral("source_reuse_");
        const QString key = c.startsWith(family) ? prefix + QStringLiteral("failed_") + c.mid(family.size()) : QString();
        lines.append({!key.isEmpty() && branding::copyDefaults().contains(key) ? key : prefix + QStringLiteral("failed_unknown"),
                      QString()});
    }
    const QString released = str(v.value(QLatin1String("released")));
    if (!released.isEmpty()) {
        QString destination = str(v.value(QLatin1String("destination")));
        if (destination.startsWith(QLatin1String("containers-storage:")))
            destination = destination.mid(int(qstrlen("containers-storage:")));
        lines.append({prefix + QStringLiteral("released_") + released,
                      released == QLatin1String("remove_failed") ? destination : QString()});
    }
    return lines;
}

// bootc_shared.progress.copy_cancel().
bool copyCancel(const QJsonValue &view, int step)
{
    if (!view.isObject() || step > 0)
        return false;
    const QJsonObject v = view.toObject();
    const QString phase = str(v.value(QLatin1String("phase")));
    return (phase == QLatin1String("planned") || phase == QLatin1String("copying") || phase == QLatin1String("verified"))
        && str(v.value(QLatin1String("released"))).isEmpty();
}

// The install source (#267): bootc_shared.source_check.reuse_source().
QJsonObject reuseSource(bool ok, const QByteArray &probeOutput, const QString &updateRef)
{
    QJsonObject root;
    if (!parseObject(ok, probeOutput, &root))
        return {};
    const QJsonValue live = root.value(QLatin1String("live"));
    if (!live.isObject() || live.toObject().value(QLatin1String("is_live")) != QJsonValue(false))
        return {};
    const QJsonValue storeValue = root.value(QLatin1String("bootc_store"));
    if (!storeValue.isObject())
        return {};
    const QJsonObject store = storeValue.toObject();
    qint64 version = 0;
    if (!integer(store.value(QLatin1String("version")), &version) || version != 1
        || !isTrue(store.value(QLatin1String("available"))) || !store.value(QLatin1String("items")).isArray())
        return {};
    const QString want = plainRef(updateRef);
    if (want.isEmpty())
        return {};
    const QJsonArray items = store.value(QLatin1String("items")).toArray();
    auto roles = [](const QJsonObject &item) {
        QStringList out;
        for (const QJsonValue &r : item.value(QLatin1String("roles")).toArray())
            if (r.isString())
                out << r.toString();
        return out;
    };
    for (const QJsonValue &v : items) {
        const QJsonObject item = v.toObject();
        if (str(item.value(QLatin1String("ref"))) == want && roles(item).contains(QLatin1String("staged")))
            return {};
    }
    static const QRegularExpression digestRe(QStringLiteral("^sha256:[0-9a-f]{64}$"));
    static const QRegularExpression platformRe(QStringLiteral("^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$"));
    for (const QJsonValue &v : items) {
        const QJsonObject item = v.toObject();
        const QString digest = str(item.value(QLatin1String("digest")));
        const QString platform = str(item.value(QLatin1String("platform")));
        if (str(item.value(QLatin1String("ref"))) == want && roles(item).contains(QLatin1String("booted"))
            && str(item.value(QLatin1String("owner"))) == QLatin1String("bootc")
            && str(item.value(QLatin1String("context"))) == QLatin1String("live-host")
            && str(item.value(QLatin1String("storage"))) == QLatin1String("ostree")
            && str(item.value(QLatin1String("availability"))) == QLatin1String("deployed")
            && isTrue(item.value(QLatin1String("matches_machine")))
            && digestRe.match(digest).hasMatch() && platformRe.match(platform).hasMatch())
            return QJsonObject{{QStringLiteral("ref"), want}, {QStringLiteral("digest"), digest},
                               {QStringLiteral("platform"), platform}};
    }
    return {};
}

QJsonObject applyReuse(const QJsonObject &recipe, const QJsonObject &source)
{
    QJsonObject out = recipe;
    if (source.isEmpty())
        return out;
    QString target = str(recipe.value(QLatin1String("targetImgref")));
    if (target.isEmpty())
        target = str(recipe.value(QLatin1String("image")));
    out.insert(QStringLiteral("targetImgref"), target);
    out.insert(QStringLiteral("image"), QString());
    out.insert(QStringLiteral("sourceReuse"), QJsonObject{
        {QStringLiteral("store"), QStringLiteral("bootc")},
        {QStringLiteral("digest"), source.value(QLatin1String("digest"))},
        {QStringLiteral("platform"), source.value(QLatin1String("platform"))},
    });
    QJsonArray experimental;
    for (const QJsonValue &e : recipe.value(QLatin1String("experimental")).toArray())
        if (e.isString())
            experimental.append(e);
    if (!experimental.contains(QJsonValue(QStringLiteral("bootc_store_reuse"))))
        experimental.append(QStringLiteral("bootc_store_reuse"));
    out.insert(QStringLiteral("experimental"), experimental);
    return out;
}

QJsonObject reuseFragment(const QJsonObject &recipe)
{
    QJsonObject out;
    for (const char *key : {"image", "targetImgref", "experimental", "sourceReuse", "composeFsBackend", "filesystem"})
        if (recipe.contains(QLatin1String(key)))
            out.insert(QLatin1String(key), recipe.value(QLatin1String(key)));
    return out;
}

}
