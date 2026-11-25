#pragma once

// Varlink client for fishermand, the installer daemon
// (tuna-os/fisherman#512, fisherman/docs/FISHERMAND.md).
//
// This is the recipe from shared/client/cpp/varlinkclient.h shaped for this
// frontend: unary calls block (the controller reads Requirements and Probe
// once at startup, off of nothing), while the install stream stays
// asynchronous. The streaming half arrives with the install page.
//
// Passphrases, passwords and recovery keys pass through `parameters`. This
// file never logs a request or a reply; an error keeps its name only.

#include <QByteArray>
#include <QJsonObject>
#include <QList>
#include <QObject>
#include <QString>
#include <QStringList>

#include "probe.h"
#include "recipe.h"

class QLocalSocket;

namespace fishermand
{

// Which backend the frontend talks to. Recipe keeps the `fisherman -`
// subprocess with the recipe on stdin; Daemon talks to fishermand over
// Varlink. TUNA_INSTALLER_BACKEND selects it, the same switch as the Niri,
// XFCE and COSMIC frontends: `daemon`, `legacy`, or `auto` (the default:
// the daemon when its socket is there). Read once per call so tests can
// flip it.
enum class Backend { Recipe, Daemon };
Backend backend();

// Where the io.tunaos.Fisherman socket lives. Every daemon socket serves
// every interface, so one path is enough. TUNA_FISHERMAN_SOCKET wins, else
// the daemon's own default (--fisherman-socket).
QString socketPath();
// The socket of one interface (io.systemd.CryptEnroll, io.systemd.Shutdown,
// io.systemd.SysInstall). The real daemon serves one interface on each
// socket. FISHERMAND_SOCKET_DIR moves all four; else a sibling of the
// moved Fisherman socket; else /run/systemd/<interface>.
QString socketPath(const QString &interface);
// migrate, soft_reboot or reboot for any spelling of a handoff mode.
QString normalHandoffMode(const QString &mode);

// The human bus name for an lsblk TRAN value. A port of fisherman's
// TransportLabel (fisherman/internal/probe/disks.go): the daemon Probe
// carries the raw `transport`, the legacy probe carried the label, and the
// disk rows must read the same either way.
QString transportLabel(const QString &tran);

struct Reply {
    QJsonObject parameters;
    // An error reply keeps its name only: the parameters can hold a secret.
    QString error;
    // The socket failed or the peer sent junk. parameters is empty.
    bool transportFailed = false;
    // A streaming reply with more to come (`continues` on the wire).
    bool continues = false;
    // No reply came inside the caller's time limit. transportFailed is set
    // too.
    bool timedOut = false;
    bool ok() const { return !transportFailed && error.isEmpty(); }
};

// One blocking unary call. No signals, no moc step: waitFor* does the
// waiting. A Client owns nothing between calls; make one per call.
class Client
{
public:
    explicit Client(const QString &path);
    Reply call(const QString &method, const QJsonObject &parameters, int timeoutMs = 10000);
    // A blocking streaming call: every reply until one without `continues`.
    QList<Reply> callMore(const QString &method, const QJsonObject &parameters, int timeoutMs = 10000);

    // Test seams: the wire format without the socket.
    static QByteArray encodeRequest(const QString &method, const QJsonObject &parameters, bool more);
    // Pops one NUL-terminated message off the front of `buffer`. False when
    // no complete message is there yet; junk sets transportFailed.
    static bool decodeOne(QByteArray &buffer, Reply *reply);

private:
    QString m_path;
};

// One requirements gate, as Requirements() answers it.
struct Gate {
    QString id; // "ram", "cpu", "firmware"
    bool ok = false;
    QString severity; // "block" or "warn"
    QString required;
    QString actual;
    QString message;
    QString action; // "power_off", "firmware_setup" or ""
};

struct Requirements {
    bool ok = false;
    QString error; // why the call failed; empty when ok
    bool meets = false;
    QList<Gate> gates;
};

// What is already on a daemon disk, for the wipe-or-free page.
struct ExistingData {
    bool hasPartitionTable = false;
    QString partitionTableType;
    QStringList operatingSystems;
    bool hasLuks = false;
};

struct Disk {
    QString path;
    QString model;
    QString vendor;
    qint64 sizeBytes = 0;
    QString sizeLabel; // the daemon's label, verbatim, like the legacy probe's
    QString transport; // raw lsblk TRAN value
    bool removable = false;
    bool eligible = false;
    QString excludedReason;
    qint64 freeBytes = -1;
    qint64 minimalSizeBytes = -1;
    bool intelRst = false;
    ExistingData existingData;
};

// The disk cannot hold the install at all (shared/flow disk status
// too-small): it is listed as unusable and never selectable.
bool tooSmall(const Disk &disk);

// The legacy unmet ids ("ram", "cpu", "uefi") from the daemon gates: a gate
// that is not ok contributes its id, with "firmware" renamed to "uefi".
QStringList unmetFromGates(const QList<Gate> &gates);

struct Probe {
    bool ok = false;
    QString error; // why the call failed; empty when ok
    int protocolVersion = -1;
    QList<Disk> disks;
    bool tpmPresent = false;
    QString tpmVersion;
    bool tpmUsable = false;
    bool rstDetected = false;
    QString rstMode;
    QStringList rstAffectedDisks;
    bool isLive = false;
    QString liveImage;
    // How the daemon will hand the installed system over (ruling on #512):
    // migrate, soft_reboot or reboot. A missing field means reboot.
    QString handoffMode;
    QString handoffReason;
};

Requirements fetchRequirements(Client &client);
Probe fetchProbe(Client &client);

// The daemon facts in the legacy probe::Result shape: eligible disks only,
// titles and size labels verbatim, unmet as "ram", "cpu", "uefi". Lets the
// disk list and the gates run on either backend without a second code path.
// offlineImages stays empty: the daemon Probe names no offline stores.
probe::Result probeResult(const Probe &probe);

// One io.systemd.SysInstall candidate, as ListCandidateDevices streams it.
struct CandidateDevice {
    QString node;
    QString vendor;
    QString model;
    QString subsystem;
    qint64 sizeBytes = -1;
    QString fit;
    qint64 minimalSizeBytes = -1;
    qint64 currentSizeBytes = -1;
    QString action;
};

// Validation problems as data: [{field, code, message}].
struct ValidationProblem {
    QString field;
    QString code;
    QString message;
};
QList<ValidationProblem> validationProblems(const QJsonObject &parameters);

// A non-blocking Varlink call on its own connection. One call at a time;
// `more` streams replies until one arrives without `continues`.
class AsyncClient : public QObject
{
    Q_OBJECT
public:
    explicit AsyncClient(const QString &path, QObject *parent = nullptr);
    ~AsyncClient() override;
    // `timeoutMs` > 0 ends a call that got no reply in that time with a
    // reply that has timedOut set. A stream that is open has no limit.
    void call(const QString &method, const QJsonObject &parameters, bool more, int timeoutMs = 0);
    void abort();
    bool busy() const { return m_socket != nullptr; }

Q_SIGNALS:
    void replyReceived(const fishermand::Reply &reply);
    void callFinished();

private:
    void onReadyRead();
    void finish();

    QString m_path;
    QLocalSocket *m_socket = nullptr;
    QByteArray m_buffer;
    bool m_streaming = false;
    bool m_finished = true;
    int m_generation = 0;
};

// io.tunaos.Fisherman.Install as an event stream, plus Cancel on a second
// connection (the wire allows one call per connection).
class InstallStream : public QObject
{
    Q_OBJECT
public:
    explicit InstallStream(const QString &path, QObject *parent = nullptr);
    void start(const QJsonObject &config, bool confirmed);
    // Asks the daemon to stop and clean up. Safe while idle.
    void cancel();
    bool running() const { return m_client != nullptr; }

Q_SIGNALS:
    void eventReceived(const QJsonObject &event);
    // terminal is complete, failed, cancelled or error. For error,
    // errorName is the Varlink error or a transport note.
    void streamFinished(const QString &terminal, const QString &errorName);
    void cancelFinished(bool wasInstalling);

private:
    QString m_path;
    AsyncClient *m_client = nullptr;
    bool m_terminalSent = false;
};

// The remaining unary daemon operations. All block; callers run them off
// the UI thread or accept the short wait at startup.
QList<CandidateDevice> fetchCandidateDevices(Client &client, QString *error = nullptr);
QList<ValidationProblem> validateConfig(Client &client, const QJsonObject &config, bool partial, QString *error = nullptr);
QList<ValidationProblem> configureTarget(Client &client, const QJsonObject &args, QString *error = nullptr);
QString makeRecoveryKey(Client &client, QString *error = nullptr);
Reply enrollRecoveryKey(Client &client, const QString &node, const QString &recoveryKey, const QString &unlockPassword);
Reply callHandoff(Client &client);
Reply callCancel(Client &client);
// io.systemd.Shutdown: `verb` is Reboot, PowerOff or SoftReboot.
Reply callShutdown(Client &client, const QString &verb);

// The recipe's encryption type in the daemon's spelling: the recipe has
// dashes (shared/recipe/encryption-choices.json), the wire has underscores.
QString encryptionWireType(const QString &recipeType);

// The Install and Validate `config` for the wizard's recipe: disk, install
// mode, encryption, user and hostname. The file system, the image and the
// region are not install configuration. `installMode` is erase or
// free_space; empty leaves the key out. `partial` is the field check: it
// leaves out the account password, which no rule reads.
QJsonObject installConfig(const Recipe &recipe, const QString &installMode, bool partial = false);

// The ConfigureTarget choices: user, hostname, locale, keymap and time zone,
// each only when the wizard has a value. `privacy.locationServices` is sent
// only when the person changed the switch (`locationTouched`).
QJsonObject targetChoices(const Recipe &recipe, bool locationTouched, bool locationServices);

// One line of the legacy progress protocol (shared/progress/README.md) for
// a daemon Install event, so the progress page keeps one parser, one bar
// and one log. An event with nothing to show gives an empty object.
// `disk_changed` on an error line is false only for validate_device: after
// that step the disk may hold a new partition table.
QJsonObject eventToLine(const QJsonObject &event);

} // namespace fishermand
