#include "offline.h"
#include "branding.h"
#include "branding_defaults.h"
#include "readiness.h"
#include "recipe.h"
#include "installercontroller.h"
#include "tpm.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcessEnvironment>
#include <QTemporaryDir>
#include <QTest>

class BackendTest : public QObject
{
    Q_OBJECT

private slots:
    void recipeDefaults();
    void recipeJsonOmitsOptionalValues();
    void recipeJsonIncludesConfiguredValues();
    void recipeValidation_data();
    void recipeValidation();
    void recipeJsonRoundTrip();
    void brandingFixtures();
    void brandingText();
    void brandingNothingReadableIsNeutral();
    void offlineCommandHelpers();
    void readinessWriteStampFailsWithEmptyRuntimeDir();
    void readinessWriteStampWritesExpectedFields();
    void readinessWriteStampBlankPageBecomesUnknown();

    // TPM 2.0 detection (shared/tpm/README.md). The probe used to be the
    // existence of /sys/class/tpm/tpm0, which a TPM 1.2 device has too.
    void tpmProbeReadsTheVersionNotTheDirectory_data();
    void tpmProbeReadsTheVersionNotTheDirectory();

    // fisherman's progress protocol (shared/progress/README.md). KDE had no
    // progress bar; these pin the parse that now drives one.
    void progressStepEventMovesTheBar();
    void progressUsesCumulativePctNotStepOverTotal();
    void progressSubstepInterpolatesInsideTheLongStep();
    void progressCompleteFillsTheBar();
    void progressIgnoresNonProtocolLines();
    void progressRejectsTheInventedStepPrefix();
    void progressUnknownStepNameFallsBackToTheRawName();

    // Recovery key (#129). The event used to be formatted into a log line
    // and dropped, so nothing could show it after the install.
    void recoveryKeyIsKeptNotJustPrinted();
    void recoveryKeyHoldsRestartUntilAcknowledged();
    void recoveryKeyAbsentMeansNoGate();
    void progressRendersEventsForTheLogPane();
};

void BackendTest::recipeDefaults()
{
    const Recipe recipe;

    QCOMPARE(recipe.filesystem, QStringLiteral("xfs"));
    QCOMPARE(recipe.encryption.type, QStringLiteral("none"));
    // Neutral until InstallerController fills them from the branding contract.
    QVERIFY(recipe.distroID.isEmpty());
    QVERIFY(recipe.hostname.isEmpty());
    QVERIFY(recipe.selinuxDisabled);
    QVERIFY(!recipe.liveMode);
}

void BackendTest::recipeJsonOmitsOptionalValues()
{
    const QJsonObject json = Recipe{}.toJson();

    // "image" is not one of the optional keys for a normal install: fisherman
    // is always handed it, and validationError() rejects an empty image before
    // a recipe can be sent. Only live-ISO mode may omit it — see the liveMode
    // branch in Recipe::toJson() and INSTALLER-FRONTENDS.md 4.
    QVERIFY(json.contains(QStringLiteral("image")));

    Recipe live;
    live.liveMode = true;
    QVERIFY(!live.toJson().contains(QStringLiteral("image")));

    QVERIFY(!json.contains(QStringLiteral("targetImgref")));
    QVERIFY(!json.contains(QStringLiteral("bootloader")));
    QVERIFY(!json.contains(QStringLiteral("composeFsBackend")));
    QVERIFY(!json.contains(QStringLiteral("flatpaks")));
    QVERIFY(!json.contains(QStringLiteral("additionalImageStores")));
    QCOMPARE(json.value(QStringLiteral("encryption")).toObject()
                 .value(QStringLiteral("type")).toString(),
             QStringLiteral("none"));
}

void BackendTest::recipeJsonIncludesConfiguredValues()
{
    Recipe recipe;
    recipe.disk = QStringLiteral("/dev/nvme0n1");
    recipe.image = QStringLiteral("ghcr.io/tuna-os/tunaos:latest");
    recipe.targetImgref = QStringLiteral("ghcr.io/tuna-os/tunaos:stable");
    recipe.bootloader = QStringLiteral("systemd");
    recipe.composeFsBackend = true;
    recipe.flatpaks = {QStringLiteral("org.mozilla.firefox")};
    recipe.additionalImageStores = {QStringLiteral("/run/media/oci")};
    recipe.encryption.type = QStringLiteral("luks-passphrase");
    recipe.encryption.passphrase = QStringLiteral("secret");

    const QJsonObject json = recipe.toJson();
    QCOMPARE(json.value(QStringLiteral("disk")).toString(), recipe.disk);
    QCOMPARE(json.value(QStringLiteral("image")).toString(), recipe.image);
    QCOMPARE(json.value(QStringLiteral("targetImgref")).toString(), recipe.targetImgref);
    QCOMPARE(json.value(QStringLiteral("bootloader")).toString(), recipe.bootloader);
    QVERIFY(json.value(QStringLiteral("composeFsBackend")).toBool());
    QCOMPARE(json.value(QStringLiteral("flatpaks")).toArray().first().toString(),
             recipe.flatpaks.first());
    QCOMPARE(json.value(QStringLiteral("additionalImageStores")).toArray().first().toString(),
             recipe.additionalImageStores.first());
    QCOMPARE(json.value(QStringLiteral("encryption")).toObject()
                 .value(QStringLiteral("passphrase")).toString(),
             recipe.encryption.passphrase);
}

void BackendTest::recipeValidation_data()
{
    QTest::addColumn<QString>("disk");
    QTest::addColumn<QString>("image");
    QTest::addColumn<bool>("liveMode");
    QTest::addColumn<QString>("hostname");
    QTest::addColumn<QString>("encryptionType");
    QTest::addColumn<QString>("passphrase");
    QTest::addColumn<QString>("expectedError");

    QTest::newRow("valid-image") << "/dev/vda" << "example/image" << false << "tunaos" << "none" << "" << "";
    QTest::newRow("valid-live") << "/dev/vda" << "" << true << "tunaos" << "none" << "" << "";
    QTest::newRow("missing-disk") << "" << "example/image" << false << "tunaos" << "none" << "" << "No disk selected";
    QTest::newRow("missing-image") << "/dev/vda" << "" << false << "tunaos" << "none" << "" << "No OS image specified";
    QTest::newRow("missing-hostname") << "/dev/vda" << "example/image" << false << "" << "none" << "" << "Hostname is required";
    QTest::newRow("unknown-encryption") << "/dev/vda" << "example/image" << false << "tunaos" << "plain" << "" << "Unknown encryption type: plain";
    QTest::newRow("missing-passphrase") << "/dev/vda" << "example/image" << false << "tunaos" << "luks-passphrase" << "" << "Encryption passphrase is required";
    QTest::newRow("valid-passphrase") << "/dev/vda" << "example/image" << false << "tunaos" << "luks-passphrase" << "secret" << "";
}

void BackendTest::recipeValidation()
{
    QFETCH(QString, disk);
    QFETCH(QString, image);
    QFETCH(bool, liveMode);
    QFETCH(QString, hostname);
    QFETCH(QString, encryptionType);
    QFETCH(QString, passphrase);
    QFETCH(QString, expectedError);

    Recipe recipe;
    recipe.disk = disk;
    recipe.image = image;
    recipe.liveMode = liveMode;
    recipe.hostname = hostname;
    recipe.encryption.type = encryptionType;
    recipe.encryption.passphrase = passphrase;

    QCOMPARE(recipe.validationError(), expectedError);
    QCOMPARE(recipe.isValid(), expectedError.isEmpty());
}

void BackendTest::recipeJsonRoundTrip()
{
    Recipe original;
    original.disk = QStringLiteral("/dev/sda");
    original.filesystem = QStringLiteral("ext4");
    original.image = QStringLiteral("ghcr.io/tuna-os/yellowfin:gnome");
    original.targetImgref = QStringLiteral("ghcr.io/tuna-os/yellowfin:stable");
    original.bootloader = QStringLiteral("systemd");
    original.composeFsBackend = true;
    original.flatpaks = {QStringLiteral("org.gnome.TextEditor"), QStringLiteral("org.kde.kcalc")};
    original.additionalImageStores = {QStringLiteral("/run/media/store")};
    original.distroID = QStringLiteral("tunaos");
    original.hostname = QStringLiteral("custom-host");
    original.encryption.type = QStringLiteral("luks-passphrase");
    original.encryption.passphrase = QStringLiteral("pass");

    const QJsonObject json = original.toJson();
    const Recipe restored = Recipe::fromJson(json);

    QCOMPARE(restored.disk, original.disk);
    QCOMPARE(restored.filesystem, original.filesystem);
    QCOMPARE(restored.image, original.image);
    QCOMPARE(restored.targetImgref, original.targetImgref);
    QCOMPARE(restored.bootloader, original.bootloader);
    QCOMPARE(restored.composeFsBackend, original.composeFsBackend);
    QCOMPARE(restored.flatpaks, original.flatpaks);
    QCOMPARE(restored.additionalImageStores, original.additionalImageStores);
    QCOMPARE(restored.distroID, original.distroID);
    QCOMPARE(restored.hostname, original.hostname);
    QCOMPARE(restored.encryption.type, original.encryption.type);
    QCOMPARE(restored.encryption.passphrase, original.encryption.passphrase);
}

static QJsonObject readJsonObject(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return {};
    return QJsonDocument::fromJson(f.readAll()).object();
}

static QString readText(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
        return {};
    return QString::fromUtf8(f.readAll());
}

// shared/branding/fixtures/expected.json: the same cases the Python, Go and
// Rust resolvers are checked against.
void BackendTest::brandingFixtures()
{
    const QString dir = QStringLiteral(BRANDING_FIXTURES_DIR);
    const QJsonObject expected = readJsonObject(dir + QStringLiteral("/expected.json"));
    if (expected.isEmpty())
        QSKIP("shared branding fixtures not available");

    for (auto it = expected.begin(); it != expected.end(); ++it) {
        if (it.key().startsWith(QLatin1Char('_')))
            continue;
        const QJsonObject spec = it.value().toObject();
        QJsonObject file;
        if (spec.value(QStringLiteral("branding")).isString())
            file = readJsonObject(dir + QLatin1Char('/') + spec.value(QStringLiteral("branding")).toString());
        QString osRelease;
        if (spec.value(QStringLiteral("os_release")).isString())
            osRelease = readText(dir + QLatin1Char('/') + spec.value(QStringLiteral("os_release")).toString());
        const branding::Branding got = branding::fromSources(
            file, osRelease, spec.value(QStringLiteral("name_override")).toString());

        const QHash<QString, QString> gotMap = {
            {QStringLiteral("name"), got.name},
            {QStringLiteral("id"), got.id},
            {QStringLiteral("vendor"), got.vendor},
            {QStringLiteral("home_url"), got.homeUrl},
            {QStringLiteral("docs_url"), got.docsUrl},
            {QStringLiteral("support_url"), got.supportUrl},
            {QStringLiteral("logo"), got.logo},
            {QStringLiteral("default_hostname"), got.defaultHostname},
            {QStringLiteral("default_image"), got.defaultImage},
        };
        const QJsonObject expect = spec.value(QStringLiteral("expect")).toObject();
        for (auto e = expect.begin(); e != expect.end(); ++e) {
            QVERIFY2(gotMap.value(e.key()) == e.value().toString(),
                     qPrintable(it.key() + QStringLiteral(": ") + e.key() + QStringLiteral(" got '")
                                + gotMap.value(e.key()) + QStringLiteral("' want '")
                                + e.value().toString() + QStringLiteral("'")));
        }
        if (spec.contains(QStringLiteral("expect_name")))
            QCOMPARE(got.name, spec.value(QStringLiteral("expect_name")).toString());
        const QJsonObject expectCopy = spec.value(QStringLiteral("expect_copy")).toObject();
        for (auto e = expectCopy.begin(); e != expectCopy.end(); ++e) {
            QVERIFY2(got.copy.value(e.key()) == e.value().toString(),
                     qPrintable(it.key() + QStringLiteral(": copy.") + e.key() + QStringLiteral(" got '")
                                + got.copy.value(e.key()) + QStringLiteral("'")));
        }
        const QJsonObject expectAssets = spec.value(QStringLiteral("expect_assets")).toObject();
        for (auto e = expectAssets.begin(); e != expectAssets.end(); ++e)
            QCOMPARE(got.assets.value(e.key()), e.value().toString());
        if (spec.contains(QStringLiteral("expect_store_url")))
            QCOMPARE(got.storeUrl, spec.value(QStringLiteral("expect_store_url")).toString());
    }

    // The compiled-in defaults are the shared file, verbatim.
    QCOMPARE(QString::fromUtf8(kCopyDefaultsJson), readText(dir + QStringLiteral("/../copy-defaults.json")));
    QVERIFY(!branding::copyDefaults().value(QStringLiteral("welcome_title")).isEmpty());
}

void BackendTest::brandingText()
{
    QJsonObject file;
    file.insert(QStringLiteral("name"), QStringLiteral("Marlin"));
    const branding::Branding b = branding::fromSources(file, QString());
    QCOMPARE(b.text(QStringLiteral("welcome_title")), QStringLiteral("Welcome to Marlin"));
    QCOMPARE(b.text(QStringLiteral("confirm_warning"), {{QStringLiteral("disk"), QStringLiteral("/dev/sda")}}),
             QStringLiteral("Everything on /dev/sda will be erased. This cannot be undone."));
}

void BackendTest::brandingNothingReadableIsNeutral()
{
    const branding::Branding b = branding::resolveFrom(
        {QStringLiteral("/nonexistent/branding.json")}, {QStringLiteral("/nonexistent/os-release")}, QString());
    QCOMPARE(b.name, QStringLiteral("Linux"));
    QCOMPARE(b.id, QStringLiteral("linux"));
    QCOMPARE(b.defaultHostname, QStringLiteral("linux"));
    QVERIFY(b.defaultImage.isEmpty());
}

void BackendTest::offlineCommandHelpers()
{
    const QStringList cmd = offline::fishermanCommand();
    QVERIFY(!cmd.isEmpty());

    const QStringList raw = {QStringLiteral("echo"), QStringLiteral("test")};
    const QStringList hostWrapped = offline::hostCommand(raw);
    QVERIFY(!hostWrapped.isEmpty());

    if (offline::inFlatpak()) {
        QCOMPARE(hostWrapped.first(), QStringLiteral("flatpak-spawn"));
        QCOMPARE(hostWrapped.at(1), QStringLiteral("--host"));
    } else {
        QCOMPARE(hostWrapped, raw);
    }
}

// readiness::writeStamp() was split out from armStamp() specifically so the
// stamp format -- which tunaOS's installer-smoke.yml parses over SSH -- is
// reachable from a test without standing up a window (see readiness.h). It
// was never linked into this test target, so nothing checked that promise.
// armStamp() itself still needs a real QQuickWindow and stays untested here.

void BackendTest::readinessWriteStampFailsWithEmptyRuntimeDir()
{
    QVERIFY(!readiness::writeStamp(QString(), QStringLiteral("welcome"), 1000));
}

void BackendTest::readinessWriteStampWritesExpectedFields()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    QVERIFY(readiness::writeStamp(dir.path(), QStringLiteral("disk"), 1234567));

    QFile stamp(QDir(dir.path()).filePath(QStringLiteral("tuna-installer-ready")));
    QVERIFY(stamp.open(QIODevice::ReadOnly | QIODevice::Text));
    const QString body = QString::fromUtf8(stamp.readAll());

    QVERIFY(body.contains(QStringLiteral("app_id=org.tunaos.InstallerKde")));
    QVERIFY(body.contains(QStringLiteral("window=ApplicationWindow")));
    QVERIFY(body.contains(QStringLiteral("signal=frame-swapped")));
    QVERIFY(body.contains(QStringLiteral("mapped_at=1234.567")));
    QVERIFY(body.contains(QStringLiteral("page=disk")));
}

void BackendTest::readinessWriteStampBlankPageBecomesUnknown()
{
    // A bare "page=" would parse downstream as a real page named "" --
    // readiness.cpp's own comment on this fallback is what this test pins.
    QTemporaryDir dir;
    QVERIFY(dir.isValid());

    QVERIFY(readiness::writeStamp(dir.path(), QString(), 0));

    QFile stamp(QDir(dir.path()).filePath(QStringLiteral("tuna-installer-ready")));
    QVERIFY(stamp.open(QIODevice::ReadOnly | QIODevice::Text));
    QVERIFY(QString::fromUtf8(stamp.readAll()).contains(QStringLiteral("page=unknown")));
}


// ---------------------------------------------------------------------------
// fisherman progress protocol
//
// fisherman writes newline-delimited JSON to stdout and nothing else. These
// tests exist because two other frontends shipped parsers for a "[n/9] "
// prefix it has never written: their bars sat at zero for every real install
// while their fixtures, written in the same invented shape, showed one
// moving. progressRejectsTheInventedStepPrefix() is that case, pinned.

static QString stepEvent(int step, int total, const char *name, int cumulative, int weight)
{
    return QStringLiteral(
        "{\"type\":\"step\",\"step\":%1,\"total_steps\":%2,\"step_name\":\"%3\","
        "\"cumulative_pct\":%4,\"weight_pct\":%5}")
        .arg(step).arg(total).arg(QString::fromLatin1(name)).arg(cumulative).arg(weight);
}

// Every test below drives the controller through loadDemoState(), its public
// harness hook, which splits the text on newlines and runs each line through
// the same appendLine() the live QProcess path uses. Feeding the real entry
// point matters here more than usual: the bug this replaces survived because
// harnesses wrote to the frontend's state instead of through its code.
static void feed(InstallerController &c, const QStringList &lines)
{
    c.loadDemoState(lines.join(QLatin1Char('\n')), 0);
}

void BackendTest::progressStepEventMovesTheBar()
{
    InstallerController c;
    QVERIFY(qFuzzyIsNull(c.installFraction()));

    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87)});

    QCOMPARE(c.installStep(), 5);
    QCOMPARE(c.installTotalSteps(), 8);
    QCOMPARE(c.installFraction(), 0.01);
}

void BackendTest::progressUsesCumulativePctNotStepOverTotal()
{
    // step/total would put step 5 of 8 at 62%. The real position is 1%:
    // "Installing OS" has not started yet and carries 87% of the time.
    InstallerController c;
    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87)});

    QVERIFY(c.installFraction() < 0.5);
    QCOMPARE(c.installFraction(), 0.01);
}

void BackendTest::progressSubstepInterpolatesInsideTheLongStep()
{
    InstallerController c;
    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87)});
    const qreal atStepStart = c.installFraction();

    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87),
             QStringLiteral(
                 "{\"type\":\"substep\",\"message\":\"Pulling image: layer 47/71\"}")});

    // Without this the bar freezes for 87% of the install.
    QVERIFY(c.installFraction() > atStepStart);
    QVERIFY(c.installFraction() < 1.0);
}

void BackendTest::progressCompleteFillsTheBar()
{
    InstallerController c;
    // cumulative_pct only ever reaches 99; `complete` is what fills the bar.
    const QString last = stepEvent(8, 8, "Finalizing installation", 99, 1);
    feed(c, {last});
    QCOMPARE(c.installFraction(), 0.99);

    feed(c, {last, QStringLiteral(
                 "{\"type\":\"complete\",\"message\":\"Installation complete\"}")});
    QCOMPARE(c.installFraction(), 1.0);
}

void BackendTest::progressIgnoresNonProtocolLines()
{
    // fisherman's stderr is interleaved into the same stream.
    InstallerController c;
    feed(c, {QStringLiteral("fisherman: warning: something"),
             QStringLiteral("{ not json")});

    QVERIFY(qFuzzyIsNull(c.installFraction()));
    QCOMPARE(c.installStep(), 0);
    // A line that is not an event is shown as it stands.
    QVERIFY(c.log().contains(QStringLiteral("fisherman: warning: something")));
}

void BackendTest::progressRejectsTheInventedStepPrefix()
{
    // The exact bug this parse replaces. "[9/9] Finalizing" is not something
    // fisherman writes, so it must move nothing -- a parser that accepts it
    // is reading its own fixtures.
    InstallerController c;
    feed(c, {QStringLiteral("[1/9] Partitioning /dev/nvme0n1"),
             QStringLiteral("[9/9] Finalizing")});

    QVERIFY(qFuzzyIsNull(c.installFraction()));
    QCOMPARE(c.installStep(), 0);
}

void BackendTest::progressUnknownStepNameFallsBackToTheRawName()
{
    // A step added to fisherman later should show its real name, not nothing.
    InstallerController c;
    feed(c, {stepEvent(2, 8, "Polishing the hull", 10, 5)});

    QCOMPARE(c.installStepName(), QStringLiteral("Polishing the hull"));
}

void BackendTest::progressRendersEventsForTheLogPane()
{
    // The protocol is machine-readable and the pane is not: a log pane fed
    // raw stdout renders as a wall of JSON.
    InstallerController c;
    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87)});

    QVERIFY(c.log().contains(QStringLiteral("[5/8] Installing OS")));
    QVERIFY(!c.log().contains(QStringLiteral("cumulative_pct")));
}

static QString recoveryEvent(const QString &key)
{
    return QStringLiteral(
        R"({"type":"recovery_key","key":"%1",)"
        R"("timestamp":"2026-01-01T00:00:00Z","elapsed_ms":1000})").arg(key);
}

void BackendTest::recoveryKeyIsKeptNotJustPrinted()
{
    InstallerController c;
    QVERIFY(c.recoveryKey().isEmpty());

    feed(c, {recoveryEvent(QStringLiteral("abcd-efgh"))});

    QCOMPARE(c.recoveryKey(), QStringLiteral("abcd-efgh"));
    // Still in the log, which is what gets pasted into a bug report.
    QVERIFY(c.log().contains(QStringLiteral("abcd-efgh")));
}

void BackendTest::recoveryKeyHoldsRestartUntilAcknowledged()
{
    InstallerController c;
    // exitCode 0: loadDemoState() marks the install finished, so succeeded()
    // is true and the gate is live.
    feed(c, {recoveryEvent(QStringLiteral("abcd-efgh"))});

    QVERIFY2(c.recoveryKeyPending(), "an unacknowledged key must hold restart");
    c.setRecoveryAck(true);
    QVERIFY2(!c.recoveryKeyPending(), "ticking the box must release restart");
}

void BackendTest::recoveryKeyAbsentMeansNoGate()
{
    // No key means no panel and no gate: a non-TPM install must not be asked
    // to tick a box about a key it was never given.
    InstallerController c;
    c.loadDemoState(QStringLiteral("some log line"), 0);
    QVERIFY(c.succeeded());
    QVERIFY(!c.recoveryKeyPending());

    // A failed install enrolled nothing, so there is nothing to write down.
    InstallerController failed;
    failed.loadDemoState(recoveryEvent(QStringLiteral("abcd-efgh")), 1);
    QCOMPARE(failed.recoveryKey(), QStringLiteral("abcd-efgh"));
    QVERIFY(!failed.succeeded());
    QVERIFY(!failed.recoveryKeyPending());
}

void BackendTest::tpmProbeReadsTheVersionNotTheDirectory_data()
{
    QTest::addColumn<QString>("tree");
    QTest::addColumn<bool>("expected");

    // shared/tpm/fixtures/ -- the same trees every frontend's probe is
    // pointed at, so all five agree.
    QTest::newRow("tpm2: version reads 2") << QStringLiteral("tpm2") << true;
    QTest::newRow("tpm12: 1.2 cannot do tpm2-luks") << QStringLiteral("tpm12") << false;
    QTest::newRow("legacy-tpm2: no version file, tpmrm0 is TPM2-only")
        << QStringLiteral("legacy-tpm2") << true;
    QTest::newRow("legacy-none: neither signal") << QStringLiteral("legacy-none") << false;
}

void BackendTest::tpmProbeReadsTheVersionNotTheDirectory()
{
    QFETCH(QString, tree);
    QFETCH(bool, expected);

    const QString root = QDir(QStringLiteral(TPM_FIXTURES_DIR)).filePath(tree);
    if (!QFileInfo::exists(root)) {
        QSKIP("shared/tpm/fixtures is absent; this tree is checked out alone");
    }
    QCOMPARE(tpm::probe2(root), expected);
}

QTEST_APPLESS_MAIN(BackendTest)

#include "test_backend.moc"
