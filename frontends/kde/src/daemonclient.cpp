#include "daemonclient.h"

#include <QCoreApplication>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocalSocket>
#include <QRegularExpression>
#include <QTimer>

namespace fishermand
{

namespace
{
// The one user-facing daemon error (the disk step shows it with a retry).
// lupdate only extracts a literal source text, so the call sites below
// pass it inline instead of through a helper.
} // namespace

Backend backend()
{
    // The one switch of the four native frontends: `daemon` and `legacy`
    // force a path. Anything else is `auto`: the daemon when its socket is
    // there, the recipe CLI otherwise. `recipe` is the old word for legacy.
    const QString mode = qEnvironmentVariable("TUNA_INSTALLER_BACKEND").trimmed().toLower();
    if (mode == QLatin1String("daemon"))
        return Backend::Daemon;
    if (mode == QLatin1String("legacy") || mode == QLatin1String("recipe"))
        return Backend::Recipe;
    const QFileInfo socket(socketPath());
    return socket.exists() && !socket.isDir() ? Backend::Daemon : Backend::Recipe;
}

QString socketPath()
{
    const QString env = qEnvironmentVariable("TUNA_FISHERMAN_SOCKET");
    if (!env.isEmpty())
        return env;
    const QString dir = qEnvironmentVariable("FISHERMAND_SOCKET_DIR");
    if (!dir.isEmpty())
        return dir + QStringLiteral("/io.tunaos.Fisherman");
    return QStringLiteral("/run/fisherman/io.tunaos.Fisherman");
}

QString socketPath(const QString &interface)
{
    if (interface == QLatin1String("io.tunaos.Fisherman"))
        return socketPath();
    const QString dir = qEnvironmentVariable("FISHERMAND_SOCKET_DIR");
    if (!dir.isEmpty())
        return dir + QLatin1Char('/') + interface;
    // `fishermand --socket-dir` puts the four sockets side by side under
    // their interface names. When the Fisherman socket was moved and such a
    // sibling is there, use it. A lone moved socket (the mock serves every
    // interface on each) answers for all of them.
    const QString env = qEnvironmentVariable("TUNA_FISHERMAN_SOCKET");
    if (!env.isEmpty()) {
        const QString sibling = QFileInfo(env).absolutePath() + QLatin1Char('/') + interface;
        return QFileInfo::exists(sibling) ? sibling : env;
    }
    return QStringLiteral("/run/systemd/") + interface;
}

QString normalHandoffMode(const QString &mode)
{
    // The wire word is soft_reboot; the ruling on #512 wrote soft-reboot.
    // Both are read. A missing or unknown mode is a plain reboot.
    QString m = mode.trimmed().toLower();
    m.replace(QLatin1Char('-'), QLatin1Char('_'));
    if (m == QLatin1String("migrate") || m == QLatin1String("soft_reboot"))
        return m;
    return QStringLiteral("reboot");
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
    reply->continues = o.value(QLatin1String("continues")).toBool();
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

QList<Reply> Client::callMore(const QString &method, const QJsonObject &parameters, int timeoutMs)
{
    QList<Reply> out;
    QLocalSocket socket;
    socket.connectToServer(m_path);
    if (!socket.waitForConnected(timeoutMs)) {
        out.append(Reply{.transportFailed = true});
        return out;
    }
    socket.write(encodeRequest(method, parameters, true));
    if (!socket.waitForBytesWritten(timeoutMs)) {
        out.append(Reply{.transportFailed = true});
        return out;
    }
    QByteArray buffer;
    while (true) {
        Reply reply;
        while (!decodeOne(buffer, &reply)) {
            if (!socket.waitForReadyRead(timeoutMs)) {
                out.append(Reply{.transportFailed = true});
                socket.disconnectFromServer();
                return out;
            }
            buffer += socket.readAll();
        }
        out.append(reply);
        if (reply.transportFailed || !reply.error.isEmpty() || !reply.continues)
            break;
    }
    socket.disconnectFromServer();
    return out;
}

Requirements fetchRequirements(Client &client)
{
    Requirements out;
    const Reply reply = client.call(QStringLiteral("io.tunaos.Fisherman.Requirements"), {});
    if (reply.transportFailed) {
        out.error = QCoreApplication::translate("daemon", "the installer daemon did not answer");
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
        out.error = QCoreApplication::translate("daemon", "the installer daemon did not answer");
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
    // A missing handoff object means reboot (ruling on #512).
    const QJsonObject handoff = reply.parameters.value(QLatin1String("handoff")).toObject();
    out.handoffMode = normalHandoffMode(handoff.value(QLatin1String("mode")).toString());
    out.handoffReason = handoff.value(QLatin1String("reason")).toString();
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

bool tooSmall(const Disk &disk)
{
    return disk.sizeBytes > 0 && disk.minimalSizeBytes > 0 && disk.sizeBytes < disk.minimalSizeBytes;
}

QString diskTitle(const Disk &disk)
{
    // virtio puts its PCI vendor id ("0x1af4") where a vendor belongs. A disk
    // that names neither vendor nor model is called after its bus; the row
    // has its path and its size below.
    static const QRegularExpression pciId(QStringLiteral("^0[xX][0-9a-fA-F]+$"));
    for (const QString &name : {disk.model.trimmed(), disk.vendor.trimmed()}) {
        if (!name.isEmpty() && !pciId.match(name).hasMatch())
            return name;
    }
    const QString bus = transportLabel(disk.transport);
    return bus.isEmpty() ? disk.path : QCoreApplication::translate("fishermand", "%1 disk").arg(bus);
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
        if (!d.eligible || tooSmall(d))
            continue;
        probe::Disk disk;
        disk.path = d.path;
        disk.model = d.model;
        disk.title = diskTitle(d);
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

QList<ValidationProblem> validationProblems(const QJsonObject &parameters)
{
    QList<ValidationProblem> out;
    for (const QJsonValue &value : parameters.value(QLatin1String("errors")).toArray()) {
        const QJsonObject e = value.toObject();
        out.append({e.value(QLatin1String("field")).toString(), e.value(QLatin1String("code")).toString(),
                    e.value(QLatin1String("message")).toString()});
    }
    return out;
}

AsyncClient::AsyncClient(const QString &path, QObject *parent)
    : QObject(parent)
    , m_path(path)
{
}

AsyncClient::~AsyncClient()
{
    abort();
}

void AsyncClient::call(const QString &method, const QJsonObject &parameters, bool more, int timeoutMs)
{
    abort();
    if (timeoutMs > 0) {
        // A daemon behind polkit can wait for a person. It must not wait
        // for ever, and the wizard must not either.
        const int generation = ++m_generation;
        QTimer::singleShot(timeoutMs, this, [this, generation] {
            if (m_finished || generation != m_generation)
                return;
            Reply reply;
            reply.transportFailed = true;
            reply.timedOut = true;
            Q_EMIT replyReceived(reply);
            finish();
        });
    } else {
        ++m_generation;
    }
    m_buffer.clear();
    m_streaming = more;
    m_finished = false;
    m_socket = new QLocalSocket(this);
    connect(m_socket, &QLocalSocket::readyRead, this, &AsyncClient::onReadyRead);
    connect(m_socket, &QLocalSocket::disconnected, this, [this] {
        if (!m_finished) {
            Reply reply;
            reply.transportFailed = true;
            Q_EMIT replyReceived(reply);
            finish();
        }
    });
    connect(m_socket, &QLocalSocket::errorOccurred, this, [this](QLocalSocket::LocalSocketError) {
        if (!m_finished && m_socket->state() == QLocalSocket::UnconnectedState) {
            Reply reply;
            reply.transportFailed = true;
            Q_EMIT replyReceived(reply);
            finish();
        }
    });
    m_socket->connectToServer(m_path);
    // The error handler above can have ended the call already.
    if (!m_socket)
        return;
    // A local socket connects at once or not at all: this does not wait.
    if (!m_socket->waitForConnected(1000)) {
        // No daemon at the path. Say so now, not when the time limit ends.
        if (!m_finished) {
            Reply reply;
            reply.transportFailed = true;
            Q_EMIT replyReceived(reply);
            finish();
        }
        return;
    }
    m_socket->write(Client::encodeRequest(method, parameters, more));
    m_socket->flush();
}

void AsyncClient::abort()
{
    if (!m_socket)
        return;
    QLocalSocket *socket = m_socket;
    m_socket = nullptr;
    m_finished = true;
    socket->disconnect();
    socket->abort();
    socket->deleteLater();
}

void AsyncClient::finish()
{
    if (m_finished)
        return;
    m_finished = true;
    if (m_socket) {
        QLocalSocket *socket = m_socket;
        m_socket = nullptr;
        socket->disconnect();
        socket->deleteLater();
    }
    Q_EMIT callFinished();
}

void AsyncClient::onReadyRead()
{
    if (!m_socket)
        return;
    m_buffer += m_socket->readAll();
    while (!m_finished) {
        Reply reply;
        if (!Client::decodeOne(m_buffer, &reply))
            break;
        Q_EMIT replyReceived(reply);
        if (reply.transportFailed || !reply.error.isEmpty() || !m_streaming || !reply.continues) {
            finish();
            break;
        }
    }
}

InstallStream::InstallStream(const QString &path, QObject *parent)
    : QObject(parent)
    , m_path(path)
{
}

void InstallStream::start(const QJsonObject &config, bool confirmed)
{
    if (m_client)
        return;
    m_terminalSent = false;
    m_client = new AsyncClient(m_path, this);
    connect(m_client, &AsyncClient::replyReceived, this, [this](const Reply &reply) {
        if (!reply.error.isEmpty()) {
            if (!m_terminalSent) {
                m_terminalSent = true;
                Q_EMIT streamFinished(QStringLiteral("error"), reply.error);
            }
            return;
        }
        if (reply.transportFailed) {
            if (!m_terminalSent) {
                m_terminalSent = true;
                Q_EMIT streamFinished(QStringLiteral("error"),
                                       QStringLiteral("the installer daemon did not answer"));
            }
            return;
        }
        const QJsonObject event = reply.parameters;
        Q_EMIT eventReceived(event);
        const QString kind = event.value(QLatin1String("event")).toString();
        if (kind == QLatin1String("complete") || kind == QLatin1String("failed")
            || kind == QLatin1String("cancelled")) {
            if (!m_terminalSent) {
                m_terminalSent = true;
                Q_EMIT streamFinished(kind, QString());
            }
        }
    });
    connect(m_client, &AsyncClient::callFinished, this, [this] {
        if (m_client) {
            m_client->deleteLater();
            m_client = nullptr;
        }
        if (!m_terminalSent) {
            m_terminalSent = true;
            Q_EMIT streamFinished(QStringLiteral("error"),
                                   QStringLiteral("the installer daemon did not answer"));
        }
    });
    const QJsonObject args{{QStringLiteral("config"), config}, {QStringLiteral("confirmed"), confirmed}};
    m_client->call(QStringLiteral("io.tunaos.Fisherman.Install"), args, true);
}

void InstallStream::cancel()
{
    // Cancel travels on its own connection while Install streams on this one.
    auto *client = new AsyncClient(m_path, this);
    connect(client, &AsyncClient::replyReceived, this, [client, this](const Reply &reply) {
        Q_EMIT cancelFinished(reply.ok() && reply.parameters.value(QLatin1String("wasInstalling")).toBool());
        client->deleteLater();
    });
    connect(client, &AsyncClient::callFinished, client, &QObject::deleteLater);
    client->call(QStringLiteral("io.tunaos.Fisherman.Cancel"), {}, false);
}

namespace
{
QString replyError(const Reply &reply)
{
    if (reply.transportFailed)
        return QCoreApplication::translate("daemon", "the installer daemon did not answer");
    return reply.error;
}
} // namespace

QList<CandidateDevice> fetchCandidateDevices(Client &client, QString *error)
{
    QList<CandidateDevice> out;
    const QList<Reply> replies = client.callMore(QStringLiteral("io.systemd.SysInstall.ListCandidateDevices"),
                                                 QJsonObject{{QStringLiteral("definitions"), QJsonArray{}}});
    for (const Reply &reply : replies) {
        if (!reply.ok()) {
            if (error)
                *error = replyError(reply);
            return {};
        }
        const QJsonObject p = reply.parameters;
        if (p.isEmpty())
            continue;
        CandidateDevice device;
        device.node = p.value(QLatin1String("node")).toString();
        device.vendor = p.value(QLatin1String("vendor")).toString();
        device.model = p.value(QLatin1String("model")).toString();
        device.subsystem = p.value(QLatin1String("subsystem")).toString();
        device.sizeBytes = static_cast<qint64>(p.value(QLatin1String("sizeBytes")).toDouble(-1));
        device.fit = p.value(QLatin1String("fit")).toString();
        device.minimalSizeBytes = static_cast<qint64>(p.value(QLatin1String("minimalSizeBytes")).toDouble(-1));
        device.currentSizeBytes = static_cast<qint64>(p.value(QLatin1String("currentSizeBytes")).toDouble(-1));
        device.action = p.value(QLatin1String("action")).toString();
        if (!device.node.isEmpty())
            out.append(device);
    }
    return out;
}

QList<ValidationProblem> validateConfig(Client &client, const QJsonObject &config, bool partial, QString *error)
{
    QJsonObject args{{QStringLiteral("config"), config}};
    if (partial)
        args.insert(QStringLiteral("partial"), true);
    const Reply reply = client.call(QStringLiteral("io.tunaos.Fisherman.Validate"), args);
    if (!reply.ok()) {
        if (error)
            *error = replyError(reply);
        return {};
    }
    return validationProblems(reply.parameters);
}

QList<ValidationProblem> configureTarget(Client &client, const QJsonObject &args, QString *error)
{
    const Reply reply = client.call(QStringLiteral("io.tunaos.Fisherman.ConfigureTarget"), args);
    if (!reply.ok()) {
        if (error)
            *error = replyError(reply);
        return {};
    }
    return validationProblems(reply.parameters);
}

QString makeRecoveryKey(Client &client, QString *error)
{
    const Reply reply = client.call(QStringLiteral("io.systemd.CryptEnroll.MakeRecoveryKey"), {});
    if (!reply.ok()) {
        if (error)
            *error = replyError(reply);
        return {};
    }
    return reply.parameters.value(QLatin1String("recoveryKey")).toString();
}

Reply enrollRecoveryKey(Client &client, const QString &node, const QString &recoveryKey, const QString &unlockPassword)
{
    QJsonObject args{{QStringLiteral("node"), node},
                     {QStringLiteral("mechanism"), QStringLiteral("recovery")},
                     {QStringLiteral("recoveryKey"), recoveryKey},
                     // Always sent: a TPM install has the empty password
                     // that the installer set, and the daemon needs to hear
                     // it (gnome-setup does the same).
                     {QStringLiteral("unlockPassword"), unlockPassword}};
    return client.call(QStringLiteral("io.systemd.CryptEnroll.Enroll"), args);
}

Reply callHandoff(Client &client)
{
    // No mode argument: the daemon decided it in Probe (ruling on #512).
    return client.call(QStringLiteral("io.tunaos.Fisherman.Handoff"), {});
}

Reply callCancel(Client &client)
{
    return client.call(QStringLiteral("io.tunaos.Fisherman.Cancel"), {});
}

Reply callShutdown(Client &client, const QString &verb)
{
    return client.call(QStringLiteral("io.systemd.Shutdown.") + verb, {});
}

QString encryptionWireType(const QString &recipeType)
{
    QString type = recipeType.isEmpty() ? QStringLiteral("none") : recipeType;
    type.replace(QLatin1Char('-'), QLatin1Char('_'));
    return type;
}

QJsonObject installConfig(const Recipe &recipe, const QString &installMode, bool partial)
{
    QJsonObject config;
    if (!recipe.disk.isEmpty())
        config.insert(QStringLiteral("disk"), recipe.disk);
    if (installMode == QLatin1String("erase") || installMode == QLatin1String("free_space"))
        config.insert(QStringLiteral("installMode"), installMode);
    QJsonObject encryption{{QStringLiteral("type"), encryptionWireType(recipe.encryption.type)}};
    // The passphrase goes in the field check too: the daemon has rules for
    // it, as `fisherman validate` has.
    if (Recipe::needsPassphrase(recipe.encryption.type) && !recipe.encryption.passphrase.isEmpty())
        encryption.insert(QStringLiteral("passphrase"), recipe.encryption.passphrase);
    config.insert(QStringLiteral("encryption"), encryption);
    if (recipe.userRequired && !recipe.user.username.isEmpty()) {
        QJsonObject user{{QStringLiteral("username"), recipe.user.username}};
        if (!recipe.user.fullname.isEmpty())
            user.insert(QStringLiteral("fullName"), recipe.user.fullname);
        if (!partial && !recipe.user.password.isEmpty())
            user.insert(QStringLiteral("password"), recipe.user.password);
        // The daemon has no group list: membership of wheel is `admin`.
        user.insert(QStringLiteral("admin"), recipe.user.groups.contains(QStringLiteral("wheel")));
        config.insert(QStringLiteral("user"), user);
    }
    if (!recipe.hostname.isEmpty())
        config.insert(QStringLiteral("hostname"), recipe.hostname);
    return config;
}

QJsonObject targetChoices(const Recipe &recipe, bool locationTouched, bool locationServices)
{
    QJsonObject choices;
    const QJsonObject config = installConfig(recipe, QString());
    if (config.contains(QLatin1String("user")))
        choices.insert(QStringLiteral("user"), config.value(QLatin1String("user")));
    if (!recipe.hostname.isEmpty())
        choices.insert(QStringLiteral("hostname"), recipe.hostname);
    if (!recipe.locale.isEmpty())
        choices.insert(QStringLiteral("locale"), recipe.locale);
    if (!recipe.keyboardLayout.isEmpty())
        choices.insert(QStringLiteral("keymap"), recipe.keyboardLayout);
    if (!recipe.timezone.isEmpty())
        choices.insert(QStringLiteral("timeZone"), recipe.timezone);
    if (locationTouched)
        choices.insert(QStringLiteral("privacy"),
                       QJsonObject{{QStringLiteral("locationServices"), locationServices}});
    return choices;
}

QJsonObject eventToLine(const QJsonObject &event)
{
    const QString kind = event.value(QLatin1String("event")).toString();
    const QString stepId = event.value(QLatin1String("stepId")).toString();
    const QString message = event.value(QLatin1String("message")).toString();
    const QJsonValue overall = event.value(QLatin1String("overallPct"));
    QJsonObject line;
    if (kind == QLatin1String("step_started")) {
        line.insert(QStringLiteral("type"), QStringLiteral("step"));
        line.insert(QStringLiteral("step"), event.value(QLatin1String("stepIndex")).toInt());
        line.insert(QStringLiteral("total_steps"), event.value(QLatin1String("totalSteps")).toInt());
        line.insert(QStringLiteral("step_name"), message.isEmpty() ? stepId : message);
        line.insert(QStringLiteral("step_id"), stepId);
    } else if (kind == QLatin1String("progress")) {
        line.insert(QStringLiteral("type"), QStringLiteral("substep"));
        line.insert(QStringLiteral("message"), message);
    } else if (kind == QLatin1String("warning")) {
        line.insert(QStringLiteral("type"), QStringLiteral("info"));
        line.insert(QStringLiteral("message"), message.isEmpty() ? stepId : message);
    } else if (kind == QLatin1String("complete")) {
        line.insert(QStringLiteral("type"), QStringLiteral("complete"));
        line.insert(QStringLiteral("message"), message);
    } else if (kind == QLatin1String("failed")) {
        line.insert(QStringLiteral("type"), QStringLiteral("error"));
        line.insert(QStringLiteral("message"), message);
        line.insert(QStringLiteral("code"), event.value(QLatin1String("reason")).toString());
        line.insert(QStringLiteral("step_id"), stepId);
        line.insert(QStringLiteral("disk_changed"), stepId != QLatin1String("validate_device"));
    } else {
        // step_finished and cancelled move no bar and add no line.
        return {};
    }
    if (overall.isDouble() && kind != QLatin1String("failed"))
        line.insert(QStringLiteral("overall_pct"), kind == QLatin1String("complete") ? 100 : overall.toInt());
    return line;
}

} // namespace fishermand
