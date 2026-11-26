// The daemon flow of the wizard against the mock fishermand
// (tuna-os/fisherman, fisherman/docs/FISHERMAND.md).
//
// Each scenario test starts `fishermand --mock --scenario <name>` on sockets
// in a temporary directory and drives InstallerController the way the QML
// does: facts, the skip rules, Validate, ConfigureTarget, the Install
// stream, Cancel, the recovery key, the handoff and the restart. Nothing
// here touches a disk: the mock serves scripted data.
//
// The mock binary: $FISHERMAND_BIN, then <build dir>/fishermand, then
// <source dir>/build/fishermand, then `fishermand` on PATH. Without one the
// scenario tests are skipped. The tests of the pure mapping always run.
//
// SPDX-License-Identifier: GPL-3.0-only

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QElapsedTimer>
#include <QJsonObject>
#include <QLocalServer>
#include <QProcess>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QtTest>

#include <memory>

#include "daemonclient.h"
#include "diskmodel.h"
#include "installercontroller.h"
#include "probe.h"

namespace
{

QString mockBinary()
{
    const QString env = qEnvironmentVariable("FISHERMAND_BIN");
    if (!env.isEmpty())
        return QFileInfo(env).isExecutable() ? env : QString();
    for (const QString &path : {QStringLiteral(KDE_BINARY_DIR "/fishermand"),
                                QStringLiteral(KDE_SOURCE_DIR "/build/fishermand")}) {
        if (QFileInfo(path).isExecutable())
            return path;
    }
    return QStandardPaths::findExecutable(QStringLiteral("fishermand"));
}

// One mock daemon on its own socket directory. The environment points the
// frontend at it for the life of the object.
class Mock
{
public:
    explicit Mock(const QString &scenario)
    {
        if (!m_dir.isValid())
            return;
        m_process.setProgram(mockBinary());
        m_process.setArguments({QStringLiteral("--mock"), QStringLiteral("--scenario"), scenario,
                                QStringLiteral("--socket-dir"), m_dir.path(),
                                QStringLiteral("--step-delay"), QStringLiteral("2ms")});
        m_process.setStandardErrorFile(QProcess::nullDevice());
        m_process.setStandardOutputFile(QProcess::nullDevice());
        m_process.start();
        if (!m_process.waitForStarted(10000))
            return;
        const QString socket = m_dir.filePath(QStringLiteral("io.tunaos.Fisherman"));
        for (int i = 0; i < 200 && !QFileInfo::exists(socket); i++)
            QTest::qWait(25);
        m_ok = QFileInfo::exists(socket);
        qputenv("TUNA_INSTALLER_BACKEND", "daemon");
        qputenv("FISHERMAND_SOCKET_DIR", m_dir.path().toLocal8Bit());
        qunsetenv("TUNA_FISHERMAN_SOCKET");
    }
    ~Mock()
    {
        m_process.terminate();
        if (!m_process.waitForFinished(5000))
            m_process.kill();
        m_process.waitForFinished(5000);
        qputenv("TUNA_INSTALLER_BACKEND", "legacy");
        qunsetenv("FISHERMAND_SOCKET_DIR");
    }
    bool ok() const { return m_ok; }
    QString dir() const { return m_dir.path(); }

private:
    QTemporaryDir m_dir;
    QProcess m_process;
    bool m_ok = false;
};

const QRegularExpression &keyShape()
{
    // shared/flow/screens.yaml, test_contract.recovery_key_shape.
    static const QRegularExpression re(QStringLiteral("^[a-z]{6,10}(-[a-z]{6,10}){7}$"));
    return re;
}

} // namespace

// The calls below do not block: each test waits for the answer.
#define ENROLL(c)                                                                                  \
    (c).enrollRecoveryKey();                                                                       \
    QTRY_VERIFY_WITH_TIMEOUT(!(c).recoveryBusy(), 15000)
#define HANDOFF(c)                                                                                 \
    (c).handoff();                                                                                 \
    QTRY_VERIFY_WITH_TIMEOUT((c).handoffState() != QStringLiteral("starting"), 15000)
#define REBOOT(c)                                                                                  \
    (c).reboot();                                                                                  \
    QTRY_VERIFY_WITH_TIMEOUT(!(c).shutdownBusy(), 15000)
#define RECOVERY_KEY(c) QTRY_VERIFY_WITH_TIMEOUT(!(c).recoveryBusy(), 15000)

#define NEED_MOCK(scenario)                                                                        \
    if (mockBinary().isEmpty()) {                                                                  \
        if (qEnvironmentVariableIsSet("TUNA_REQUIRE_FISHERMAND"))                                  \
            QFAIL("TUNA_REQUIRE_FISHERMAND is set and there is no mock fishermand");               \
        QSKIP("no mock fishermand: set FISHERMAND_BIN (go build ./fisherman/cmd/fishermand)");     \
    }                                                                                              \
    Mock mock(QStringLiteral(scenario));                                                           \
    QVERIFY2(mock.ok(), "the mock daemon did not open its sockets")

class DaemonTest : public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void initTestCase();
    void init();

    // The switch and the mapping: no daemon needed.
    void backendSwitch();
    void socketPaths();
    void handoffModeSpellings();
    void handoffModeSharedCases();
    void installConfigMapsTheRecipe();
    void privacyOnlyWhenChanged();
    void eventsBecomeProgressLines();
    void firstBootToolDetection();
    void legacyBackendKeepsTheRecipePath();

    // One test per mock scenario.
    void scenarioHappy();
    void slowDaemonDoesNotBlock();
    void scenarioNoTpm();
    void scenarioExistingData();
    void scenarioTightSpace();
    void scenarioRst();
    void scenarioDeviceLost();
    void scenarioRepartError();
    void scenarioCancel();
    void scenarioHandoffMigrate();
    void scenarioHandoffSoftReboot();
    void scenarioInhibitor();
    void shutdownVerbs();
    void scenarioLowRam();

    // Failure states that need no scenario of their own.
    void daemonValidatesFields();
    void invalidConfigStopsBeforeInstall();
    void daemonUnreachable();
    void plasmaSetupOwnsTheAccount();
    void recoveryKeyStaysOutOfTheLog();

private:
    QTemporaryDir m_home;
};

void DaemonTest::initTestCase()
{
    QVERIFY(m_home.isValid());
    // The install log goes under the data location: keep it out of $HOME.
    qputenv("XDG_DATA_HOME", m_home.filePath(QStringLiteral("data")).toLocal8Bit());
    qputenv("XDG_CACHE_HOME", m_home.filePath(QStringLiteral("cache")).toLocal8Bit());
    qputenv("BOOTC_INSTALLER_PRODUCT_NAME", "Marlin");
    if (mockBinary().isEmpty())
        qWarning("no mock fishermand found: the scenario tests are skipped");
}

void DaemonTest::init()
{
    qputenv("TUNA_INSTALLER_BACKEND", "legacy");
    qunsetenv("TUNA_FISHERMAN_SOCKET");
    qunsetenv("FISHERMAND_SOCKET_DIR");
    qunsetenv("TUNA_FIRSTBOOT_TOOL");
    qunsetenv(probe::FAKE_ENV);
}

void DaemonTest::backendSwitch()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString socket = dir.filePath(QStringLiteral("io.tunaos.Fisherman"));
    qputenv("TUNA_FISHERMAN_SOCKET", socket.toLocal8Bit());

    // An explicit value wins, whatever is on disk.
    qputenv("TUNA_INSTALLER_BACKEND", "daemon");
    QCOMPARE(fishermand::backend(), fishermand::Backend::Daemon);
    qputenv("TUNA_INSTALLER_BACKEND", " Daemon ");
    QCOMPARE(fishermand::backend(), fishermand::Backend::Daemon);
    qputenv("TUNA_INSTALLER_BACKEND", "legacy");
    QCOMPARE(fishermand::backend(), fishermand::Backend::Recipe);
    // The old word of this frontend.
    qputenv("TUNA_INSTALLER_BACKEND", "recipe");
    QCOMPARE(fishermand::backend(), fishermand::Backend::Recipe);

    // auto, unset and unknown: the daemon only when its socket is there.
    for (const char *value : {"auto", "", "something-else"}) {
        qputenv("TUNA_INSTALLER_BACKEND", value);
        QCOMPARE(fishermand::backend(), fishermand::Backend::Recipe);
    }
    qunsetenv("TUNA_INSTALLER_BACKEND");
    QCOMPARE(fishermand::backend(), fishermand::Backend::Recipe);
    QFile file(socket);
    QVERIFY(file.open(QIODevice::WriteOnly));
    file.close();
    QCOMPARE(fishermand::backend(), fishermand::Backend::Daemon);
    qputenv("TUNA_INSTALLER_BACKEND", "auto");
    QCOMPARE(fishermand::backend(), fishermand::Backend::Daemon);
    // A directory at the path is not a socket.
    qputenv("TUNA_FISHERMAN_SOCKET", dir.path().toLocal8Bit());
    QCOMPARE(fishermand::backend(), fishermand::Backend::Recipe);
    qputenv("TUNA_INSTALLER_BACKEND", "legacy");
    qputenv("TUNA_FISHERMAN_SOCKET", socket.toLocal8Bit());
    QCOMPARE(fishermand::backend(), fishermand::Backend::Recipe);
}

void DaemonTest::socketPaths()
{
    QCOMPARE(fishermand::socketPath(), QStringLiteral("/run/fisherman/io.tunaos.Fisherman"));
    QCOMPARE(fishermand::socketPath(QStringLiteral("io.tunaos.Fisherman")),
             QStringLiteral("/run/fisherman/io.tunaos.Fisherman"));
    // The real daemon has one interface on each socket.
    QCOMPARE(fishermand::socketPath(QStringLiteral("io.systemd.CryptEnroll")),
             QStringLiteral("/run/systemd/io.systemd.CryptEnroll"));
    QCOMPARE(fishermand::socketPath(QStringLiteral("io.systemd.Shutdown")),
             QStringLiteral("/run/systemd/io.systemd.Shutdown"));

    qputenv("FISHERMAND_SOCKET_DIR", "/tmp/x");
    QCOMPARE(fishermand::socketPath(), QStringLiteral("/tmp/x/io.tunaos.Fisherman"));
    QCOMPARE(fishermand::socketPath(QStringLiteral("io.systemd.SysInstall")),
             QStringLiteral("/tmp/x/io.systemd.SysInstall"));
    qunsetenv("FISHERMAND_SOCKET_DIR");

    // A moved Fisherman socket: a sibling with the interface name when
    // there is one, else the one socket (the mock serves all on each).
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString moved = dir.filePath(QStringLiteral("f.sock"));
    qputenv("TUNA_FISHERMAN_SOCKET", moved.toLocal8Bit());
    QCOMPARE(fishermand::socketPath(), moved);
    QCOMPARE(fishermand::socketPath(QStringLiteral("io.systemd.Shutdown")), moved);
    QFile sibling(dir.filePath(QStringLiteral("io.systemd.Shutdown")));
    QVERIFY(sibling.open(QIODevice::WriteOnly));
    sibling.close();
    QCOMPARE(fishermand::socketPath(QStringLiteral("io.systemd.Shutdown")), sibling.fileName());
}

void DaemonTest::handoffModeSpellings()
{
    QCOMPARE(fishermand::normalHandoffMode(QStringLiteral("migrate")), QStringLiteral("migrate"));
    QCOMPARE(fishermand::normalHandoffMode(QStringLiteral("soft_reboot")), QStringLiteral("soft_reboot"));
    QCOMPARE(fishermand::normalHandoffMode(QStringLiteral("soft-reboot")), QStringLiteral("soft_reboot"));
    QCOMPARE(fishermand::normalHandoffMode(QStringLiteral("Soft-Reboot")), QStringLiteral("soft_reboot"));
    QCOMPARE(fishermand::normalHandoffMode(QStringLiteral("reboot")), QStringLiteral("reboot"));
    QCOMPARE(fishermand::normalHandoffMode(QString()), QStringLiteral("reboot"));
    QCOMPARE(fishermand::normalHandoffMode(QStringLiteral("kexec")), QStringLiteral("reboot"));
}

void DaemonTest::handoffModeSharedCases()
{
    // shared/probe/handoff-cases.json: the cases every frontend meets.
    const QString path = QFileInfo(QStringLiteral(__FILE__)).dir().absoluteFilePath(
        QStringLiteral("../../../shared/probe/handoff-cases.json"));
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        QSKIP("shared cases only exist in the monorepo checkout");
    const QJsonArray cases = QJsonDocument::fromJson(f.readAll()).object().value(QStringLiteral("cases")).toArray();
    QVERIFY(!cases.isEmpty());
    for (const QJsonValue &v : cases) {
        const QJsonObject c = v.toObject();
        // A missing field reaches the reader as an empty string.
        const QString wire = c.value(QStringLiteral("wire_mode")).toString();
        QCOMPARE(fishermand::normalHandoffMode(wire), c.value(QStringLiteral("mode")).toString());
    }
}

void DaemonTest::installConfigMapsTheRecipe()
{
    Recipe r;
    r.disk = QStringLiteral("/dev/sda");
    r.encryption.type = QStringLiteral("tpm2-luks-passphrase");
    r.encryption.passphrase = QStringLiteral("s3cret passphrase");
    r.hostname = QStringLiteral("tuna-box");
    r.user.username = QStringLiteral("tuna");
    r.user.fullname = QStringLiteral("Tuna Test");
    r.user.password = QStringLiteral("hunter2!");
    r.user.groups = {QStringLiteral("wheel"), QStringLiteral("audio")};
    r.filesystem = QStringLiteral("btrfs");
    r.image = QStringLiteral("ghcr.io/x/y:z");

    const QJsonObject config = fishermand::installConfig(r, QStringLiteral("erase"));
    const QJsonObject want{
        {QStringLiteral("disk"), QStringLiteral("/dev/sda")},
        {QStringLiteral("installMode"), QStringLiteral("erase")},
        {QStringLiteral("encryption"),
         QJsonObject{{QStringLiteral("type"), QStringLiteral("tpm2_luks_passphrase")},
                     {QStringLiteral("passphrase"), QStringLiteral("s3cret passphrase")}}},
        {QStringLiteral("user"),
         QJsonObject{{QStringLiteral("username"), QStringLiteral("tuna")},
                     {QStringLiteral("fullName"), QStringLiteral("Tuna Test")},
                     {QStringLiteral("password"), QStringLiteral("hunter2!")},
                     {QStringLiteral("admin"), true}}},
        {QStringLiteral("hostname"), QStringLiteral("tuna-box")},
    };
    QCOMPARE(config, want);

    // No install mode, no passphrase type, no user: only what is there.
    Recipe bare;
    bare.disk = QStringLiteral("/dev/vda");
    const QJsonObject small = fishermand::installConfig(bare, QString());
    QVERIFY(!small.contains(QLatin1String("installMode")));
    QVERIFY(!small.contains(QLatin1String("user")));
    QCOMPARE(small.value(QLatin1String("encryption")).toObject(),
             QJsonObject({{QStringLiteral("type"), QStringLiteral("none")}}));
    // An unknown mode is left out, never sent.
    QVERIFY(!fishermand::installConfig(bare, QStringLiteral("shrink")).contains(QLatin1String("installMode")));

    // The field check leaves the account password out.
    const QJsonObject partial = fishermand::installConfig(r, QString(), true);
    QVERIFY(!partial.value(QLatin1String("user")).toObject().contains(QLatin1String("password")));
    // The passphrase stays: the daemon has rules for it.
    QCOMPARE(partial.value(QLatin1String("encryption")).toObject().value(QLatin1String("passphrase")).toString(),
             QStringLiteral("s3cret passphrase"));
    // A TPM-only type carries no passphrase even when one was typed.
    r.encryption.type = QStringLiteral("tpm2-luks");
    QVERIFY(!fishermand::installConfig(r, QString()).value(QLatin1String("encryption")).toObject()
                 .contains(QLatin1String("passphrase")));
    // The image makes its own user: none is sent.
    r.userRequired = false;
    QVERIFY(!fishermand::installConfig(r, QString()).contains(QLatin1String("user")));
}

void DaemonTest::privacyOnlyWhenChanged()
{
    Recipe r;
    r.hostname = QStringLiteral("box");
    r.locale = QStringLiteral("de_DE.UTF-8");
    r.keyboardLayout = QStringLiteral("de");
    r.timezone = QStringLiteral("Europe/Berlin");
    const QJsonObject untouched = fishermand::targetChoices(r, false, false);
    QVERIFY(!untouched.contains(QLatin1String("privacy")));
    QCOMPARE(untouched.value(QLatin1String("locale")).toString(), QStringLiteral("de_DE.UTF-8"));
    QCOMPARE(untouched.value(QLatin1String("keymap")).toString(), QStringLiteral("de"));
    QCOMPARE(untouched.value(QLatin1String("timeZone")).toString(), QStringLiteral("Europe/Berlin"));
    QCOMPARE(untouched.value(QLatin1String("hostname")).toString(), QStringLiteral("box"));
    QVERIFY(!untouched.contains(QLatin1String("user")));

    const QJsonObject on = fishermand::targetChoices(r, true, true);
    QCOMPARE(on.value(QLatin1String("privacy")).toObject(),
             QJsonObject({{QStringLiteral("locationServices"), true}}));
    // Switched on and back off is still a choice: false is sent.
    const QJsonObject off = fishermand::targetChoices(r, true, false);
    QCOMPARE(off.value(QLatin1String("privacy")).toObject(),
             QJsonObject({{QStringLiteral("locationServices"), false}}));

    // A region value nobody picked is not sent.
    const QJsonObject empty = fishermand::targetChoices(Recipe(), false, false);
    QVERIFY(!empty.contains(QLatin1String("locale")));
    QVERIFY(!empty.contains(QLatin1String("keymap")));
    QVERIFY(!empty.contains(QLatin1String("timeZone")));

    // The controller tracks the touch, not the value.
    InstallerController c;
    QVERIFY(!c.locationTouched());
    QVERIFY(!c.daemonTarget().contains(QLatin1String("privacy")));
    c.setLocationServices(false);
    QVERIFY(c.locationTouched());
    QCOMPARE(c.daemonTarget().value(QLatin1String("privacy")).toObject(),
             QJsonObject({{QStringLiteral("locationServices"), false}}));
    c.setLocationServices(true);
    QCOMPARE(c.daemonTarget().value(QLatin1String("privacy")).toObject(),
             QJsonObject({{QStringLiteral("locationServices"), true}}));
}

void DaemonTest::eventsBecomeProgressLines()
{
    const auto event = [](const char *json) {
        return fishermand::eventToLine(QJsonDocument::fromJson(json).object());
    };
    const QJsonObject step = event(R"({"event":"step_started","stepId":"install_os","stepIndex":5,"totalSteps":9,"overallPct":14})");
    QCOMPARE(step.value(QLatin1String("type")).toString(), QStringLiteral("step"));
    QCOMPARE(step.value(QLatin1String("step")).toInt(), 5);
    QCOMPARE(step.value(QLatin1String("total_steps")).toInt(), 9);
    QCOMPARE(step.value(QLatin1String("step_id")).toString(), QStringLiteral("install_os"));
    QCOMPARE(step.value(QLatin1String("overall_pct")).toInt(), 14);

    const QJsonObject progress = event(R"({"event":"progress","stepId":"install_os","overallPct":47})");
    QCOMPARE(progress.value(QLatin1String("type")).toString(), QStringLiteral("substep"));
    QCOMPARE(progress.value(QLatin1String("overall_pct")).toInt(), 47);

    QCOMPARE(event(R"({"event":"complete","overallPct":100})").value(QLatin1String("type")).toString(),
             QStringLiteral("complete"));
    QVERIFY(event(R"({"event":"step_finished","stepId":"mount","overallPct":14})").isEmpty());
    QVERIFY(event(R"({"event":"cancelled","overallPct":50})").isEmpty());
    // A kind this client does not know adds no line (shared/flow: ignore).
    QVERIFY(event(R"({"event":"new_kind"})").isEmpty());

    const QJsonObject failed = event(R"({"event":"failed","stepId":"install_os","reason":"device_lost","message":"gone","nextAction":"choose_another_disk","overallPct":40})");
    QCOMPARE(failed.value(QLatin1String("type")).toString(), QStringLiteral("error"));
    QCOMPARE(failed.value(QLatin1String("code")).toString(), QStringLiteral("device_lost"));
    QCOMPARE(failed.value(QLatin1String("disk_changed")).toBool(), true);
    // A step with no message has words in the log, not its id.
    const QJsonObject silent = event(R"({"event":"step_started","stepId":"validate_device","stepIndex":1,"totalSteps":10,"overallPct":0})");
    QCOMPARE(silent.value(u"step").toInt(), 1);
    QVERIFY(!silent.value(u"step_name").toString().contains(u'_'));
    QVERIFY(!silent.value(u"step_name").toString().isEmpty());
    const QJsonObject early = event(R"({"event":"failed","stepId":"validate_device","reason":"device_lost","message":"gone"})");
    QCOMPARE(early.value(QLatin1String("disk_changed")).toBool(true), false);

    // The controller's bar follows the daemon's overallPct and never goes
    // back; only the end of the stream ends the install.
    InstallerController c;
    c.consumeDaemonEvent(QJsonDocument::fromJson(R"({"event":"step_started","stepId":"install_os","stepIndex":5,"totalSteps":9,"overallPct":14})").object());
    QCOMPARE(c.installStep(), 5);
    QCOMPARE(c.installTotalSteps(), 9);
    QCOMPARE(c.installFraction(), 0.14);
    c.consumeDaemonEvent(QJsonDocument::fromJson(R"({"event":"progress","stepId":"install_os","overallPct":64})").object());
    QCOMPARE(c.installFraction(), 0.64);
    c.consumeDaemonEvent(QJsonDocument::fromJson(R"({"event":"progress","stepId":"install_os","overallPct":31})").object());
    QCOMPARE(c.installFraction(), 0.64);
    c.consumeDaemonEvent(QJsonDocument::fromJson(R"({"event":"complete","overallPct":100})").object());
    QCOMPARE(c.installFraction(), 1.0);
    QVERIFY(!c.installFinishedFlag());
    QVERIFY(!c.succeeded());
}

void DaemonTest::firstBootToolDetection()
{
    const QString unit = QStringLiteral("plasma-setup.service");
    const auto touch = [](const QString &path, const QByteArray &body) {
        QFile f(path);
        return f.open(QIODevice::WriteOnly) && f.write(body) == body.size();
    };

    // An image with plasma-setup enabled.
    QTemporaryDir enabled;
    QVERIFY(QDir(enabled.path()).mkpath(QStringLiteral("usr/lib/systemd/system")));
    QVERIFY(QDir(enabled.path()).mkpath(QStringLiteral("etc/systemd/system/graphical.target.wants")));
    const QString libUnit = enabled.filePath(QStringLiteral("usr/lib/systemd/system/") + unit);
    QVERIFY(touch(libUnit, "[Unit]\n"));
    QVERIFY(QFile::link(libUnit, enabled.filePath(QStringLiteral("etc/systemd/system/graphical.target.wants/") + unit)));
    QVERIFY(InstallerController::plasmaSetupWillRun(enabled.path()));

    // The rule: the installer makes the user. What is on the disk does not
    // decide it, an enabled plasma-setup included.
    qunsetenv("TUNA_FIRSTBOOT_TOOL");
    QCOMPARE(InstallerController::detectFirstBootTool(enabled.path()), QString());
    for (const char *value : {"", "none", "yes", "1", "kde-initial-setup"}) {
        qputenv("TUNA_FIRSTBOOT_TOOL", value);
        QCOMPARE(InstallerController::detectFirstBootTool(enabled.path()), QString());
    }

    // Only the medium's word skips the account step.
    qputenv("TUNA_FIRSTBOOT_TOOL", "plasma-setup");
    QCOMPARE(InstallerController::detectFirstBootTool(enabled.path()), QStringLiteral("plasma-setup"));
    qputenv("TUNA_FIRSTBOOT_TOOL", " plasma-setup ");
    QCOMPARE(InstallerController::detectFirstBootTool(enabled.path()), QStringLiteral("plasma-setup"));
    // The tools of the other desktops are taken at the medium's word.
    for (const char *tool : {"cosmic-initial-setup", "gnome-initial-setup"}) {
        qputenv("TUNA_FIRSTBOOT_TOOL", tool);
        QCOMPARE(InstallerController::detectFirstBootTool(QStringLiteral("/nonexistent")), QLatin1String(tool));
    }

    // The check on a claim of plasma-setup: a unit that will not run means
    // that the wizard asks, or the installed system has no user.
    qputenv("TUNA_FIRSTBOOT_TOOL", "plasma-setup");
    QTemporaryDir missing;
    QVERIFY(missing.isValid());
    QVERIFY(!InstallerController::plasmaSetupWillRun(missing.path()));
    QCOMPARE(InstallerController::detectFirstBootTool(missing.path()), QString());

    QTemporaryDir notEnabled;
    QVERIFY(QDir(notEnabled.path()).mkpath(QStringLiteral("usr/lib/systemd/system")));
    QVERIFY(touch(notEnabled.filePath(QStringLiteral("usr/lib/systemd/system/") + unit), "[Unit]\n"));
    QCOMPARE(InstallerController::detectFirstBootTool(notEnabled.path()), QString());

    // Masked, as the tunaOS images ship it today.
    QVERIFY(QFile::link(QStringLiteral("/dev/null"), enabled.filePath(QStringLiteral("etc/systemd/system/") + unit)));
    QVERIFY(!InstallerController::plasmaSetupWillRun(enabled.path()));
    QCOMPARE(InstallerController::detectFirstBootTool(enabled.path()), QString());
}

void DaemonTest::legacyBackendKeepsTheRecipePath()
{
    // `legacy` with a daemon socket in reach: no daemon fact, no daemon
    // step, and the four encryption choices stay.
    qputenv("TUNA_INSTALLER_BACKEND", "legacy");
    InstallerController c;
    QVERIFY(!c.daemonBackend());
    QCOMPARE(c.encryptionType(), QStringLiteral("none"));
    QVERIFY(c.stepSkipped(QStringLiteral("rst")));
    QVERIFY(c.stepSkipped(QStringLiteral("wipe-or-free")));
    QVERIFY(!c.stepSkipped(QStringLiteral("encryption")));
    QVERIFY(c.stepSkipped(QStringLiteral("handoff")));
    QVERIFY(c.stepSkipped(QStringLiteral("recovery-key")));
    QVERIFY(!c.daemonEncrypted());
    c.handoff();
    QVERIFY(c.handoffState().isEmpty());
    // fisherman's recovery_key event still opens the recovery-key step.
    c.loadDemoState(QStringLiteral("{\"type\":\"recovery_key\",\"key\":\"abcdefgh-abcdefgh-abcdefgh-abcdefgh-abcdefgh-abcdefgh-abcdefgh-abcdefgh\"}"), 0);
    QVERIFY(c.succeeded());
    QVERIFY(!c.stepSkipped(QStringLiteral("recovery-key")));
    QVERIFY(c.stepSkipped(QStringLiteral("handoff")));
    QVERIFY(!c.recoveryQrRows().isEmpty());
    // fisherman enrolled the key before it sent it: Done goes on at once.
    QVERIFY(!c.recoveryEnrolled());
    c.enrollRecoveryKey();
    QVERIFY(c.recoveryEnrolled());
}

void DaemonTest::scenarioHappy()
{
    NEED_MOCK("happy");
    InstallerController c;
    QVERIFY(c.daemonBackend());
    QVERIFY(!c.daemonUnreachable());
    QVERIFY(c.hasTpm());
    QVERIFY(c.isLive());
    QVERIFY(c.unmetRequirements().isEmpty());

    // The screens of happy-tpm: no requirements, rst, wipe-or-free or
    // encryption step; the TPM seals the disk with no prompt.
    QVERIFY(c.stepSkipped(QStringLiteral("requirements")));
    QVERIFY(!c.stepSkipped(QStringLiteral("try-or-install")));
    QVERIFY(!c.stepSkipped(QStringLiteral("language")));
    QVERIFY(!c.stepSkipped(QStringLiteral("keyboard")));
    QVERIFY(!c.stepSkipped(QStringLiteral("timezone")));
    QVERIFY(c.stepSkipped(QStringLiteral("network")));
    QVERIFY(c.stepSkipped(QStringLiteral("rst")));
    QVERIFY(c.stepSkipped(QStringLiteral("encryption")));
    QCOMPARE(c.encryptionType(), QStringLiteral("tpm2-luks"));
    QVERIFY(c.stepSkipped(QStringLiteral("recovery-key")));
    QVERIFY(c.stepSkipped(QStringLiteral("handoff")));

    // The disk list: the NVMe disk. The 8 GiB stick is too small.
    DiskModel disks;
    disks.refresh();
    QCOMPARE(disks.rowCount(), 1);
    QCOMPARE(disks.deviceAt(0), QStringLiteral("/dev/nvme0n1"));
    QCOMPARE(c.tooSmallDisks().size(), 1);
    QVERIFY(c.tooSmallDisks().first().contains(QStringLiteral("Mock USB Stick")));
    QVERIFY(!c.minimalDiskSize().isEmpty());
    QCOMPARE(c.diskFit(QStringLiteral("/dev/sdb")), QStringLiteral("disk_too_small"));

    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    QVERIFY(c.stepSkipped(QStringLiteral("wipe-or-free")));
    QVERIFY(!c.selectedDiskHasData());
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    c.setLanguage(c.languageIds().isEmpty() ? QStringLiteral("en_US") : c.languageIds().first());
    c.setTimezone(QStringLiteral("Europe/Berlin"));
    QCOMPARE(c.daemonConfig().value(QLatin1String("installMode")).toString(), QStringLiteral("erase"));
    QCOMPARE(c.daemonTarget().value(QLatin1String("timeZone")).toString(), QStringLiteral("Europe/Berlin"));

    QSignalSpy completed(&c, &InstallerController::installCompleted);
    c.startInstall();
    QVERIFY(c.installing());
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY(!c.installing());
    QVERIFY(c.succeeded());
    QVERIFY(!c.cancelled());
    QCOMPARE(c.exitCode(), 0);
    QCOMPARE(completed.count(), 1);
    QCOMPARE(c.installFraction(), 1.0);
    // The ten clean-install steps of a TPM install (tpm2_enroll included).
    QCOMPARE(c.installTotalSteps(), 10);
    QVERIFY(c.failureReason().isEmpty());

    // The recovery key: made at the end of the install, shown with a QR
    // symbol, enrolled when the person is done.
    QVERIFY(!c.stepSkipped(QStringLiteral("recovery-key")));
    RECOVERY_KEY(c);
    QVERIFY2(keyShape().match(c.recoveryKey()).hasMatch(), "the key does not have the shape of the test contract");
    QVERIFY(c.recoveryError().isEmpty());
    const QStringList qr = c.recoveryQrRows();
    QVERIFY(qr.size() >= 21);
    QCOMPARE(qr.first().size(), qr.size());
    QVERIFY(c.recoveryKeyPending());
    ENROLL(c);
    QVERIFY(c.recoveryEnrolled());
    c.setRecoveryAck(true);
    QVERIFY(!c.recoveryKeyPending());

    // The handoff: the mode is the daemon's, read from Probe; Handoff goes
    // with no mode.
    QVERIFY(!c.stepSkipped(QStringLiteral("handoff")));
    QCOMPARE(c.handoffMode(), QStringLiteral("reboot"));
    c.handoff();
    // It does not block: the state is "starting" until the daemon answers.
    QCOMPARE(c.handoffState(), QStringLiteral("starting"));
    QTRY_COMPARE_WITH_TIMEOUT(c.handoffState(), QStringLiteral("started"), 15000);
    QVERIFY(!c.sessionKeepsRunning());
    QVERIFY(c.handoffError().isEmpty());

    // A second install after a complete one is refused by the daemon.
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY(!c.succeeded());
}

void DaemonTest::slowDaemonDoesNotBlock()
{
    // A peer that accepts and never answers, as a daemon that waits for a
    // polkit prompt does. No call may hold the event loop: each returns at
    // once and shows a busy state. The time limit then ends the wait.
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QLocalServer silent;
    QVERIFY(silent.listen(dir.filePath(QStringLiteral("silent.sock"))));
    fishermand::AsyncClient client(silent.fullServerName());
    QList<fishermand::Reply> replies;
    connect(&client, &fishermand::AsyncClient::replyReceived, this,
            [&replies](const fishermand::Reply &reply) { replies.append(reply); });
    QElapsedTimer timer;
    timer.start();
    client.call(QStringLiteral("io.tunaos.Fisherman.Handoff"), {}, false, 300);
    QVERIFY2(timer.elapsed() < 200, "the call blocked");
    QVERIFY(replies.isEmpty());
    QTRY_COMPARE_WITH_TIMEOUT(replies.size(), 1, 5000);
    QVERIFY(replies.first().timedOut);
    QVERIFY(replies.first().transportFailed);
    QVERIFY(!replies.first().ok());
    QVERIFY(!client.busy());

    // The controller on such a daemon: the calls return at once.
    qputenv("TUNA_INSTALLER_BACKEND", "legacy");
    InstallerController c;
    qputenv("TUNA_INSTALLER_BACKEND", "daemon");
    for (const char *name : {"io.tunaos.Fisherman", "io.systemd.CryptEnroll", "io.systemd.Shutdown"}) {
        auto *server = new QLocalServer(&c);
        QVERIFY(server->listen(dir.filePath(QLatin1String(name))));
    }
    qputenv("FISHERMAND_SOCKET_DIR", dir.path().toLocal8Bit());
    QVERIFY(c.daemonBackend());
    timer.restart();
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.startInstall();
    c.makeRecoveryKey();
    c.reboot();
    QVERIFY2(timer.elapsed() < 500, "a daemon call blocked the event loop");
    QVERIFY(c.installing());
    QVERIFY(c.recoveryBusy());
    QVERIFY(c.shutdownBusy());
    // Cancel before the stream opened: nothing ran, the disk is as it was.
    c.cancelInstall();
    QVERIFY(!c.installing());
    QVERIFY(c.cancelled());
    QVERIFY(c.diskUnchanged());
}

void DaemonTest::scenarioNoTpm()
{
    NEED_MOCK("no-tpm");
    InstallerController c;
    QVERIFY(c.daemonBackend());
    QVERIFY(!c.hasTpm());
    // No TPM: the encryption step asks for a passphrase, twice.
    QVERIFY(!c.stepSkipped(QStringLiteral("encryption")));
    QCOMPARE(c.encryptionType(), QStringLiteral("luks-passphrase"));
    QVERIFY(c.needsPassphrase(c.encryptionType()));
    QVERIFY(c.daemonEncrypted());

    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    c.setPassphrase(QStringLiteral("correct horse battery staple"));
    const QJsonObject encryption = c.daemonConfig().value(QLatin1String("encryption")).toObject();
    QCOMPARE(encryption.value(QLatin1String("type")).toString(), QStringLiteral("luks_passphrase"));
    QCOMPARE(encryption.value(QLatin1String("passphrase")).toString(), QStringLiteral("correct horse battery staple"));

    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY(c.succeeded());
    // Nine steps: no tpm2_enroll.
    QCOMPARE(c.installTotalSteps(), 9);
    // The passphrase is in no log line.
    QVERIFY(!c.log().contains(QStringLiteral("correct horse")));
    RECOVERY_KEY(c);
    QVERIFY(keyShape().match(c.recoveryKey()).hasMatch());
    ENROLL(c);
    QVERIFY(c.recoveryEnrolled());
}

void DaemonTest::scenarioExistingData()
{
    NEED_MOCK("existing-data");
    InstallerController c;
    // Windows on the NVMe disk, with room: the wipe-or-free step asks.
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    QVERIFY(c.selectedDiskHasData());
    QVERIFY(!c.selectedDiskForceErase());
    QVERIFY(!c.stepSkipped(QStringLiteral("wipe-or-free")));
    QCOMPARE(c.selectedDiskOperatingSystems(), QStringList{QStringLiteral("Windows")});
    QVERIFY(!c.selectedDiskFreeSpace().isEmpty());
    QCOMPARE(c.diskFit(QStringLiteral("/dev/nvme0n1")), QStringLiteral("enough_free_space"));
    // Free space is the default: the data stays unless the person says so.
    QCOMPARE(c.installMode(), QStringLiteral("free_space"));
    QCOMPARE(c.daemonConfig().value(QLatin1String("installMode")).toString(), QStringLiteral("free_space"));
    c.setInstallMode(QStringLiteral("erase"));
    QCOMPARE(c.daemonConfig().value(QLatin1String("installMode")).toString(), QStringLiteral("erase"));
    c.setInstallMode(QStringLiteral("shrink"));
    QCOMPARE(c.installMode(), QStringLiteral("erase"));

    // The disk with a foreign partition table: no choice, a forced erase.
    c.setDisk(QStringLiteral("/dev/sdc"));
    QCOMPARE(c.diskFit(QStringLiteral("/dev/sdc")), QStringLiteral("conflicting_disk_label_present"));
    QVERIFY(c.selectedDiskHasData());
    QVERIFY(c.selectedDiskForceErase());
    QVERIFY(!c.stepSkipped(QStringLiteral("wipe-or-free")));
    c.setInstallMode(QStringLiteral("free_space"));
    QCOMPARE(c.daemonConfig().value(QLatin1String("installMode")).toString(), QStringLiteral("erase"));

    // The install into free space runs to the end.
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    QCOMPARE(c.daemonConfig().value(QLatin1String("installMode")).toString(), QStringLiteral("free_space"));
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY2(c.succeeded(), qPrintable(c.log()));
}

void DaemonTest::scenarioTightSpace()
{
    NEED_MOCK("tight-space");
    InstallerController c;
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    QCOMPARE(c.diskFit(QStringLiteral("/dev/nvme0n1")), QStringLiteral("insufficient_free_space"));
    QVERIFY(c.selectedDiskHasData());
    QVERIFY(c.selectedDiskForceErase());
    QVERIFY(!c.stepSkipped(QStringLiteral("wipe-or-free")));
    QCOMPARE(c.daemonConfig().value(QLatin1String("installMode")).toString(), QStringLiteral("erase"));
}

void DaemonTest::scenarioRst()
{
    NEED_MOCK("rst");
    InstallerController c;
    QVERIFY(c.rstDetected());
    QCOMPARE(c.rstAffectedDisks(), QStringList{QStringLiteral("/dev/nvme0n1")});
    // The page comes before the disk list and does not block it.
    QVERIFY(!c.stepSkipped(QStringLiteral("rst")));
    QVERIFY(!c.stepSkipped(QStringLiteral("disk")));
    // The hidden disk is not offered, and the stick is too small: no row.
    DiskModel disks;
    disks.refresh();
    QCOMPARE(disks.rowCount(), 0);
    QCOMPARE(c.tooSmallDisks().size(), 1);
}

void DaemonTest::scenarioDeviceLost()
{
    NEED_MOCK("device-lost");
    InstallerController c;
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY(!c.succeeded());
    QVERIFY(!c.cancelled());
    QCOMPARE(c.exitCode(), 1);
    QCOMPARE(c.failureReason(), QStringLiteral("device_lost"));
    QCOMPARE(c.installError().value(QStringLiteral("step_id")).toString(), QStringLiteral("install_os"));
    // The disk went away during install_os: it was changed, and the done
    // step says so.
    QCOMPARE(c.installError().value(QStringLiteral("disk_changed")).toBool(), true);
    QVERIFY(!c.failureLines().isEmpty());
    // The bar stopped short of the end.
    QVERIFY(c.installFraction() < 1.0);
    // No key and no handoff after a failure: straight to done.
    QVERIFY(c.recoveryKey().isEmpty());
    QVERIFY(c.stepSkipped(QStringLiteral("recovery-key")));
    QVERIFY(c.stepSkipped(QStringLiteral("handoff")));
    c.handoff();
    QVERIFY(c.handoffState().isEmpty());

    // Try again: the result is forgotten and the daemon takes a new install.
    c.resetForRetry();
    QVERIFY(!c.installFinishedFlag());
    QVERIFY(c.failureReason().isEmpty());
    // The mock's disk stays gone: the daemon's check names the disk, and
    // the wizard starts no install on it.
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 15000);
    QVERIFY(!c.installing());
    QCOMPARE(c.failureReason(), QStringLiteral("validation_failed"));
    QVERIFY2(c.log().contains(QStringLiteral("disk")), qPrintable(c.log()));
}

void DaemonTest::scenarioRepartError()
{
    NEED_MOCK("repart-error");
    InstallerController c;
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY(!c.succeeded());
    QVERIFY(!c.cancelled());
    QCOMPARE(c.failureReason(), QStringLiteral("repart_failed"));
    QCOMPARE(c.installError().value(QStringLiteral("step_id")).toString(), QStringLiteral("partition"));
    QVERIFY(c.stepSkipped(QStringLiteral("recovery-key")));
    QVERIFY(c.stepSkipped(QStringLiteral("handoff")));
}

void DaemonTest::scenarioCancel()
{
    NEED_MOCK("cancel");
    InstallerController c;
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    c.startInstall();
    // The mock waits at half of install_os until Cancel arrives.
    QTRY_COMPARE_WITH_TIMEOUT(c.installStep(), 6, 30000);
    QTest::qWait(300);
    QVERIFY(c.installing());
    QVERIFY(!c.installFinishedFlag());

    c.cancelInstall();
    // A second press sends nothing more.
    c.cancelInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY(c.cancelled());
    QVERIFY(!c.succeeded());
    QCOMPARE(c.exitCode(), 130);
    QVERIFY(c.failureReason().isEmpty());
    QVERIFY(c.stepSkipped(QStringLiteral("recovery-key")));
    QVERIFY(c.stepSkipped(QStringLiteral("handoff")));
    // A cancel when nothing runs is safe.
    c.cancelInstall();
    QVERIFY(c.cancelled());
}

void DaemonTest::scenarioHandoffMigrate()
{
    NEED_MOCK("handoff-migrate");
    InstallerController c;
    QCOMPARE(c.handoffMode(), QStringLiteral("migrate"));
    // Before an install the daemon refuses, and the wizard does not ask.
    c.handoff();
    QVERIFY(c.handoffState().isEmpty());
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY(c.succeeded());
    HANDOFF(c);
    QCOMPARE(c.handoffState(), QStringLiteral("started"));
    // The live session becomes the installed system: nothing restarts.
    QVERIFY(c.sessionKeepsRunning());
}

void DaemonTest::scenarioHandoffSoftReboot()
{
    NEED_MOCK("handoff-soft-reboot");
    InstallerController c;
    QCOMPARE(c.handoffMode(), QStringLiteral("soft_reboot"));
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY(c.succeeded());
    HANDOFF(c);
    QCOMPARE(c.handoffState(), QStringLiteral("started"));
    QVERIFY(!c.sessionKeepsRunning());
}

void DaemonTest::scenarioInhibitor()
{
    NEED_MOCK("inhibitor");
    InstallerController c;
    // reboot-failed: the daemon refuses, and the wizard shows why. It does
    // not fall back to systemctl.
    c.reboot();
    QVERIFY(c.shutdownBusy());
    QTRY_VERIFY_WITH_TIMEOUT(!c.shutdownBusy(), 15000);
    QVERIFY2(c.shutdownError().contains(QStringLiteral("io.systemd.Shutdown.")), qPrintable(c.shutdownError()));
}

void DaemonTest::shutdownVerbs()
{
    // Restart and power off are io.systemd.Shutdown calls: the mock records
    // them and restarts nothing.
    {
        NEED_MOCK("happy");
        InstallerController c;
        REBOOT(c);
        QVERIFY2(c.shutdownError().isEmpty(), qPrintable(c.shutdownError()));
    }
    NEED_MOCK("happy");
    InstallerController c;
    c.poweroff();
    QTRY_VERIFY_WITH_TIMEOUT(!c.shutdownBusy(), 15000);
    QVERIFY2(c.shutdownError().isEmpty(), qPrintable(c.shutdownError()));
}

void DaemonTest::scenarioLowRam()
{
    NEED_MOCK("low-ram");
    InstallerController c;
    QCOMPARE(c.unmetRequirements(), QStringList{QStringLiteral("ram")});
    QVERIFY(!c.stepSkipped(QStringLiteral("requirements")));
    QVERIFY(c.requirementsBlocking());
    QVERIFY(!c.requirementsFatal());
}

void DaemonTest::daemonValidatesFields()
{
    NEED_MOCK("happy");
    InstallerController c;
    QSignalSpy problems(&c, &InstallerController::problemsChanged);
    c.setHostname(QStringLiteral("bad host"));
    c.setUsername(QStringLiteral("root"));
    // 300 ms after the last change, over io.tunaos.Fisherman.Validate.
    QTRY_VERIFY_WITH_TIMEOUT(!c.hostnameProblem().isEmpty(), 10000);
    QVERIFY(!c.usernameProblem().isEmpty());
    c.setHostname(QStringLiteral("good-host"));
    c.setUsername(QStringLiteral("tuna"));
    QTRY_VERIFY_WITH_TIMEOUT(c.hostnameProblem().isEmpty(), 10000);
    QVERIFY(c.usernameProblem().isEmpty());

    // The passphrase rule: a problem while it is empty, none once typed.
    c.setEncryptionType(QStringLiteral("luks-passphrase"));
    c.setPassphrase(QString());
    QTRY_VERIFY_WITH_TIMEOUT(!c.encryptionProblem().isEmpty(), 10000);
    c.setPassphrase(QStringLiteral("correct horse battery staple"));
    QTRY_VERIFY_WITH_TIMEOUT(c.encryptionProblem().isEmpty(), 10000);
}

void DaemonTest::invalidConfigStopsBeforeInstall()
{
    NEED_MOCK("no-tpm");
    InstallerController c;
    // A disk the daemon does not have: the whole-config Validate names the
    // field, and no Install call is made.
    c.setDisk(QStringLiteral("/dev/nonexistent"));
    c.setPassphrase(QStringLiteral("correct horse battery staple"));
    c.startInstall();
    // The check is on its way: the install step shows, and nothing blocks.
    QVERIFY(c.installing());
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 15000);
    QVERIFY(!c.installing());
    QVERIFY(!c.succeeded());
    QCOMPARE(c.failureReason(), QStringLiteral("validation_failed"));
    QVERIFY2(c.log().contains(QStringLiteral("disk")), qPrintable(c.log()));
    QVERIFY(!c.log().contains(QStringLiteral("correct horse")));
}

void DaemonTest::daemonUnreachable()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    qputenv("TUNA_INSTALLER_BACKEND", "daemon");
    qputenv("FISHERMAND_SOCKET_DIR", dir.path().toLocal8Bit());
    InstallerController c;
    QVERIFY(c.daemonBackend());
    QVERIFY(c.daemonUnreachable());
    QVERIFY(!c.daemonError().isEmpty());
    // Nothing falls back to the recipe CLI behind the person's back.
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    QElapsedTimer timer;
    timer.start();
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 15000);
    // A daemon that is not there is known at once, not after a time limit.
    QVERIFY2(timer.elapsed() < 5000, "an absent daemon took the whole time limit to report");
    QVERIFY(!c.installing());
    QVERIFY(!c.succeeded());
    QCOMPARE(c.failureReason(), QStringLiteral("daemon_unreachable"));
    REBOOT(c);
    QVERIFY(!c.shutdownError().isEmpty());
    // recovery-key-failed: no key, a reason, and nothing to enrol.
    c.makeRecoveryKey();
    RECOVERY_KEY(c);
    QVERIFY(c.recoveryKey().isEmpty());
    QVERIFY(!c.recoveryError().isEmpty());
    c.enrollRecoveryKey();
    QVERIFY(!c.recoveryBusy());
    QVERIFY(!c.recoveryEnrolled());
}

void DaemonTest::plasmaSetupOwnsTheAccount()
{
    NEED_MOCK("happy");
    {
        // The default: the wizard asks for the account.
        qunsetenv("TUNA_FIRSTBOOT_TOOL");
        InstallerController c;
        QCOMPARE(c.firstBootTool(), QString());
        QVERIFY(c.needsUserCreation());
        QVERIFY(!c.stepSkipped(QStringLiteral("account")));
        c.setUsername(QStringLiteral("tuna"));
        QVERIFY(c.daemonConfig().contains(QLatin1String("user")));
    }
    if (!InstallerController::plasmaSetupWillRun(QString())) {
        // The medium names plasma-setup, and this system has no such unit
        // that will run: the wizard still asks.
        qputenv("TUNA_FIRSTBOOT_TOOL", "plasma-setup");
        InstallerController c;
        QCOMPARE(c.firstBootTool(), QString());
        QVERIFY(!c.stepSkipped(QStringLiteral("account")));
    }
    // The medium names a first-boot tool: no account step, and no user
    // goes to the daemon, even when a name was typed before.
    qputenv("TUNA_FIRSTBOOT_TOOL", "gnome-initial-setup");
    InstallerController c;
    QCOMPARE(c.firstBootTool(), QStringLiteral("gnome-initial-setup"));
    QVERIFY(!c.needsUserCreation());
    QVERIFY(c.stepSkipped(QStringLiteral("account")));
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    QVERIFY(!c.daemonConfig().contains(QLatin1String("user")));
    QVERIFY(!c.daemonTarget().contains(QLatin1String("user")));
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY2(c.succeeded(), qPrintable(c.log()));
}

void DaemonTest::recoveryKeyStaysOutOfTheLog()
{
    NEED_MOCK("happy");
    InstallerController c;
    c.setDisk(QStringLiteral("/dev/nvme0n1"));
    c.setUsername(QStringLiteral("tuna"));
    c.setUserPassword(QStringLiteral("hunter2!"));
    c.startInstall();
    QTRY_VERIFY_WITH_TIMEOUT(c.installFinishedFlag(), 30000);
    QVERIFY(c.succeeded());
    RECOVERY_KEY(c);
    const QString key = c.recoveryKey();
    QVERIFY(!key.isEmpty());
    // Not in the pane, not in the copy for a bug report, not in the file.
    QVERIFY(!c.log().contains(key));
    QVERIFY(!c.logForSharing().contains(key));
    QVERIFY(!c.logPath().isEmpty());
    QFile file(c.logPath());
    QVERIFY(file.open(QIODevice::ReadOnly));
    const QByteArray written = file.readAll();
    QVERIFY(!written.isEmpty());
    QVERIFY(!written.contains(key.toUtf8()));
    QVERIFY(!written.contains("hunter2!"));
}

QTEST_GUILESS_MAIN(DaemonTest)
#include "test_daemon.moc"
