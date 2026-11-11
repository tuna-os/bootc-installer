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

Request fromRecipe(const QJsonObject &recipe, bool isLive)
{
    Request r;
    r.source = str(recipe.value(QLatin1String("image")));
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

}
