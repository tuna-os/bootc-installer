#include "offline.h"
#include "productname.h"
#include "readiness.h"
#include "recipe.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
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
    void productNameParsing_data();
    void productNameParsing();
    void offlineCommandHelpers();
    void readinessWriteStampFailsWithEmptyRuntimeDir();
    void readinessWriteStampWritesExpectedFields();
    void readinessWriteStampBlankPageBecomesUnknown();
};

void BackendTest::recipeDefaults()
{
    const Recipe recipe;

    QCOMPARE(recipe.filesystem, QStringLiteral("xfs"));
    QCOMPARE(recipe.encryption.type, QStringLiteral("none"));
    QCOMPARE(recipe.distroID, QStringLiteral("tunaos"));
    QCOMPARE(recipe.hostname, QStringLiteral("tunaos"));
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

void BackendTest::productNameParsing_data()
{
    QTest::addColumn<QString>("osRelease");
    QTest::addColumn<QString>("expected");

    QTest::newRow("double-quoted") << "NAME=TunaOS\nPRETTY_NAME=\"TunaOS KDE\"\n" << "TunaOS KDE";
    QTest::newRow("single-quoted") << "PRETTY_NAME='TunaOS KDE'\n" << "TunaOS KDE";
    QTest::newRow("unquoted") << "PRETTY_NAME=TunaOS\n" << "TunaOS";
    QTest::newRow("trimmed") << "  PRETTY_NAME=  \"TunaOS\"  \n" << "TunaOS";
    QTest::newRow("empty") << "PRETTY_NAME=\"\"\n" << "";
    QTest::newRow("absent") << "NAME=TunaOS\nID=tunaos\n" << "";
}

void BackendTest::productNameParsing()
{
    QFETCH(QString, osRelease);
    QFETCH(QString, expected);

    QCOMPARE(product::prettyNameFrom(osRelease), expected);
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

QTEST_APPLESS_MAIN(BackendTest)

#include "test_backend.moc"
