#include "daemonclient.h"

#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocalSocket>

namespace fishermand
{

namespace
{
QString trError(const char *text)
{
    return QCoreApplication::translate("daemon", text);
}
} // namespace

Backend backend()
{
    return qEnvironmentVariable("TUNA_INSTALLER_BACKEND") == QLatin1String("daemon") ? Backend::Daemon
                                                                                     : Backend::Recipe;
}

QString socketPath()
{
    const QString env = qEnvironmentVariable("TUNA_FISHERMAN_SOCKET");
    if (!env.isEmpty())
        return env;
    return QStringLiteral("/run/fisherman/io.tunaos.Fisherman");
}

QString transportLabel(const QString &tran)
{
    const QString lower = tran.toLower();
    if (lower.isEmpty())
        return {};
    if (lower == QLatin1String("nvme"))
        return QStringLiteral("NVMe");
    if (lower == QLatin1String("sata") || lower == QLatin1String("ata"))
        return QStringLiteral("SATA");
    if (lower == QLatin1String("usb"))
        return QStringLiteral("USB");
    if (lower == QLatin1String("scsi"))
        return QStringLiteral("SCSI");
    if (lower == QLatin1String("sas"))
        return QStringLiteral("SAS");
    if (lower == QLatin1String("virtio"))
        return QStringLiteral("VirtIO");
    if (lower == QLatin1String("mmc"))
        return QStringLiteral("MMC");
    if (lower == QLatin1String("ufs"))
        return QStringLiteral("UFS");
    if (lower == QLatin1String("fc"))
        return QStringLiteral("Fibre Channel");
    if (lower == QLatin1String("iscsi"))
        return QStringLiteral("iSCSI");
    if (lower == QLatin1String("ieee1394"))
        return QStringLiteral("FireWire");
    return tran.toUpper();
}

Client::Client(const QString &path)
    : m_path(path)
{
}

QByteArray Client::encodeRequest(const QString &method, const QJsonObject &parameters, bool more)
{
    QJsonObject request{{QStringLiteral("method"), method}, {QStringLiteral("parameters"), parameters}};
    if (more)
        request.insert(QStringLiteral("more"), true);
    return QJsonDocument(request).toJson(QJsonDocument::Compact) + '\0';
}

bool Client::decodeOne(QByteArray &buffer, Reply *reply)
{
    const int end = buffer.indexOf('\0');
    if (end < 0)
        return false;
    const QByteArray raw = buffer.left(end);
    buffer.remove(0, end + 1);
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(raw, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        reply->transportFailed = true;
        return true;
    }
    const QJsonObject o = doc.object();
    reply->parameters = o.value(QLatin1String("parameters")).toObject();
    reply->error = o.value(QLatin1String("error")).toString();
    return true;
}

Reply Client::call(const QString &method, const QJsonObject &parameters, int timeoutMs)
{
    Reply failed;
    QLocalSocket socket;
    socket.connectToServer(m_path);
    if (!socket.waitForConnected(timeoutMs)) {
        failed.transportFailed = true;
        return failed;
    }
    socket.write(encodeRequest(method, parameters, false));
    if (!socket.waitForBytesWritten(timeoutMs)) {
        failed.transportFailed = true;
        return failed;
    }
    QByteArray buffer;
    Reply reply;
    while (!socket.waitForReadyRead(timeoutMs))
        return Reply{.transportFailed = true};
    buffer += socket.readAll();
    // The peer may split the message across reads; keep waiting for the NUL.
    while (!decodeOne(buffer, &reply)) {
        if (socket.atEnd() || !socket.waitForReadyRead(timeoutMs))
            return Reply{.transportFailed = true};
        buffer += socket.readAll();
    }
    socket.disconnectFromServer();
    return reply;
}

Requirements fetchRequirements(Client &client)
{
    Requirements out;
    const Reply reply = client.call(QStringLiteral("io.tunaos.Fisherman.Requirements"), {});
    if (reply.transportFailed) {
        out.error = trError("the installer daemon did not answer");
        return out;
    }
    if (!reply.error.isEmpty()) {
        out.error = reply.error;
        return out;
    }
    out.ok = true;
    out.meets = reply.parameters.value(QLatin1String("meetsRequirements")).toBool();
    for (const QJsonValue &value : reply.parameters.value(QLatin1String("gates")).toArray()) {
        const QJsonObject g = value.toObject();
        Gate gate;
        gate.id = g.value(QLatin1String("id")).toString();
        gate.ok = g.value(QLatin1String("ok")).toBool();
        gate.severity = g.value(QLatin1String("severity")).toString();
        gate.required = g.value(QLatin1String("required")).toString();
        gate.actual = g.value(QLatin1String("actual")).toString();
        gate.message = g.value(QLatin1String("message")).toString();
        gate.action = g.value(QLatin1String("action")).toString();
        out.gates.append(gate);
    }
    return out;
}

Probe fetchProbe(Client &client)
{
    Probe out;
    const Reply reply = client.call(QStringLiteral("io.tunaos.Fisherman.Probe"), {});
    if (reply.transportFailed) {
        out.error = trError("the installer daemon did not answer");
        return out;
    }
    if (!reply.error.isEmpty()) {
        out.error = reply.error;
        return out;
    }
    out.ok = true;
    out.protocolVersion = reply.parameters.value(QLatin1String("protocolVersion")).toInt(-1);
    for (const QJsonValue &value : reply.parameters.value(QLatin1String("disks")).toArray()) {
        const QJsonObject d = value.toObject();
        Disk disk;
        disk.path = d.value(QLatin1String("path")).toString();
        disk.model = d.value(QLatin1String("model")).toString();
        disk.vendor = d.value(QLatin1String("vendor")).toString();
        disk.sizeBytes = static_cast<qint64>(d.value(QLatin1String("sizeBytes")).toDouble());
        disk.sizeLabel = d.value(QLatin1String("sizeLabel")).toString();
        disk.transport = d.value(QLatin1String("transport")).toString();
        disk.removable = d.value(QLatin1String("removable")).toBool();
        disk.eligible = d.value(QLatin1String("eligible")).toBool();
        disk.excludedReason = d.value(QLatin1String("excludedReason")).toString();
        disk.freeBytes = static_cast<qint64>(d.value(QLatin1String("freeBytes")).toDouble(-1));
        disk.minimalSizeBytes = static_cast<qint64>(d.value(QLatin1String("minimalSizeBytes")).toDouble(-1));
        disk.intelRst = d.value(QLatin1String("intelRst")).toBool();
        const QJsonObject e = d.value(QLatin1String("existingData")).toObject();
        disk.existingData.hasPartitionTable = e.value(QLatin1String("hasPartitionTable")).toBool();
        disk.existingData.partitionTableType = e.value(QLatin1String("partitionTableType")).toString();
        disk.existingData.hasLuks = e.value(QLatin1String("hasLuks")).toBool();
        for (const QJsonValue &os : e.value(QLatin1String("operatingSystems")).toArray())
            disk.existingData.operatingSystems.append(os.toString());
        out.disks.append(disk);
    }
    const QJsonObject tpm = reply.parameters.value(QLatin1String("tpm")).toObject();
    out.tpmPresent = tpm.value(QLatin1String("present")).toBool();
    out.tpmVersion = tpm.value(QLatin1String("version")).toString();
    out.tpmUsable = tpm.value(QLatin1String("usable")).toBool();
    const QJsonObject rst = reply.parameters.value(QLatin1String("intelRst")).toObject();
    out.rstDetected = rst.value(QLatin1String("detected")).toBool();
    out.rstMode = rst.value(QLatin1String("mode")).toString();
    for (const QJsonValue &disk : rst.value(QLatin1String("affectedDisks")).toArray())
        out.rstAffectedDisks.append(disk.toString());
    const QJsonObject live = reply.parameters.value(QLatin1String("live")).toObject();
    out.isLive = live.value(QLatin1String("isLive")).toBool();
    out.liveImage = live.value(QLatin1String("liveImage")).toString();
    return out;
}

QStringList unmetFromGates(const QList<Gate> &gates)
{
    QStringList unmet;
    for (const Gate &g : gates) {
        if (g.ok)
            continue;
        unmet.append(g.id == QLatin1String("firmware") ? QStringLiteral("uefi") : g.id);
    }
    return unmet;
}

probe::Result probeResult(const Probe &probe)
{
    probe::Result r;
    if (!probe.ok) {
        r.ok = false;
        r.error = probe.error;
        return r;
    }
    r.ok = true;
    for (const Disk &d : probe.disks) {
        if (!d.eligible)
            continue;
        probe::Disk disk;
        disk.path = d.path;
        disk.model = d.model;
        disk.title = d.model.isEmpty() ? d.path : d.model;
        disk.sizeLabel = d.sizeLabel;
        disk.transportLabel = transportLabel(d.transport);
        disk.removable = d.removable;
        r.disks.append(disk);
    }
    r.tpmUsable = probe.tpmUsable;
    // The unmet requirements ("ram", "cpu", "uefi") come from Requirements(),
    // not from Probe(): the caller fills r.unmet from the gates (the daemon
    // names the firmware gate "firmware", the legacy shape called it "uefi").
    r.isLive = probe.isLive;
    r.liveImage = probe.liveImage;
    return r;
}

} // namespace fishermand
