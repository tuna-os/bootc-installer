#include "offline.h"
#include "fisherman.h"
#include "account.h"
#include "imagecatalog.h"
#include "region.h"
#include "branding.h"
#include "readiness.h"
#include "recipe.h"
#include "installercontroller.h"
#include "probe.h"
#include "diskmodel.h"
#include "validate.h"
#include "redact.h"
#include "sourcecheck.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QProcessEnvironment>
#include <QRegularExpression>
#include <QSet>
#include <QCryptographicHash>
#include <QDirIterator>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QUrl>

#include <csignal>
#include <sys/stat.h>
#include <unistd.h>

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
    void recipeUserBlock();
    void recipeUserOmittedWithoutUsername();
    void controllerAccountFields();
    void validateUsernameProblem();
    void brandingFixtures();
    void brandingLogoFixtures();
    void brandingLogoSourceEscapesFilenames();
    void brandingLogoReachesController();
    void brandingText();
    void brandingNothingReadableIsNeutral();
    void encryptionChoicesReadTheCopyLayer();
    void offlineCommandHelpers();
    // #290: one resolver, and the staged, host-verified copy in a Flatpak.
    void fishermanResolverArgv();
    void fishermanCacheDirIsTheAppCache();
    void fishermanStagingNeedsTheSameBytesOnTheHost();
    void fishermanStagingRefusesAnUnsafeDirectory();
    void readinessWriteStampFailsWithEmptyRuntimeDir();
    void readinessWriteStampWritesExpectedFields();
    void readinessWriteStampBlankPageBecomesUnknown();

    // `fisherman probe --json` (shared/probe/README.md): the same fixtures
    // and expected renderings every frontend is tested against.
    void probeFixtures_data();
    void probeFixtures();
    void sourceCheckCases();
    void bootcStoreCases();
    void verificationCases();
    void sourceReplyOfAnOlderRequestIsDropped();
    void probeFakeEnvReachesTheController();
    void probeFailureOffersNothingAndSaysWhy();
    void probeCommandIsUnprivileged();

    // fisherman's progress protocol (shared/progress/README.md). KDE had no
    // progress bar; these pin the parse that now drives one.
    void progressStepEventMovesTheBar();
    void progressUsesCumulativePctNotStepOverTotal();
    void progressSubstepInterpolatesInsideTheLongStep();
    void progressReproducesTheSharedFractionCases();
    // fisherman's overall_pct and step_id (tuna-os/fisherman#270).
    void progressReproducesTheSharedOverallPctCases();
    void progressReproducesTheSharedErrorCases();
    void progressOverallPctDrivesTheBar();
    void progressStepIdReadsTheCopyLayer();
    void progressCompleteFillsTheBar();
    void progressIgnoresNonProtocolLines();
    void progressRejectsTheInventedStepPrefix();
    void progressUnknownStepNameFallsBackToTheRawName();

    // Recovery key (#129). The event used to be formatted into a log line
    // and dropped, so nothing could show it after the install.
    void recoveryKeyIsKeptNotJustPrinted();
    void recoveryKeyHoldsRestartUntilAcknowledged();
    void recoveryKeyAbsentMeansNoGate();
    void recoveryKeyRedactionFollowsTheSharedCases();
    void recoveryKeyIsNotInTheLogFile();
    void progressRendersEventsForTheLogPane();

    // stdout and stderr shared one line buffer, so a stdout event split
    // across two reads merged with stderr output and lost its leading '{'.
    void streamsKeepSeparatePartialLines();

    // The wrapper runs pkexec under a host bash and leads its own process
    // group, the shared cancel contract.
    void flatpakWrapperPassesStdinOutputAndStatusThrough();
    void wrapperLeadsItsOwnProcessGroup();
    void validateAnswersBecomeCopyLines();
    void validateSendsAPartialRecipeOnStdin();
    void liveMediaComesFromTheProbe();

    // The image catalog (fisherman's images.json, resolved like the GNOME and
    // XFCE frontends resolve it): tag+registry composition, ancestor
    // inheritance, @alias resolution, and the needs_user_creation default.
    void catalogParseComposesTagsAndInherits();
    void catalogParseRejectsGarbage();
    void catalogLoadPrefersTheEnvOverride();
    void catalogSelectionDrivesTheRecipeAndTheUserStep();
    void catalogAbsentMeansAccountRequired();
    // The shared catalog contract (shared/catalog/README.md): this parser
    // reads fixtures/catalog.json to the answers in fixtures/expected.json.
    void catalogContractSearchPaths();
    void catalogContractOverride();
    void catalogContractDefaultSelection();
    void catalogContractLeaves();
    void catalogContractRecipes();
    void catalogBrandingDefaultWinsInTheController();
    void catalogLoadSkipsAFileThatIsNoCatalog();
    void catalogLiveMediaReadsTheLeafOfTheLiveImage();
    void liveLeafTakesTheOperatorLayout();
    void catalogSelectionReplacesThePreviousLeaf();
    void catalogNvidiaDetection();
    void nvidiaDetectionFollowsThePciFixture();
    void catalogFilesystemProblemReachesTheDiskStep();
    // #302: the shared group list and the operator's.
    void accountGroupsAreTheSharedFile();
    void accountGroupCases();
    // #299: cancel signals the group and is not a crash.
    void cancelSignalsTheGroupAndIsNotACrash();
    void exitCode130IsCancelled();
    void anEndWithoutCancelIsStillAFailure();
    void cancelAsksFirstInTheQml();
    // #301
    void networkTargetsFollowTheFixture();
    void connectivityTriesTheImageRegistryFirst();
    // #300
    void qmlStringsGoThroughQsTr();
    void confirmPageListsNoLocaleRows();

    // The user block follows the account step: omitted when the selected
    // image creates its own first user, even with a typed username.
    void recipeUserOmittedWhenNotRequired();

    // The hardware gates (the GNOME cpu/ram/unsupported windows): fatal on
    // uefi, overridable on ram/cpu, absent when everything is met.
    void requirementsGates();
    void cancelInstallWithoutAProcessIsANoOp();
    void copyLogWithoutAClipboardIsANoOp();

    // Region & language preflight data comes from the platform, not from a
    // bundled copy: Qt's locale database, the XKB list, QTimeZone.
    void regionListsComeFromThePlatform();
    void regionTimezoneDisplay();
    void regionRejectsUnreachableHosts();

    // The done screen's tour is the selected leaf's carousel slides.
    void tourSlidesFollowTheSelection();
};

void BackendTest::recipeDefaults()
{
    const Recipe recipe;

    QCOMPARE(recipe.filesystem, QStringLiteral("xfs"));
    QCOMPARE(recipe.encryption.type, QStringLiteral("none"));
    // Neutral until InstallerController fills them from the branding contract.
    QVERIFY(recipe.distroID.isEmpty());
    QVERIFY(recipe.hostname.isEmpty());
    QVERIFY(!recipe.selinuxDisabled);
    QVERIFY(!recipe.liveMode);
}

void BackendTest::recipeJsonOmitsOptionalValues()
{
    const QJsonObject json = Recipe{}.toJson();

    // "image" is not one of the optional keys for a normal install: fisherman
    // is always handed it, and rejects an empty one off live media
    // (image_required). Only on live media (probe's live.is_live) may it be
    // omitted — see the liveMode branch in Recipe::toJson().
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
    // The image, hostname and encryption rules are fisherman's
    // (`validate --json`, the install runs them before touching a disk):
    // this frontend no longer keeps a copy of them.
    QTest::newRow("image-is-fishermans") << "/dev/vda" << "" << false << "tunaos" << "none" << "" << "";
    QTest::newRow("hostname-is-fishermans") << "/dev/vda" << "example/image" << false << "" << "none" << "" << "";
    QTest::newRow("encryption-is-fishermans") << "/dev/vda" << "example/image" << false << "tunaos" << "plain" << "" << "";
    QTest::newRow("passphrase-is-fishermans") << "/dev/vda" << "example/image" << false << "tunaos" << "luks-passphrase" << "" << "";
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

    Recipe withUser = original;
    withUser.user.username = QStringLiteral("alex");
    withUser.user.fullname = QStringLiteral("Alex Example");
    withUser.user.password = QStringLiteral("pw");
    const Recipe restoredUser = Recipe::fromJson(withUser.toJson());
    QCOMPARE(restoredUser.user.username, withUser.user.username);
    QCOMPARE(restoredUser.user.fullname, withUser.user.fullname);
    QCOMPARE(restoredUser.user.password, withUser.user.password);
    QCOMPARE(restoredUser.user.groups, account::defaultGroups());
}

// The schema's `user` block: username, fullname, password and the shared
// default groups (shared/account/groups.json, #302).
void BackendTest::recipeUserBlock()
{
    Recipe recipe;
    recipe.disk = QStringLiteral("/dev/vda");
    recipe.user.username = QStringLiteral("alex");
    recipe.user.fullname = QStringLiteral("Alex Example");
    recipe.user.password = QStringLiteral("s3cret");

    const QJsonObject json = recipe.toJson();
    QVERIFY(json.contains(QStringLiteral("user")));
    const QJsonObject user = json.value(QStringLiteral("user")).toObject();
    QCOMPARE(user.keys(), (QStringList{QStringLiteral("fullname"), QStringLiteral("groups"),
                                       QStringLiteral("password"), QStringLiteral("username")}));
    QCOMPARE(user.value(QStringLiteral("username")).toString(), QStringLiteral("alex"));
    QCOMPARE(user.value(QStringLiteral("fullname")).toString(), QStringLiteral("Alex Example"));
    QCOMPARE(user.value(QStringLiteral("password")).toString(), QStringLiteral("s3cret"));
    QCOMPARE(user.value(QStringLiteral("groups")).toArray(), QJsonArray::fromStringList(account::defaultGroups()));
    QVERIFY(account::defaultGroups().contains(QStringLiteral("wheel")));
    QVERIFY(account::defaultGroups().contains(QStringLiteral("sudo")));

    // An empty full name is still written (the schema allows it, and XFCE
    // writes it the same way); fisherman then leaves the GECOS field empty.
    recipe.user.fullname.clear();
    QVERIFY(recipe.toJson().value(QStringLiteral("user")).toObject()
                .value(QStringLiteral("fullname")).toString().isEmpty());
}

void BackendTest::recipeUserOmittedWithoutUsername()
{
    // No username, no block: fisherman reads an absent `user` as "create no
    // account", and a block with an empty username the same way, so the
    // recipe carries neither the block nor a stray password.
    QVERIFY(!Recipe{}.toJson().contains(QStringLiteral("user")));

    Recipe recipe;
    recipe.user.fullname = QStringLiteral("Alex Example");
    recipe.user.password = QStringLiteral("left over");
    const QJsonObject json = recipe.toJson();
    QVERIFY(!json.contains(QStringLiteral("user")));
    QVERIFY(!QJsonDocument(json).toJson().contains("left over"));

    QCOMPARE(Recipe::fromJson(QJsonObject{}).user.groups, account::defaultGroups());
}

void BackendTest::controllerAccountFields()
{
    InstallerController c;
    QVERIFY(c.username().isEmpty());
    QSignalSpy changed(&c, &InstallerController::recipeChanged);
    c.setUsername(QStringLiteral("alex"));
    c.setFullname(QStringLiteral("Alex Example"));
    c.setUserPassword(QStringLiteral("pw"));
    QCOMPARE(changed.count(), 3);
    c.setUsername(QStringLiteral("alex"));
    QCOMPARE(changed.count(), 3);
    QCOMPARE(c.username(), QStringLiteral("alex"));
    QCOMPARE(c.fullname(), QStringLiteral("Alex Example"));
    QCOMPARE(c.userPassword(), QStringLiteral("pw"));

    // The account step's field goes to `validate --json --partial`: the
    // username only. fisherman has no rule for the rest, and the password
    // has no business on a validate call.
    const QJsonObject partial = QJsonDocument::fromJson(c.partialRecipe()).object();
    QCOMPARE(partial.value(QStringLiteral("user")).toObject(),
             (QJsonObject{{QStringLiteral("username"), QStringLiteral("alex")}}));
    QVERIFY(!c.partialRecipe().contains("pw\""));
}

void BackendTest::validateUsernameProblem()
{
#ifndef VALIDATE_GOLDENS_DIR
    QSKIP("no goldens");
#else
    QFile golden(QStringLiteral(VALIDATE_GOLDENS_DIR) + QStringLiteral("/partial-user.golden"));
    if (!golden.open(QIODevice::ReadOnly))
        QSKIP("the fisherman submodule is not checked out");
    const QByteArray answer = golden.readAll();

    InstallerController c;
    QVERIFY(c.usernameProblem().isEmpty());
    c.applyValidateAnswer(answer);
    QCOMPARE(c.usernameProblem(), c.text(QStringLiteral("validate_username_reserved")));
    QVERIFY(!c.usernameProblem().isEmpty());
    // A username problem is the account step's alone.
    QVERIFY(c.hostnameProblem().isEmpty());
    QVERIFY(c.encryptionProblem().isEmpty());

    // Every username code fisherman has reads a copy line.
    for (const char *code : {"username_too_long", "username_invalid_start",
                             "username_invalid_char", "username_reserved"}) {
        c.applyValidateAnswer(QStringLiteral(
            R"({"protocol_version":1,"valid":false,"errors":[{"field":"user.username","code":"%1","message":"m"}]})")
                                  .arg(QLatin1String(code)).toUtf8());
        QVERIFY2(c.usernameProblem() != QStringLiteral("m"), code);
        QCOMPARE(c.usernameProblem(), c.text(QStringLiteral("validate_") + QLatin1String(code)));
    }
    c.applyValidateAnswer(R"({"protocol_version":1,"valid":true,"errors":[]})");
    QVERIFY(c.usernameProblem().isEmpty());
#endif
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

    // The compiled-in defaults are shared/branding/copy-defaults.json: CMake
    // reads that file, so there is no copy to compare it with.
    QVERIFY(!branding::copyDefaults().value(QStringLiteral("welcome_title")).isEmpty());
}

void BackendTest::brandingLogoFixtures()
{
    const QString path = QStringLiteral(BRANDING_FIXTURES_DIR) + QStringLiteral("/logo-paths.json");
    const QJsonArray cases = readJsonObject(path).value(QStringLiteral("cases")).toArray();
    QVERIFY2(!cases.isEmpty(), qPrintable(QStringLiteral("Missing logo fixtures: ") + path));
    for (const QJsonValue &entry : cases) {
        const QJsonObject spec = entry.toObject();
        const branding::Logo got = branding::resolveLogo(
            spec.value(QStringLiteral("spec")).toString(), spec.value(QStringLiteral("in_flatpak")).toBool());
        const QString kind = got.kind == branding::Logo::Kind::File ? QStringLiteral("file")
            : got.kind == branding::Logo::Kind::Theme ? QStringLiteral("theme") : QStringLiteral("none");
        QCOMPARE(kind, spec.value(QStringLiteral("kind")).toString());
        QCOMPARE(got.value, spec.value(QStringLiteral("value")).toString());
        if (got.kind == branding::Logo::Kind::File)
            QCOMPARE(QUrl(got.source()).toLocalFile(), got.value);
        else
            QCOMPARE(got.source(), got.value);
    }
}

void BackendTest::brandingLogoSourceEscapesFilenames()
{
    const QString path = QStringLiteral("/tmp/logo with spaces #1%20?.png");
    const branding::Logo logo = branding::resolveLogo(path, false);
    QCOMPARE(logo.source(), QStringLiteral("file:///tmp/logo%20with%20spaces%20%231%2520%3F.png"));
    QCOMPARE(QUrl(logo.source()).toLocalFile(), path);
    QVERIFY(branding::resolveLogo(QStringLiteral("  "), true).source().isEmpty());
    QCOMPARE(branding::resolveLogo(QStringLiteral(" example-logo "), true).source(),
             QStringLiteral("example-logo"));
    QCOMPARE(branding::resolveLogo(QStringLiteral("/usr-local/logo.svg"), true).value,
             QStringLiteral("/usr-local/logo.svg"));
    QVERIFY(branding::resolveLogo(QStringLiteral("https://example.com/logo.png"), false).source().isEmpty());
}

void BackendTest::brandingLogoReachesController()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QFile f(dir.filePath(QStringLiteral("branding.json")));
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write(R"({"logo": "/usr/share/example/logo with spaces #1.svg"})");
    f.close();
    const QByteArray previous = qgetenv("BOOTC_INSTALLER_BRANDING");
    qputenv("BOOTC_INSTALLER_BRANDING", f.fileName().toUtf8());
    InstallerController controller;
    if (previous.isNull())
        qunsetenv("BOOTC_INSTALLER_BRANDING");
    else
        qputenv("BOOTC_INSTALLER_BRANDING", previous);
    QCOMPARE(controller.logoSource(), branding::resolveLogo(
        QStringLiteral("/usr/share/example/logo with spaces #1.svg"), offline::inFlatpak()).source());
    QCOMPARE(controller.property("logoSource").toString(), controller.logoSource());
}

void BackendTest::encryptionChoicesReadTheCopyLayer()
{
    // The ids and their order are fisherman's encryption-choices.json,
    // compiled in from shared/recipe/encryption-choices.json.
    const QStringList types = {QStringLiteral("none"), QStringLiteral("luks-passphrase"),
                               QStringLiteral("tpm2-luks"), QStringLiteral("tpm2-luks-passphrase")};
    QCOMPARE(Recipe::encryptionTypes(), types);
    QVERIFY(Recipe::needsPassphrase(QStringLiteral("tpm2-luks-passphrase")));
    QVERIFY(!Recipe::needsPassphrase(QStringLiteral("tpm2-luks")));
    QVERIFY(!Recipe::needsPassphrase(QString()));
    QVERIFY(Recipe::needsTpm2(QStringLiteral("tpm2-luks")));
    QVERIFY(!Recipe::needsTpm2(QStringLiteral("luks-passphrase")));

    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QFile f(dir.filePath(QStringLiteral("branding.json")));
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write(R"({"name": "Marlin", "copy": {"encryption_tpm2_luks_label": "Hardware key"}})");
    f.close();
    qputenv("BOOTC_INSTALLER_BRANDING", f.fileName().toUtf8());
    InstallerController c;
    qunsetenv("BOOTC_INSTALLER_BRANDING");

    QCOMPARE(c.encryptionTypes(), types);
    for (const QString &type : types) {
        QVERIFY2(!c.encryptionLabel(type).isEmpty(), qPrintable(type));
        QVERIFY2(!c.encryptionDescription(type).isEmpty(), qPrintable(type));
    }
    // The confirm step used to say "None" and "Passphrase (LUKS)" here while
    // the encryption step said "No encryption" and "Passphrase".
    QCOMPARE(c.encryptionLabel(QStringLiteral("none")), QStringLiteral("No encryption"));
    QCOMPARE(c.encryptionLabel(QString()), QStringLiteral("No encryption"));
    QCOMPARE(c.encryptionLabel(QStringLiteral("luks-passphrase")), QStringLiteral("Passphrase"));
    QCOMPARE(c.encryptionDescription(QStringLiteral("luks-passphrase")),
             QStringLiteral("You'll type it at every boot."));
    // A product renames a choice once, in its branding file.
    QCOMPARE(c.encryptionLabel(QStringLiteral("tpm2-luks")), QStringLiteral("Hardware key"));
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

// The one resolver (#290): native, Flatpak and live media.
void BackendTest::fishermanResolverArgv()
{
    const QString native = QStringLiteral("/usr/local/bin/fisherman");
    const QString staged = QStringLiteral("/home/u/.var/app/org.example.Installer/cache/bootc-installer/fisherman");

    // Native: pkexec, as the GNOME frontend. A bash wrapper, so this
    // frontend owns a process group it can signal. `-`: the recipe goes on
    // stdin (fisherman#276), never as a path.
    const fisherman::Commands installed = fisherman::resolve(false, false, QString());
    QCOMPARE(installed.unprivileged, QStringList{native});
    QCOMPARE(installed.install,
             (QStringList{QStringLiteral("bash"), QStringLiteral("-c"),
                          QStringLiteral("pkexec /usr/local/bin/fisherman -; exit $?")}));

    // Live media, native: the live user has passwordless sudo and can have
    // no polkit agent. -n: never a prompt nobody can answer.
    const fisherman::Commands live = fisherman::resolve(false, true, QString());
    QCOMPARE(live.unprivileged, QStringList{native});
    QCOMPARE(live.install,
             (QStringList{QStringLiteral("bash"), QStringLiteral("-c"),
                          QStringLiteral("sudo -n /usr/local/bin/fisherman -; exit $?")}));

    // Flatpak: the staged copy, on the host, for all three uses. pkexec
    // inside a host bash, so fisherman's parent is a process this frontend
    // owns (fisherman cancels when its parent dies). Never the host's
    // /usr/local/bin/fisherman, and never sudo.
    for (const bool isLive : {false, true}) {
        const fisherman::Commands sandboxed = fisherman::resolve(true, isLive, staged);
        QCOMPARE(sandboxed.unprivileged,
                 (QStringList{QStringLiteral("flatpak-spawn"), QStringLiteral("--host"), staged}));
        QCOMPARE(sandboxed.install,
                 (QStringList{QStringLiteral("flatpak-spawn"), QStringLiteral("--host"),
                              QStringLiteral("bash"), QStringLiteral("-c"),
                              QStringLiteral("pkexec '%1' -; exit $?").arg(staged)}));
        QVERIFY(!sandboxed.install.join(QLatin1Char(' ')).contains(native));
    }
    // A path with a quote cannot leave the argument.
    QVERIFY(fisherman::resolve(true, false, QStringLiteral("/a'b/fisherman")).install.last()
                .startsWith(QStringLiteral("pkexec '/a'\\''b/fisherman' -;")));

    // No other file in src/ names the binary: probe, validate and the
    // install all go through the resolver.
    QDirIterator it(QStringLiteral(KDE_SOURCE_DIR "/src"), {QStringLiteral("*.cpp"), QStringLiteral("*.h"), QStringLiteral("*.qml")},
                    QDir::Files, QDirIterator::Subdirectories);
    int seen = 0;
    while (it.hasNext()) {
        const QString path = it.next();
        ++seen;
        if (QFileInfo(path).fileName().startsWith(QStringLiteral("fisherman.")))
            continue;
        QFile f(path);
        QVERIFY(f.open(QIODevice::ReadOnly));
        const QByteArray text = f.readAll();
        QVERIFY2(!text.contains("/usr/local/bin/fisherman\"") && !text.contains("/app/bin/fisherman"),
                 qPrintable(path + QStringLiteral(" names the fisherman binary; use fisherman.h")));
    }
    QVERIFY(seen > 10);
}

void BackendTest::fishermanCacheDirIsTheAppCache()
{
    QProcessEnvironment env;
    env.insert(QStringLiteral("HOME"), QStringLiteral("/var/home/test"));
    env.insert(QStringLiteral("XDG_CACHE_HOME"), QStringLiteral("/var/home/test/.var/app/app.id/cache"));
    QCOMPARE(fisherman::cacheDir(env), QStringLiteral("/var/home/test/.var/app/app.id/cache/bootc-installer"));
    // Never derived from HOME: no variable, or a relative one, is an error.
    for (const QString &bad : {QString(), QStringLiteral("relative")}) {
        QProcessEnvironment e;
        e.insert(QStringLiteral("HOME"), QStringLiteral("/home/test"));
        if (!bad.isEmpty())
            e.insert(QStringLiteral("XDG_CACHE_HOME"), bad);
        QString error;
        QVERIFY(fisherman::cacheDir(e, &error).isEmpty());
        QVERIFY(error.contains(QStringLiteral("absolute")));
    }
}

void BackendTest::fishermanStagingNeedsTheSameBytesOnTheHost()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString source = dir.filePath(QStringLiteral("source"));
    QFile f(source);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write("test helper bytes");
    f.close();
    QVERIFY(QDir().mkpath(dir.filePath(QStringLiteral("cache"))));
    QFile::setPermissions(dir.filePath(QStringLiteral("cache")),
                          QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner);
    const QString cache = dir.filePath(QStringLiteral("cache/bootc-installer"));
    const QString target = cache + QStringLiteral("/fisherman");
    const QByteArray digest = QCryptographicHash::hash("test helper bytes", QCryptographicHash::Sha256).toHex();

    QStringList asked;
    const auto host = [&](int code, const QByteArray &out) {
        return [&asked, code, out](const QStringList &argv) {
            asked = argv;
            return fisherman::HostResult{code, out};
        };
    };
    // The host sees the same bytes: staged, 0700, and that path is returned.
    fisherman::Staging s = fisherman::stage(source, cache, host(0, digest + "  " + target.toUtf8() + "\n"));
    QVERIFY2(s.ok, qPrintable(s.error));
    QCOMPARE(s.path, target);
    QCOMPARE(asked, (QStringList{QStringLiteral("sha256sum"), QStringLiteral("--"), target}));
    struct stat st{};
    QCOMPARE(::stat(QFile::encodeName(target).constData(), &st), 0);
    QCOMPARE(int(st.st_mode & 0777), 0700);
    QFile staged(target);
    QVERIFY(staged.open(QIODevice::ReadOnly));
    QCOMPARE(staged.readAll(), QByteArray("test helper bytes"));
    // The host cannot hash it, or sees other bytes: not usable.
    s = fisherman::stage(source, cache, host(1, QByteArray()));
    QVERIFY(!s.ok);
    QVERIFY(s.path.isEmpty());
    QVERIFY(!s.error.isEmpty());
    s = fisherman::stage(source, cache, host(0, QByteArray(64, '0') + "  " + target.toUtf8()));
    QVERIFY(!s.ok);
    // No packaged binary: an error, and the host is not asked.
    asked.clear();
    QVERIFY(!fisherman::stage(dir.filePath(QStringLiteral("absent")), cache, host(0, digest)).ok);
    QVERIFY(asked.isEmpty());
    // A relative cache directory is refused.
    QVERIFY(!fisherman::stage(source, QStringLiteral("relative"), host(0, digest)).ok);
}

void BackendTest::fishermanStagingRefusesAnUnsafeDirectory()
{
#ifndef Q_OS_UNIX
    QSKIP("POSIX ownership and modes");
#else
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString source = dir.filePath(QStringLiteral("source"));
    QFile f(source);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write("x");
    f.close();
    bool asked = false;
    const auto host = [&asked](const QStringList &) {
        asked = true;
        return fisherman::HostResult{0, QByteArray()};
    };
    // A cache directory that is a symlink.
    QVERIFY(QDir().mkpath(dir.filePath(QStringLiteral("real"))));
    QVERIFY(QFile::link(dir.filePath(QStringLiteral("real")), dir.filePath(QStringLiteral("link"))));
    QVERIFY(!fisherman::stage(source, dir.filePath(QStringLiteral("link")), host).ok);
    // A cache directory others can write to.
    const QString open = dir.filePath(QStringLiteral("open"));
    QVERIFY(QDir().mkpath(open));
    QVERIFY(::chmod(QFile::encodeName(open).constData(), 0777) == 0);
    QVERIFY(!fisherman::stage(source, open, host).ok);
    QVERIFY2(!asked, "the host was asked about a directory that was refused");
#endif
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

// shared/progress/fraction-cases.json is generated from the canonical
// parser and pins the bar after every event; every frontend's parser must
// reproduce it. It exists because #115's deploy-phase weighting was first
// written in Python only, leaving this bar on the old formula.
static void replayProgressCases(const QString &file, int minCases)
{
    QFile f(QStringLiteral(PROGRESS_FIXTURES_DIR "/") + file);
    if (!f.exists())
        QSKIP("shared/progress is not present (tree checked out alone)");
    QVERIFY(f.open(QIODevice::ReadOnly));
    const QJsonArray cases = QJsonDocument::fromJson(f.readAll()).object().value(QStringLiteral("cases")).toArray();
    QVERIFY(cases.size() >= minCases);
    for (const QJsonValue &cv : cases) {
        const QJsonObject kase = cv.toObject();
        const QString name = kase.value(QStringLiteral("name")).toString();
        const QJsonArray events = kase.value(QStringLiteral("events")).toArray();
        const QJsonArray bars = kase.value(QStringLiteral("bar")).toArray();
        QCOMPARE(events.size(), bars.size());
        QStringList lines;
        for (int i = 0; i < events.size(); ++i) {
            lines << QString::fromUtf8(QJsonDocument(events.at(i).toObject()).toJson(QJsonDocument::Compact));
            // Fresh controller fed every event so far: loadDemoState() resets
            // and replays through appendLine(), the live entry point.
            InstallerController c;
            feed(c, lines);
            const double want = bars.at(i).toDouble();
            if (qAbs(c.installFraction() - want) > 1e-6)
                QFAIL(qPrintable(QStringLiteral("%1 event %2: bar %3 want %4")
                                     .arg(name).arg(i).arg(c.installFraction()).arg(want)));
        }
    }
}

void BackendTest::progressReproducesTheSharedFractionCases()
{
    replayProgressCases(QStringLiteral("fraction-cases.json"), 5);
}

// shared/progress/error-cases.json: the last `error` event is kept as
// {message, code, field}, as the canonical parser keeps it, and it does not
// move the bar.
void BackendTest::progressReproducesTheSharedErrorCases()
{
    replayProgressCases(QStringLiteral("error-cases.json"), 6);
    QFile f(QStringLiteral(PROGRESS_FIXTURES_DIR "/error-cases.json"));
    QVERIFY(f.open(QIODevice::ReadOnly));
    const QJsonArray cases = QJsonDocument::fromJson(f.readAll()).object().value(QStringLiteral("cases")).toArray();
    for (const QJsonValue &cv : cases) {
        const QJsonObject kase = cv.toObject();
        QStringList lines;
        for (const QJsonValue &event : kase.value(QStringLiteral("events")).toArray())
            lines << QString::fromUtf8(QJsonDocument(event.toObject()).toJson(QJsonDocument::Compact));
        InstallerController c;
        feed(c, lines);
        const QJsonValue want = kase.value(QStringLiteral("error"));
        const QVariantMap expected = want.isNull() ? QVariantMap() : want.toObject().toVariantMap();
        QVERIFY2(c.installError() == expected, qPrintable(kase.value(QStringLiteral("name")).toString()));
    }
}

// shared/progress/overall-pct-cases.json: fisherman's overall_pct is the
// bar; an event without it falls back to the derivation above.
void BackendTest::progressReproducesTheSharedOverallPctCases()
{
    replayProgressCases(QStringLiteral("overall-pct-cases.json"), 3);
}

void BackendTest::progressOverallPctDrivesTheBar()
{
    InstallerController c;
    const QString flatpaks = QStringLiteral(
        "{\"type\":\"step\",\"step\":6,\"total_steps\":8,\"step_name\":\"Copying system Flatpaks\","
        "\"step_id\":\"flatpaks\",\"cumulative_pct\":88,\"weight_pct\":11,\"overall_pct\":88}");
    // The derivation holds the bar through the Flatpak copy; overall_pct
    // moves it.
    feed(c, {flatpaks, QStringLiteral(
                 "{\"type\":\"substep\",\"message\":\"Copying Flatpak data: 50%\",\"overall_pct\":93.5}")});
    QCOMPARE(c.installFraction(), 0.935);

    // Never backwards, even if an event said so.
    feed(c, {flatpaks,
             QStringLiteral("{\"type\":\"substep\",\"message\":\"a\",\"overall_pct\":93.5}"),
             QStringLiteral("{\"type\":\"substep\",\"message\":\"b\",\"overall_pct\":90}")});
    QCOMPARE(c.installFraction(), 0.935);

    // Without overall_pct the bar is derived, as before.
    feed(c, {stepEvent(5, 8, "Installing OS", 1, 87),
             QStringLiteral("{\"type\":\"substep\",\"message\":\"Pulling image: layer 2/4\"}")});
    QVERIFY(qAbs(c.installFraction() - (1 + 0.5 * 0.6 * 87) / 100.0) < 1e-9);
}

void BackendTest::progressStepIdReadsTheCopyLayer()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QFile f(dir.filePath(QStringLiteral("branding.json")));
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write(R"({"name": "Marlin", "copy": {"step_flatpaks": "Adding apps to {name}"}})");
    f.close();
    qputenv("BOOTC_INSTALLER_BRANDING", f.fileName().toUtf8());
    InstallerController c;
    qunsetenv("BOOTC_INSTALLER_BRANDING");

    const auto step = [](const char *name, const char *id) {
        return QStringLiteral(
                   "{\"type\":\"step\",\"step\":3,\"total_steps\":8,\"step_name\":\"%1\","
                   "\"step_id\":\"%2\",\"cumulative_pct\":1,\"weight_pct\":0,\"overall_pct\":1}")
            .arg(QString::fromLatin1(name), QString::fromLatin1(id));
    };
    // A product's branding.json renames the step.
    feed(c, {step("Copying system Flatpaks", "flatpaks")});
    QCOMPARE(c.installStepName(), QStringLiteral("Adding apps to Marlin"));
    // The neutral default for an id the product left alone.
    feed(c, {step("Installing OS", "install_os")});
    QCOMPARE(c.installStepName(), QStringLiteral("Installing Marlin…"));
    // An id the copy does not know shows fisherman's step name.
    feed(c, {step("Polishing the hull", "polish_hull")});
    QCOMPARE(c.installStepName(), QStringLiteral("Polishing the hull"));
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
    // Still in the log pane, which the same user reads on the same screen.
    QVERIFY(c.log().contains(QStringLiteral("abcd-efgh")));
    // Not in the copy that leaves the installer (#337).
    QVERIFY(!c.logForSharing().contains(QStringLiteral("abcd-efgh")));
    QVERIFY(c.logForSharing().contains(redact::kPlaceholder));
}

// shared/progress/recovery-key-cases.json: the redacted form is the same in
// every frontend that keeps a log, byte for byte.
static QJsonObject recoveryKeyCases()
{
    QFile f(QStringLiteral(PROGRESS_FIXTURES_DIR "/recovery-key-cases.json"));
    if (!f.open(QIODevice::ReadOnly))
        return {};
    return QJsonDocument::fromJson(f.readAll()).object();
}

void BackendTest::recoveryKeyRedactionFollowsTheSharedCases()
{
    const QJsonObject spec = recoveryKeyCases();
    if (spec.isEmpty())
        QSKIP("shared/progress is not present (tree checked out alone)");
    const QString key = spec.value(QStringLiteral("key")).toString();
    QCOMPARE(redact::kPlaceholder, spec.value(QStringLiteral("placeholder")).toString());
    const QJsonArray lines = spec.value(QStringLiteral("lines")).toArray();
    QVERIFY(lines.size() >= 5);
    for (const QJsonValue &v : lines) {
        const QJsonObject c = v.toObject();
        const QString known = c.value(QStringLiteral("known_key")).toBool() ? key : QString();
        const QString got = redact::recoveryKey(c.value(QStringLiteral("line")).toString(), known);
        QVERIFY2(got == c.value(QStringLiteral("redacted")).toString(),
                 qPrintable(c.value(QStringLiteral("name")).toString() + QStringLiteral(": got ") + got));
    }
    QCOMPARE(redact::recoveryKey(QString()), QString());
}

void BackendTest::recoveryKeyIsNotInTheLogFile()
{
    const QJsonObject spec = recoveryKeyCases();
    if (spec.isEmpty())
        QSKIP("shared/progress is not present (tree checked out alone)");
    const QString key = spec.value(QStringLiteral("key")).toString();
    QVERIFY(key.size() > 8);
    QFile transcript(QStringLiteral(PROGRESS_FIXTURES_DIR "/")
                     + spec.value(QStringLiteral("transcript")).toString());
    QVERIFY(transcript.open(QIODevice::ReadOnly));
    const QByteArray events = transcript.readAll();
    QVERIFY(events.contains(key.toUtf8()));

    // The log file goes to the application data directory.
    QTemporaryDir data;
    QVERIFY(data.isValid());
    const QByteArray oldData = qgetenv("XDG_DATA_HOME");
    qputenv("XDG_DATA_HOME", data.path().toUtf8());

    InstallerController c;
    c.openLogFile();
    const QString path = c.logPath();
    QVERIFY2(path.startsWith(data.path()), qPrintable(path));
    // The live path: stdout carries the events, stderr repeats the key.
    const QString stderrLine = QStringLiteral("enrolled slot 1 with %1.").arg(key);
    const qsizetype half = events.size() / 2;
    c.consumeStdout(events.left(half));
    c.consumeStdout(events.mid(half));
    c.consumeStderr(stderrLine.toUtf8() + '\n');
    c.consumeStderr(QByteArrayLiteral("Recovery key: ") + key.toUtf8());
    c.flushStreams();
    c.closeLogFile();
    if (oldData.isNull())
        qunsetenv("XDG_DATA_HOME");
    else
        qputenv("XDG_DATA_HOME", oldData);

    // The key is still there for the done page.
    QCOMPARE(c.recoveryKey(), key);

    QFile log(path);
    QVERIFY(log.open(QIODevice::ReadOnly));
    const QByteArray written = log.readAll();
    QVERIFY2(!written.contains(key.toUtf8()), "the recovery key is in the log file");

    // The file is the transcript, with the one event in its redacted form.
    QByteArrayList want;
    int redacted = 0;
    for (const QByteArray &line : events.split('\n')) {
        if (line.isEmpty())
            continue;
        if (line.contains("\"recovery_key\"")) {
            want << spec.value(QStringLiteral("redacted_event")).toString().toUtf8();
            ++redacted;
        } else {
            want << line;
        }
    }
    QCOMPARE(redacted, 1);
    // The event's type is still in the file: a reader can see that a key
    // was sent.
    QVERIFY(want.join('\n').contains("\"type\":\"recovery_key\""));
    want << QByteArrayLiteral("[stderr] enrolled slot 1 with [redacted].")
         << QByteArrayLiteral("[stderr] Recovery key: [redacted]");
    QCOMPARE(written, want.join('\n') + '\n');

    // The clipboard copy has the same rule; the pane is what the user sees.
    QVERIFY(c.log().contains(key));
    QVERIFY(!c.logForSharing().contains(key));
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

void BackendTest::probeFixtures_data()
{
    QTest::addColumn<QString>("name");
    QTest::newRow("laptop") << QStringLiteral("laptop");
    QTest::newRow("container") << QStringLiteral("container");
    QTest::newRow("vm") << QStringLiteral("vm");
    QTest::newRow("pure-live-oci") << QStringLiteral("pure-live-oci");
}

void BackendTest::probeFixtures()
{
    QFETCH(QString, name);
    const QDir dir(QStringLiteral(PROBE_FIXTURES_DIR));
    QFile input(dir.filePath(name + QStringLiteral(".json")));
    QFile expectedFile(dir.filePath(name + QStringLiteral(".expected.json")));
    if (!input.open(QIODevice::ReadOnly) || !expectedFile.open(QIODevice::ReadOnly))
        QSKIP("shared/probe/fixtures is absent; this tree is checked out alone");
    const QJsonObject expected = QJsonDocument::fromJson(expectedFile.readAll()).object();

    const probe::Result result = probe::parse(input.readAll());
    QVERIFY2(result.ok, qPrintable(result.error));

    // What the disk step's rows carry, through the model the QML reads.
    DiskModel model;
    model.setResult(result);
    const QJsonArray want = expected.value(QStringLiteral("disks")).toArray();
    QCOMPARE(model.rowCount(), want.size());
    const QHash<int, QByteArray> roles = model.roleNames();
    auto role = [&](const QByteArray &n) { return roles.key(n); };
    for (int i = 0; i < want.size(); ++i) {
        const QJsonObject w = want.at(i).toObject();
        const QModelIndex idx = model.index(i);
        QCOMPARE(model.data(idx, role("device")).toString(), w.value(QStringLiteral("path")).toString());
        QCOMPARE(model.data(idx, role("title")).toString(), w.value(QStringLiteral("title")).toString());
        QCOMPARE(model.data(idx, role("model")).toString(), w.value(QStringLiteral("model")).toString());
        QCOMPARE(model.data(idx, role("size")).toString(), w.value(QStringLiteral("size_label")).toString());
        QCOMPARE(model.data(idx, role("transport")).toString(),
                 w.value(QStringLiteral("transport_label")).toString());
        QCOMPARE(model.data(idx, role("removable")).toBool(), w.value(QStringLiteral("removable")).toBool());
    }
    QCOMPARE(result.tpmUsable, expected.value(QStringLiteral("tpm_usable")).toBool());
    QStringList unmet;
    for (const QJsonValue &v : expected.value(QStringLiteral("unmet")).toArray())
        unmet << v.toString();
    QCOMPARE(result.unmet, unmet);
}

namespace {

// The cases of a shared case file; empty (and the test skips) when this
// tree is checked out without the monorepo around it.
QJsonArray sharedCases(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return {};
    return QJsonDocument::fromJson(f.readAll()).object().value(QStringLiteral("cases")).toArray();
}

// The probe output a case describes: ok false when the probe failed,
// {protocol_version: 1} for an older fisherman, else the fixture under key.
QByteArray caseProbe(const QJsonObject &c, const QString &dir, const QString &key, bool *ok)
{
    *ok = !c.value(QStringLiteral("probe_failed")).toBool();
    if (!*ok)
        return {};
    if (c.value(QStringLiteral("fixture")).isNull())
        return QByteArrayLiteral("{\"protocol_version\": 1}");
    QFile f(QDir(QStringLiteral(SHARED_PROBE_DIR "/fixtures/") + dir)
                .filePath(c.value(QStringLiteral("fixture")).toString()));
    if (!f.open(QIODevice::ReadOnly))
        qFatal("missing fixture %s", qPrintable(f.fileName()));
    return QByteArrayLiteral("{\"protocol_version\": 1, \"") + key.toUtf8() + QByteArrayLiteral("\": ")
        + f.readAll() + QByteArrayLiteral("}");
}

sourcecheck::Request caseRequest(const QJsonObject &r)
{
    sourcecheck::Request req;
    req.source = r.value(QStringLiteral("source")).toString();
    req.liveRoot = r.value(QStringLiteral("live_root")).toBool();
    req.target = r.value(QStringLiteral("target")).toString();
    for (const QJsonValue &f : r.value(QStringLiteral("features")).toArray())
        req.features << f.toString();
    return req;
}

}

void BackendTest::sourceCheckCases()
{
    const QJsonArray cases = sharedCases(QStringLiteral(SHARED_PROBE_DIR "/capabilities-cases.json"));
    if (cases.isEmpty())
        QSKIP("shared/probe is absent; this tree is checked out alone");
    for (const QJsonValue &value : cases) {
        const QJsonObject c = value.toObject();
        const QString name = c.value(QStringLiteral("name")).toString();
        bool ok = false;
        const QByteArray input = caseProbe(c, QStringLiteral("capabilities"), QStringLiteral("capabilities"), &ok);
        const sourcecheck::Request req = caseRequest(c.value(QStringLiteral("request")).toObject());
        const QJsonObject view = sourcecheck::check(ok, input, req);
        QVERIFY2(view == c.value(QStringLiteral("expected")).toObject(),
                 qPrintable(name + QStringLiteral(": ") + QString::fromUtf8(QJsonDocument(view).toJson(QJsonDocument::Compact))));
        QCOMPARE(sourcecheck::blocksInstall(view), c.value(QStringLiteral("blocks_install")).toBool());
        QStringList args;
        for (const QJsonValue &a : c.value(QStringLiteral("probe_args")).toArray())
            args << a.toString();
        QCOMPARE(sourcecheck::probeArguments(req), args);
    }
}

void BackendTest::bootcStoreCases()
{
    const QJsonArray cases = sharedCases(QStringLiteral(SHARED_PROBE_DIR "/bootc-store-cases.json"));
    if (cases.isEmpty())
        QSKIP("shared/probe is absent; this tree is checked out alone");
    for (const QJsonValue &value : cases) {
        const QJsonObject c = value.toObject();
        bool ok = false;
        const QByteArray input = caseProbe(c, QStringLiteral("bootc-store"), QStringLiteral("bootc_store"), &ok);
        const QJsonObject view = sourcecheck::bootcStore(ok, input);
        QVERIFY2(view == c.value(QStringLiteral("expected")).toObject(),
                 qPrintable(c.value(QStringLiteral("name")).toString() + QStringLiteral(": ")
                            + QString::fromUtf8(QJsonDocument(view).toJson(QJsonDocument::Compact))));
    }
}

void BackendTest::verificationCases()
{
    const QJsonArray cases = sharedCases(QStringLiteral(SHARED_COMPLETION_DIR "/verification-cases.json"));
    if (cases.isEmpty())
        QSKIP("shared/completion is absent; this tree is checked out alone");
    for (const QJsonValue &value : cases) {
        const QJsonObject c = value.toObject();
        QFile f(QDir(QStringLiteral(SHARED_COMPLETION_DIR "/fixtures")).filePath(c.value(QStringLiteral("fixture")).toString()));
        QVERIFY(f.open(QIODevice::ReadOnly));
        const QJsonObject view = sourcecheck::verification(f.readAll(), c.value(QStringLiteral("expected_install_id")).toString());
        QVERIFY2(view == c.value(QStringLiteral("expected")).toObject(),
                 qPrintable(c.value(QStringLiteral("name")).toString() + QStringLiteral(": ")
                            + QString::fromUtf8(QJsonDocument(view).toJson(QJsonDocument::Compact))));
    }
}

void BackendTest::sourceReplyOfAnOlderRequestIsDropped()
{
    QFile f(QStringLiteral(SHARED_PROBE_DIR "/fixtures/capabilities/caps-matching-ostree-current.json"));
    if (!f.open(QIODevice::ReadOnly))
        QSKIP("shared/probe is absent; this tree is checked out alone");
    QJsonObject caps = QJsonDocument::fromJson(f.readAll()).object();
    QJsonObject target = caps.value(QStringLiteral("target")).toObject();
    target[QStringLiteral("update_ref_from")] = QStringLiteral("source");
    caps[QStringLiteral("target")] = target;
    const QByteArray reply = QJsonDocument(QJsonObject{{QStringLiteral("protocol_version"), 1},
                                                      {QStringLiteral("capabilities"), caps}}).toJson();
    sourcecheck::Request req;
    req.source = caps.value(QStringLiteral("source")).toObject().value(QStringLiteral("ref")).toString();

    InstallerController c;
    // A blocked source holds Install; the rows say why.
    sourcecheck::Request blocked = req;
    blocked.features << QStringLiteral("unified_storage");
    c.applySourceReply(c.sourceGeneration(), blocked, true, reply);
    QVERIFY(c.sourceBlocked());
    // A reply of an older request does not replace the newer one.
    c.applySourceReply(c.sourceGeneration() - 1, req, true, reply);
    QVERIFY(c.sourceBlocked());
    c.applySourceReply(c.sourceGeneration(), req, true, reply);
    QVERIFY(!c.sourceBlocked());
    QStringList titles;
    for (const QVariant &row : c.sourceRows())
        titles << row.toMap().value(QStringLiteral("title")).toString();
    QVERIFY(titles.contains(c.text(QStringLiteral("source_check_ready"))));
    // A failed probe is never a green check.
    c.applySourceReply(c.sourceGeneration(), req, false, QByteArray());
    titles.clear();
    for (const QVariant &row : c.sourceRows())
        titles << row.toMap().value(QStringLiteral("title")).toString();
    QVERIFY(titles.contains(c.text(QStringLiteral("source_check_unavailable"))));
    QVERIFY(!titles.contains(c.text(QStringLiteral("source_check_ready"))));
}

void BackendTest::probeFakeEnvReachesTheController()
{
    const QString vm = QDir(QStringLiteral(PROBE_FIXTURES_DIR)).filePath(QStringLiteral("vm.json"));
    if (!QFileInfo::exists(vm))
        QSKIP("shared/probe/fixtures is absent; this tree is checked out alone");
    qputenv(probe::FAKE_ENV, vm.toLocal8Bit());
    InstallerController c;
    qunsetenv(probe::FAKE_ENV);
    QVERIFY(!c.hasTpm());
    QCOMPARE(c.unmetRequirements(), (QStringList{QStringLiteral("ram"), QStringLiteral("cpu"),
                                                 QStringLiteral("uefi")}));
    const QStringList lines = c.requirementsWarning().split(QLatin1Char('\n'));
    QCOMPARE(lines, (QStringList{c.text(QStringLiteral("requirements_title")),
                                 c.text(QStringLiteral("requirements_ram")),
                                 c.text(QStringLiteral("requirements_cpu")),
                                 c.text(QStringLiteral("requirements_uefi"))}));

    const QString laptop = QDir(QStringLiteral(PROBE_FIXTURES_DIR)).filePath(QStringLiteral("laptop.json"));
    qputenv(probe::FAKE_ENV, laptop.toLocal8Bit());
    InstallerController met;
    qunsetenv(probe::FAKE_ENV);
    QVERIFY(met.hasTpm());
    QVERIFY(met.requirementsWarning().isEmpty());
}

void BackendTest::probeFailureOffersNothingAndSaysWhy()
{
    const probe::Result old = probe::parse(QByteArrayLiteral("{\"protocol_version\": 2}"));
    QVERIFY(!old.ok);
    QVERIFY(old.error.contains(QStringLiteral("protocol_version")));
    QVERIFY(!probe::parse(QByteArrayLiteral("not json")).ok);

    qputenv(probe::FAKE_ENV, QByteArrayLiteral("/nonexistent/probe.json"));
    DiskModel model;
    model.refresh();
    InstallerController c;
    qunsetenv(probe::FAKE_ENV);
    QCOMPARE(model.rowCount(), 0);
    QVERIFY(model.error().contains(QStringLiteral("/nonexistent/probe.json")));
    QVERIFY(!c.hasTpm());
    QVERIFY(c.requirementsWarning().isEmpty());
}

void BackendTest::probeCommandIsUnprivileged()
{
    // The probe is the resolver's unprivileged command: never pkexec, sudo
    // or a shell.
    for (const bool flatpak : {false, true}) {
        const QStringList argv = fisherman::resolve(flatpak, false, QStringLiteral("/staged/fisherman")).unprivileged;
        for (const QString &word : {QStringLiteral("pkexec"), QStringLiteral("sudo"), QStringLiteral("bash")})
            QVERIFY(!argv.contains(word));
    }
}

void BackendTest::streamsKeepSeparatePartialLines()
{
    InstallerController c;
    const QString event = stepEvent(5, 8, "Installing OS", 1, 87);
    const QByteArray bytes = event.toUtf8();
    const qsizetype half = bytes.size() / 2;

    // What a pipe really delivers: half an event on stdout, then a complete
    // stderr line, then the rest of the event.
    c.consumeStdout(bytes.left(half));
    c.consumeStderr("pkexec: some warning\n");
    c.consumeStdout(bytes.mid(half) + "\n");
    c.consumeStderr("trailing stderr without a newline");
    c.flushStreams();

    // The event parsed: under the shared buffer it never did.
    QCOMPARE(c.installStep(), 5);
    QCOMPARE(c.installTotalSteps(), 8);
    QCOMPARE(c.installFraction(), 0.01);

    const QString log = c.log();
    // stderr still reaches the pane, intact and on its own line.
    QVERIFY(log.contains(QStringLiteral("[stderr] pkexec: some warning\n")));
    QVERIFY(log.contains(QStringLiteral("[stderr] trailing stderr without a newline")));
    QVERIFY(log.contains(QStringLiteral("[5/8] Installing OS")));
    // No fragment of the event leaked into the pane as raw text.
    QVERIFY(!log.contains(QStringLiteral("\"type\"")));
}

void BackendTest::flatpakWrapperPassesStdinOutputAndStatusThrough()
{
#if !QT_CONFIG(process)
    QSKIP("QProcess is not available on this platform (wasm)");
#else
    // Run the wrapper's bash for real (everything after flatpak-spawn
    // --host) with pkexec stubbed on PATH: what is written to the wrapper's
    // stdin is what fisherman reads, and `-` is its argument.
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString stub = dir.filePath(QStringLiteral("pkexec"));
    const QString seen = dir.filePath(QStringLiteral("stdin"));
    QFile f(stub);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write("#!/bin/sh\nprintf '%s|%s\\n' \"$1\" \"$2\"\ncat > \"" + seen.toUtf8()
            + "\"\necho to-stderr >&2\nexit 7\n");
    f.close();
    f.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner);

    QStringList cmd = fisherman::resolve(true, false, QStringLiteral("/usr/local/bin/fisherman")).install;
    cmd.removeFirst(); // flatpak-spawn
    cmd.removeFirst(); // --host

    QProcess p;
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert(QStringLiteral("PATH"), dir.path() + QLatin1Char(':') + env.value(QStringLiteral("PATH")));
    p.setProcessEnvironment(env);
    p.setWorkingDirectory(dir.path());
    p.start(cmd.takeFirst(), cmd);
    const QByteArray recipe = R"({"encryption":{"type":"luks-passphrase","passphrase":"s3cret"}})";
    p.write(recipe);
    p.closeWriteChannel();
    QVERIFY(p.waitForFinished(10000));
    QCOMPARE(p.exitCode(), 7);
    QCOMPARE(QString::fromUtf8(p.readAllStandardOutput()), QStringLiteral("/usr/local/bin/fisherman|-\n"));
    QCOMPARE(p.readAllStandardError(), QByteArray("to-stderr\n"));
    QFile got(seen);
    QVERIFY(got.open(QIODevice::ReadOnly));
    QCOMPARE(got.readAll(), recipe);
#endif
}

void BackendTest::validateAnswersBecomeCopyLines()
{
#ifndef VALIDATE_GOLDENS_DIR
    QSKIP("no goldens");
#else
    const QString dir = QStringLiteral(VALIDATE_GOLDENS_DIR);
    QFile golden(dir + QStringLiteral("/partial-hostname.golden"));
    if (!golden.open(QIODevice::ReadOnly))
        QSKIP("the fisherman submodule is not checked out");
    const QByteArray answer = golden.readAll();
    const validate::Result r = validate::parse(answer);
    QVERIFY(r.ok);
    QCOMPARE(r.problems.size(), 1);
    QCOMPARE(r.problems.first().code, QStringLiteral("hostname_label_hyphen"));

    InstallerController c;
    QVERIFY(c.hostnameProblem().isEmpty());
    c.applyValidateAnswer(answer);
    QCOMPARE(c.hostnameProblem(), c.text(QStringLiteral("validate_hostname_label_hyphen")));
    QVERIFY(!c.hostnameProblem().isEmpty());
    QVERIFY(c.encryptionProblem().isEmpty());

    // An unknown code shows fisherman's message; no answer clears it.
    c.applyValidateAnswer(R"({"protocol_version":1,"valid":false,"errors":[{"field":"encryption.passphrase","code":"brand_new","message":"say why"}]})");
    QCOMPARE(c.encryptionProblem(), QStringLiteral("say why"));
    c.applyValidateAnswer("not json");
    QVERIFY(c.encryptionProblem().isEmpty());
    QVERIFY(!validate::parse(R"({"protocol_version":2,"errors":[]})").ok);
#endif
}

void BackendTest::validateSendsAPartialRecipeOnStdin()
{
    QCOMPARE(validate::arguments(),
             (QStringList{QStringLiteral("validate"), QStringLiteral("--json"),
                          QStringLiteral("--partial"), QStringLiteral("-")}));
    InstallerController c;
    c.setHostname(QStringLiteral("box"));
    c.setEncryptionType(QStringLiteral("tpm2-luks"));
    QJsonObject partial = QJsonDocument::fromJson(c.partialRecipe()).object();
    QCOMPARE(partial.value(QStringLiteral("hostname")).toString(), QStringLiteral("box"));
    QVERIFY(!partial.value(QStringLiteral("encryption")).toObject().contains(QStringLiteral("passphrase")));
    c.setEncryptionType(QStringLiteral("luks-passphrase"));
    c.setPassphrase(QStringLiteral("s3cret"));
    partial = QJsonDocument::fromJson(c.partialRecipe()).object();
    QCOMPARE(partial.value(QStringLiteral("encryption")).toObject().value(QStringLiteral("passphrase")).toString(),
             QStringLiteral("s3cret"));
    // composeFsBackend travels with the filesystem (#287): without it
    // fisherman cannot say that a composefs image needs fs-verity.
    QVERIFY(partial.contains(QStringLiteral("composeFsBackend")));
    QVERIFY(!partial.value(QStringLiteral("composeFsBackend")).toBool());
}

void BackendTest::liveMediaComesFromTheProbe()
{
    const QString dir = QStringLiteral(PROBE_FIXTURES_DIR);
    for (const QString &name : {QStringLiteral("laptop"), QStringLiteral("container"), QStringLiteral("vm"), QStringLiteral("pure-live-oci")}) {
        QFile in(dir + QLatin1Char('/') + name + QStringLiteral(".json"));
        QFile want(dir + QLatin1Char('/') + name + QStringLiteral(".expected.json"));
        if (!in.open(QIODevice::ReadOnly) || !want.open(QIODevice::ReadOnly))
            QSKIP("shared/probe/fixtures is absent");
        const probe::Result r = probe::parse(in.readAll());
        const QJsonObject expected = QJsonDocument::fromJson(want.readAll()).object();
        QCOMPARE(r.liveImage, expected.value(QStringLiteral("live_image")).toString());
        QStringList images;
        for (const QJsonValue &v : expected.value(QStringLiteral("offline_images")).toArray())
            images << v.toString();
        QCOMPARE(r.offlineImages, images);
        QCOMPARE(r.isLive, name != QStringLiteral("container"));
    }
    // The controller takes it in: the laptop booted from live media.
    qputenv("BOOTC_INSTALLER_FAKE_PROBE", (dir + QStringLiteral("/laptop.json")).toUtf8());
    InstallerController live;
    qputenv("BOOTC_INSTALLER_FAKE_PROBE", (dir + QStringLiteral("/container.json")).toUtf8());
    InstallerController installed;
    qunsetenv("BOOTC_INSTALLER_FAKE_PROBE");
    QVERIFY(live.isLive());
    QCOMPARE(live.liveImage(), QStringLiteral("ghcr.io/example/os:stable"));
    QVERIFY(!installed.isLive());
}

void BackendTest::wrapperLeadsItsOwnProcessGroup()
{
#if !QT_CONFIG(process) || !defined(Q_OS_UNIX)
    QSKIP("needs QProcess and POSIX process groups");
#else
    QProcess p;
    offline::startInOwnProcessGroup(p);
    p.start(QStringLiteral("sleep"), {QStringLiteral("30")});
    QVERIFY(p.waitForStarted(5000));
    const pid_t pid = static_cast<pid_t>(p.processId());
    QCOMPARE(::getpgid(pid), pid);
    QVERIFY(::getpgid(pid) != ::getpgrp());
    // Signalling that group reaches the wrapper, not this process.
    QCOMPARE(::killpg(pid, SIGTERM), 0);
    QVERIFY(p.waitForFinished(5000));
    QCOMPARE(p.exitStatus(), QProcess::CrashExit);
#endif
}

// A two-group manifest exercising every resolution the loader mirrors from
// the GNOME tree: @alias, tag+registry composition, ancestor inheritance of
// needs_user_creation/flatpaks/bootloader, and a group carousel.
static QByteArray catalogFixture()
{
    return QByteArrayLiteral(
        R"({"aliases": {"brew": "https://example.com/brew.flatpakref"},
            "default_image": "ghcr.io/example/blue:stable",
            "fallback_flatpaks": ["org.example.Base"],
            "images": [
              {"name": "Blue", "registry": "ghcr.io/example/blue",
               "flatpaks": "@brew", "bootloader": "systemd",
               "needs_user_creation": true,
               "carousel": [{"title": "Welcome", "description": "Tour blue"}],
               "children": [
                 {"name": "Stable", "tag": "stable"},
                 {"name": "Beta", "tag": "beta", "needs_user_creation": false,
                  "desc": "Preview"}
               ]},
              {"name": "Red", "imgref": "ghcr.io/example/red:latest",
               "desc": "The red one", "needs_user_creation": false}
            ]})");
}

void BackendTest::catalogParseComposesTagsAndInherits()
{
    const imagecatalog::Catalog catalog = imagecatalog::parse(catalogFixture());
    QCOMPARE(catalog.defaultImage, QStringLiteral("ghcr.io/example/blue:stable"));
    QCOMPARE(catalog.leaves.size(), 3);

    // tag+registry composition; the row title of the flat list is the
    // breadcrumb, the confirm page's is the label.
    const imagecatalog::Leaf stable = catalog.leaves.at(0);
    QCOMPARE(stable.imgref, QStringLiteral("ghcr.io/example/blue:stable"));
    QCOMPARE(stable.name, QStringLiteral("Stable"));
    QCOMPARE(stable.breadcrumb, QStringLiteral("Blue \u203a Stable"));
    QCOMPARE(stable.label, QStringLiteral("Blue Stable"));
    // Inherited from the group: the bootloader, the user flag and the
    // group's carousel slides. The @alias names a URL, which this frontend
    // does not download: no list, so no `flatpaks` key (#296).
    QVERIFY(!stable.hasFlatpaks);
    QVERIFY(stable.flatpaks.isEmpty());
    QCOMPARE(stable.bootloader, QStringLiteral("systemd"));
    QVERIFY(stable.needsUserCreation);
    QCOMPARE(stable.carousel.size(), 1);
    QCOMPARE(stable.carousel.first().toMap().value(QStringLiteral("title")).toString(),
             QStringLiteral("Welcome"));

    // A leaf-level override wins over the inherited flag.
    const imagecatalog::Leaf beta = catalog.leaves.at(1);
    QCOMPARE(beta.imgref, QStringLiteral("ghcr.io/example/blue:beta"));
    QVERIFY(!beta.needsUserCreation);
    QCOMPARE(beta.desc, QStringLiteral("Preview"));
    QVERIFY(beta.searchText.contains(QStringLiteral("blue")));
    QVERIFY(beta.searchText.contains(QStringLiteral("beta")));

    // A full imgref needs no registry. (The bare-leaf default of true is
    // pinned by catalogParseRejectsGarbage below.)
    const imagecatalog::Leaf red = catalog.leaves.at(2);
    QCOMPARE(red.imgref, QStringLiteral("ghcr.io/example/red:latest"));
    QVERIFY(!red.needsUserCreation); // explicit false in the fixture
}

void BackendTest::catalogParseRejectsGarbage()
{
    QVERIFY(imagecatalog::parse(QByteArrayLiteral("not json")).leaves.isEmpty());
    QVERIFY(imagecatalog::parse(QByteArrayLiteral("[]")).leaves.isEmpty());
    QVERIFY(imagecatalog::parse(QByteArrayLiteral("{}")).leaves.isEmpty());
    // A tag without any registry in scope is not selectable, and a
    // needs_user_creation default of true applies to a bare imgref leaf.
    const imagecatalog::Catalog catalog = imagecatalog::parse(
        QByteArrayLiteral(R"({"images": [{"name": "Lonely", "tag": "x"},
                                         {"name": "Bare", "imgref": "example/bare:1"}]})"));
    QCOMPARE(catalog.leaves.size(), 1);
    QCOMPARE(catalog.leaves.first().imgref, QStringLiteral("example/bare:1"));
    QVERIFY(catalog.leaves.first().needsUserCreation);
}

void BackendTest::catalogLoadPrefersTheEnvOverride()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QFile manifest(dir.filePath(QStringLiteral("images.json")));
    QVERIFY(manifest.open(QIODevice::WriteOnly));
    manifest.write(catalogFixture());
    manifest.close();

    qputenv(imagecatalog::IMAGES_ENV, dir.filePath(QStringLiteral("images.json")).toUtf8());
    const imagecatalog::Catalog catalog = imagecatalog::load();
    qunsetenv(imagecatalog::IMAGES_ENV);
    QCOMPARE(catalog.leaves.size(), 3);
    // The search path itself is the shared contract's: catalogContractSearchPaths.
    QCOMPARE(imagecatalog::defaultSearchPaths(false).first(),
             QStringLiteral("/etc/bootc-installer/images.json"));
    QCOMPARE(imagecatalog::defaultSearchPaths(true).first(),
             QStringLiteral("/run/host/etc/bootc-installer/images.json"));
}

void BackendTest::catalogSelectionDrivesTheRecipeAndTheUserStep()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QFile manifest(dir.filePath(QStringLiteral("images.json")));
    QVERIFY(manifest.open(QIODevice::WriteOnly));
    manifest.write(catalogFixture());
    manifest.close();
    qputenv(imagecatalog::IMAGES_ENV, dir.filePath(QStringLiteral("images.json")).toUtf8());
    InstallerController c;
    qunsetenv(imagecatalog::IMAGES_ENV);

    QVERIFY(c.hasCatalog());
    QCOMPARE(c.catalogNames().size(), 3);
    // The constructor preselects the manifest's default_image.
    QCOMPARE(c.catalogIndex(), 0);
    QCOMPARE(c.image(), QStringLiteral("ghcr.io/example/blue:stable"));
    QVERIFY(c.needsUserCreation());

    QSignalSpy picked(&c, &InstallerController::catalogChanged);
    c.setUsername(QStringLiteral("alex"));
    c.setUserPassword(QStringLiteral("pw"));
    // The beta leaf creates its own first user: the account step is skipped
    // and the recipe omits the block even with a typed username.
    c.selectCatalogImage(1);
    QCOMPARE(c.image(), QStringLiteral("ghcr.io/example/blue:beta"));
    QVERIFY(!c.needsUserCreation());
    QVERIFY(!c.recipe().toJson().contains(QStringLiteral("user")));
    // The group inheritance travelled into the recipe: systemd bootloader,
    // no composefs, and no `flatpaks` key (the leaf's source is a URL, so
    // fisherman applies its own default).
    QCOMPARE(c.recipe().bootloader, QStringLiteral("systemd"));
    QVERIFY(!c.recipe().composeFsBackend);
    QVERIFY(!c.recipe().toJson().contains(QStringLiteral("flatpaks")));
    QCOMPARE(c.recipe().targetImgref, QStringLiteral("ghcr.io/example/blue:beta"));
    QVERIFY(!c.tourSlides().isEmpty());
    // Out-of-range and repeated selections are ignored, not errors.
    c.selectCatalogImage(99);
    c.selectCatalogImage(1);
    QCOMPARE(c.catalogIndex(), 1);
    QCOMPARE(picked.count(), 1);
}

void BackendTest::catalogAbsentMeansAccountRequired()
{
    qunsetenv(imagecatalog::IMAGES_ENV);
    // /etc and fisherman's data dirs have no manifest on a test runner.
    InstallerController c;
    if (c.hasCatalog())
        QSKIP("a real images.json is installed; nothing to prove about its absence");
    QVERIFY(c.needsUserCreation());
    QCOMPARE(c.catalogIndex(), -1);
    QVERIFY(c.catalogNames().isEmpty());
    QVERIFY(c.tourSlides().isEmpty());
    // Live media keeps the empty image, and the user step then follows the
    // live manifest's first leaf (see the constructor); here there is none.
    QVERIFY(c.needsNetwork());
}

void BackendTest::recipeUserOmittedWhenNotRequired()
{
    Recipe withUser;
    withUser.user.username = QStringLiteral("alex");
    QVERIFY(withUser.toJson().contains(QStringLiteral("user")));

    Recipe skipped;
    skipped.user.username = QStringLiteral("alex");
    skipped.userRequired = false;
    QVERIFY(!skipped.toJson().contains(QStringLiteral("user")));

    // fromJson still reads a user block when one is present.
    QCOMPARE(Recipe::fromJson(withUser.toJson()).user.username, QStringLiteral("alex"));
}

void BackendTest::requirementsGates()
{
    const QString dir = QStringLiteral(PROBE_FIXTURES_DIR);
    if (!QFileInfo::exists(dir + QStringLiteral("/vm.json")))
        QSKIP("shared/probe/fixtures is absent");
    qputenv(probe::FAKE_ENV, (dir + QStringLiteral("/vm.json")).toUtf8());
    InstallerController blocked;
    qputenv(probe::FAKE_ENV, (dir + QStringLiteral("/laptop.json")).toUtf8());
    InstallerController clear;
    qunsetenv(probe::FAKE_ENV);

    // vm.json is unmet on ram, cpu AND uefi: fatal, no continue path.
    QVERIFY(blocked.requirementsBlocking());
    QVERIFY(blocked.requirementsFatal());
    QVERIFY(!blocked.continueAnyway());
    QSignalSpy changed(&blocked, &InstallerController::continueAnywayChanged);
    blocked.setContinueAnyway(true);
    QVERIFY(blocked.continueAnyway());
    QCOMPARE(changed.count(), 1);
    blocked.setContinueAnyway(true);
    QCOMPARE(changed.count(), 1);

    // laptop.json meets everything: no gate at all.
    QVERIFY(!clear.requirementsBlocking());
    QVERIFY(!clear.requirementsFatal());
}

void BackendTest::cancelInstallWithoutAProcessIsANoOp()
{
    InstallerController c;
    // Nothing is running: leaving must be safe and silent, not an error.
    QVERIFY(!c.installing());
    c.cancelInstall();
    QVERIFY(!c.installing());
}

void BackendTest::copyLogWithoutAClipboardIsANoOp()
{
    // QTEST_APPLESS_MAIN runs without a GUI application: there is no
    // clipboard, and the call must warn and return instead of crashing.
    InstallerController c;
    c.copyLogToClipboard();
}

void BackendTest::regionListsComeFromThePlatform()
{
    const QList<region::Language> languages = region::availableLanguages();
    QVERIFY(!languages.isEmpty());
    bool hasEnglish = false;
    for (const region::Language &l : languages) {
        QVERIFY(!l.id.isEmpty() && !l.display.isEmpty());
        if (l.id == QStringLiteral("en"))
            hasEnglish = true;
    }
    QVERIFY(hasEnglish);

    const QList<region::Keymap> layouts = region::availableKeyboardLayouts();
    QVERIFY(!layouts.isEmpty());
    bool hasUs = false;
    for (const region::Keymap &k : layouts) {
        if (k.id == QStringLiteral("us"))
            hasUs = true;
    }
    QVERIFY(hasUs);

    QVERIFY(region::availableTimezones().contains(QStringLiteral("UTC")));
    QVERIFY(!region::systemTimezone().isEmpty());
    QCOMPARE(region::systemKeyboardLayout(), QStringLiteral("us"));
}

void BackendTest::regionTimezoneDisplay()
{
    QCOMPARE(region::timezoneDisplay(QStringLiteral("America/New_York")),
             QStringLiteral("New York (America)"));
    QCOMPARE(region::timezoneDisplay(QStringLiteral("UTC")), QStringLiteral("UTC"));
}

void BackendTest::regionRejectsUnreachableHosts()
{
    // .invalid never resolves (RFC 2606), so no packet decides the outcome:
    // asserting on an unroutable IP instead would depend on the runner's
    // firewall, and a sandbox proxy already answers those here. No success
    // case is asserted — the CI runner's network is not this test's business.
    QVERIFY(!region::hostReachable("nonexistent.invalid", 53, 1500));
}

void BackendTest::tourSlidesFollowTheSelection()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QFile manifest(dir.filePath(QStringLiteral("images.json")));
    QVERIFY(manifest.open(QIODevice::WriteOnly));
    manifest.write(catalogFixture());
    manifest.close();
    qputenv(imagecatalog::IMAGES_ENV, dir.filePath(QStringLiteral("images.json")).toUtf8());
    InstallerController c;
    qunsetenv(imagecatalog::IMAGES_ENV);
    if (!c.hasCatalog())
        QSKIP("catalog override did not apply");

    // The default leaf carries the group's carousel.
    QCOMPARE(c.tourSlides().size(), 1);
    QCOMPARE(c.tourSlides().first().toMap().value(QStringLiteral("title")).toString(),
             QStringLiteral("Welcome"));
    // The red leaf names none: the done screen hides the carousel.
    c.selectCatalogImage(2);
    QVERIFY(c.tourSlides().isEmpty());
}

// ---- the shared catalog contract (shared/catalog/README.md) ----------------

static QByteArray readFixture(const QString &path)
{
    QFile f(path);
    return f.open(QIODevice::ReadOnly) ? f.readAll() : QByteArray();
}

static QByteArray sharedCatalog()
{
    return readFixture(QStringLiteral(CATALOG_FIXTURES_DIR "/catalog.json"));
}

static QJsonObject sharedExpected()
{
    return QJsonDocument::fromJson(readFixture(QStringLiteral(CATALOG_FIXTURES_DIR "/expected.json"))).object();
}

static QStringList strings(const QJsonValue &v)
{
    QStringList out;
    for (const QJsonValue &item : v.toArray())
        out << item.toString();
    return out;
}

// A probe answer for a machine: not the fixtures, so the test owns live
// media and the offline stores.
static QByteArray probeAnswer(bool live, const QString &liveImage, const QStringList &offlineImages)
{
    return QJsonDocument(QJsonObject{
        {QStringLiteral("protocol_version"), 1},
        {QStringLiteral("disks"), QJsonArray{}},
        {QStringLiteral("tpm"), QJsonObject{{QStringLiteral("usable"), false}}},
        {QStringLiteral("system"), QJsonObject{{QStringLiteral("unmet"), QJsonArray{}}}},
        {QStringLiteral("live"), QJsonObject{{QStringLiteral("is_live"), live},
                                              {QStringLiteral("live_image"), liveImage}}},
        {QStringLiteral("offline"), QJsonObject{{QStringLiteral("images"), QJsonArray::fromStringList(offlineImages)}}},
    }).toJson();
}

static bool writeFile(const QString &path, const QByteArray &data)
{
    QDir().mkpath(QFileInfo(path).path());
    QFile f(path);
    return f.open(QIODevice::WriteOnly) && f.write(data) == data.size();
}

// A machine for one controller: the catalog, the probe answer and a /sys
// with or without an NVIDIA display device. The variables are unset again
// when this goes out of scope.
struct Machine {
    QTemporaryDir dir;
    Machine(const QByteArray &catalog, bool live, const QString &liveImage,
            const QStringList &offlineImages, bool nvidia, const QByteArray &branding = QByteArray())
    {
        writeFile(dir.filePath(QStringLiteral("images.json")), catalog);
        writeFile(dir.filePath(QStringLiteral("probe.json")), probeAnswer(live, liveImage, offlineImages));
        // An Intel display device always; the NVIDIA one on request.
        writeFile(dir.filePath(QStringLiteral("sys/bus/pci/devices/0000:00:02.0/vendor")), "0x8086\n");
        writeFile(dir.filePath(QStringLiteral("sys/bus/pci/devices/0000:00:02.0/class")), "0x030000\n");
        if (nvidia) {
            writeFile(dir.filePath(QStringLiteral("sys/bus/pci/devices/0000:01:00.0/vendor")), "0x10de\n");
            writeFile(dir.filePath(QStringLiteral("sys/bus/pci/devices/0000:01:00.0/class")), "0x030200\n");
        }
        qputenv(imagecatalog::IMAGES_ENV, dir.filePath(QStringLiteral("images.json")).toUtf8());
        qputenv("BOOTC_INSTALLER_FAKE_PROBE", dir.filePath(QStringLiteral("probe.json")).toUtf8());
        qputenv("BOOTC_INSTALLER_SYS_ROOT", dir.filePath(QStringLiteral("sys")).toUtf8());
        if (!branding.isNull()) {
            writeFile(dir.filePath(QStringLiteral("branding.json")), branding);
            qputenv("BOOTC_INSTALLER_BRANDING", dir.filePath(QStringLiteral("branding.json")).toUtf8());
        }
    }
    ~Machine()
    {
        qunsetenv(imagecatalog::IMAGES_ENV);
        qunsetenv("BOOTC_INSTALLER_FAKE_PROBE");
        qunsetenv("BOOTC_INSTALLER_SYS_ROOT");
        qunsetenv("BOOTC_INSTALLER_BRANDING");
    }
};

void BackendTest::catalogContractSearchPaths()
{
    const QJsonArray rows = sharedExpected().value(QStringLiteral("search_paths")).toArray();
    if (rows.isEmpty())
        QSKIP("shared/catalog/fixtures is absent");
    for (const QJsonValue &v : rows) {
        const QJsonObject row = v.toObject();
        const bool flatpak = row.value(QStringLiteral("in_flatpak")).toBool();
        QStringList want = strings(row.value(QStringLiteral("paths")));
        // "<bundled>" is this frontend's own file: fisherman's catalog, as
        // the Flatpak manifest and a native package install it.
        QCOMPARE(want.last(), QStringLiteral("<bundled>"));
        want.last() = flatpak ? QStringLiteral("/app/share/fisherman/data/images.json")
                              : QStringLiteral("/usr/share/fisherman/data/images.json");
        const QString xdg = row.value(QStringLiteral("xdg_config_home")).toString();
        QCOMPARE(imagecatalog::searchPaths(flatpak, xdg), want);
        QCOMPARE(imagecatalog::searchPaths(flatpak, xdg + QLatin1Char('/')), want);
    }
}

void BackendTest::catalogContractOverride()
{
    // FISHERMAN_IMAGES_PATH, for each case of expected.json: its file first
    // when it names one, then the search path as without it.
    const QJsonObject override = sharedExpected().value(QStringLiteral("override")).toObject();
    const QJsonArray cases = override.value(QStringLiteral("cases")).toArray();
    if (cases.isEmpty())
        QSKIP("shared/catalog/fixtures is absent");
    QCOMPARE(override.value(QStringLiteral("env")).toString(), QString::fromLatin1(imagecatalog::IMAGES_ENV));
    for (const QJsonValue &v : cases) {
        const QJsonObject row = v.toObject();
        const bool flatpak = row.value(QStringLiteral("in_flatpak")).toBool();
        QStringList want = strings(row.value(QStringLiteral("paths")));
        QCOMPARE(want.last(), QStringLiteral("<bundled>"));
        want.last() = flatpak ? QStringLiteral("/app/share/fisherman/data/images.json")
                              : QStringLiteral("/usr/share/fisherman/data/images.json");
        QCOMPARE(imagecatalog::searchPaths(flatpak, row.value(QStringLiteral("xdg_config_home")).toString(),
                                           row.value(QStringLiteral("value")).toString()),
                 want);
    }
    // load(): a missing override file does not stop the search, and a good
    // one is the catalog.
    QTemporaryDir dir;
    qputenv(imagecatalog::IMAGES_ENV, dir.filePath(QStringLiteral("absent.json")).toUtf8());
    QCOMPARE(imagecatalog::defaultSearchPaths(false).first(), dir.filePath(QStringLiteral("absent.json")));
    QCOMPARE(imagecatalog::defaultSearchPaths(false).size(), 5);
    qputenv(imagecatalog::IMAGES_ENV, QByteArray(CATALOG_FIXTURES_DIR "/catalog.json"));
    QVERIFY(!imagecatalog::load().leaves.isEmpty());
    qunsetenv(imagecatalog::IMAGES_ENV);
    QCOMPARE(imagecatalog::defaultSearchPaths(false).size(), 4);
}

void BackendTest::catalogContractDefaultSelection()
{
    const QJsonObject expected = sharedExpected();
    const QJsonArray rows = expected.value(QStringLiteral("default_selection")).toArray();
    if (rows.isEmpty())
        QSKIP("shared/catalog/fixtures is absent");
    const imagecatalog::Catalog with = imagecatalog::parse(sharedCatalog());
    QJsonObject stripped = QJsonDocument::fromJson(sharedCatalog()).object();
    stripped.remove(QStringLiteral("default_image"));
    const imagecatalog::Catalog without = imagecatalog::parse(QJsonDocument(stripped).toJson());
    for (const QJsonValue &v : rows) {
        const QJsonObject row = v.toObject();
        // A row with an empty catalog default applies to the fixture with
        // that key removed.
        const imagecatalog::Catalog &catalog =
            row.value(QStringLiteral("catalog_default_image")).toString().isEmpty() ? without : with;
        const int index = catalog.defaultIndex(row.value(QStringLiteral("branding_default_image")).toString());
        const QJsonValue selected = row.value(QStringLiteral("selected"));
        if (selected.isNull())
            QCOMPARE(index, -1); // nothing: never the first row
        else
            QCOMPARE(catalog.leaves.value(index).imgref, selected.toString());
    }
    // An image the catalog does not have needs an account.
    const QJsonObject unknown = expected.value(QStringLiteral("unknown_image")).toObject();
    QCOMPARE(with.needsUserCreation(unknown.value(QStringLiteral("imgref")).toString()),
             unknown.value(QStringLiteral("needs_user_creation")).toBool());
    QVERIFY(with.needsUserCreation(QString()));
    QVERIFY(imagecatalog::Catalog{}.needsUserCreation(QStringLiteral("registry.example/os/atlas:beta")));
}

void BackendTest::catalogContractLeaves()
{
    const QJsonArray rows = sharedExpected().value(QStringLiteral("leaves")).toArray();
    if (rows.isEmpty())
        QSKIP("shared/catalog/fixtures is absent");
    const imagecatalog::Catalog catalog = imagecatalog::parse(sharedCatalog());
    QVERIFY(catalog.valid);
    QCOMPARE(catalog.leaves.size(), rows.size());
    for (int i = 0; i < rows.size(); ++i) {
        const QJsonObject want = rows.at(i).toObject().value(QStringLiteral("leaf")).toObject();
        const imagecatalog::Leaf &leaf = catalog.leaves.at(i);
        const QByteArray where = want.value(QStringLiteral("imgref")).toString().toUtf8();
        QVERIFY2(leaf.imgref == want.value(QStringLiteral("imgref")).toString(), where);
        QVERIFY2(leaf.name == want.value(QStringLiteral("name")).toString(), where);
        QVERIFY2(leaf.product == want.value(QStringLiteral("product")).toString(), where);
        QVERIFY2(leaf.channel == want.value(QStringLiteral("channel")).toString(), where);
        QVERIFY2(leaf.label == want.value(QStringLiteral("label")).toString(), where);
        QVERIFY2(leaf.breadcrumb == want.value(QStringLiteral("breadcrumb")).toString(), where);
        QVERIFY2(leaf.nvidiaImgref == want.value(QStringLiteral("nvidia_imgref")).toString(), where);
        QVERIFY2(leaf.bootloader == want.value(QStringLiteral("bootloader")).toString(), where);
        QVERIFY2(leaf.composefs == want.value(QStringLiteral("composefs")).toBool(), where);
        QVERIFY2(leaf.filesystem == want.value(QStringLiteral("filesystem")).toString(), where);
        QVERIFY2(leaf.filesystems == strings(want.value(QStringLiteral("filesystems"))), where);
        QVERIFY2(leaf.defaultHostname == want.value(QStringLiteral("default_hostname")).toString(), where);
        QVERIFY2(leaf.flatpakVarPath == want.value(QStringLiteral("flatpak_var_path")).toString(), where);
        QVERIFY2(leaf.needsUserCreation == want.value(QStringLiteral("needs_user_creation")).toBool(), where);
        QVERIFY2(leaf.imageType == want.value(QStringLiteral("image_type")).toString(), where);
        // null: no list this frontend can read offline. [] is a list.
        const QJsonValue flatpaks = want.value(QStringLiteral("flatpaks"));
        QVERIFY2(leaf.hasFlatpaks == flatpaks.isArray(), where);
        QVERIFY2(leaf.flatpaks == strings(flatpaks), where);
        // null: no node has the object. An object has the four switches.
        const QJsonValue extras = want.value(QStringLiteral("extras"));
        QVERIFY2(leaf.hasExtras == extras.isObject(), where);
        QVERIFY2(leaf.extras == extras.toObject(), where);
    }
}

// What recipe_matches() of the reference resolver checks: each key of
// `recipe` is in the recipe with that value, each key of `absent` is not
// there. A missing bootloader, composeFsBackend or imageType equals "",
// false or "bootc".
static QString recipeProblems(const QJsonObject &recipe, const QJsonObject &fragment)
{
    static const QJsonObject empty{{QStringLiteral("bootloader"), QString()},
                                   {QStringLiteral("composeFsBackend"), false},
                                   {QStringLiteral("imageType"), QStringLiteral("bootc")}};
    QStringList problems;
    const QJsonObject want = fragment.value(QStringLiteral("recipe")).toObject();
    for (auto it = want.begin(); it != want.end(); ++it) {
        QJsonValue got = recipe.value(it.key());
        if (got.isUndefined() && empty.contains(it.key()))
            got = empty.value(it.key());
        if (it.key() == QLatin1String("extras") && got.isObject()) {
            // A switch that the recipe leaves out is off; fisherman refuses
            // any other key.
            QJsonObject full;
            const QJsonObject have = got.toObject();
            for (const QString &name : it.value().toObject().keys())
                full.insert(name, have.value(name).toBool(false));
            for (const QString &name : have.keys()) {
                if (!full.contains(name))
                    problems << QStringLiteral("extras: unknown key %1").arg(name);
            }
            got = full;
        }
        if (got != it.value())
            problems << QStringLiteral("%1: expected %2, found %3").arg(
                it.key(), QString::fromUtf8(QJsonDocument(QJsonArray{it.value()}).toJson(QJsonDocument::Compact)),
                QString::fromUtf8(QJsonDocument(QJsonArray{got}).toJson(QJsonDocument::Compact)));
    }
    for (const QJsonValue &key : fragment.value(QStringLiteral("absent")).toArray()) {
        if (recipe.contains(key.toString()))
            problems << QStringLiteral("%1: must be left out").arg(key.toString());
    }
    return problems.join(QStringLiteral("; "));
}

void BackendTest::catalogContractRecipes()
{
    const QJsonArray rows = sharedExpected().value(QStringLiteral("leaves")).toArray();
    if (rows.isEmpty())
        QSKIP("shared/catalog/fixtures is absent");
    const imagecatalog::Catalog catalog = imagecatalog::parse(sharedCatalog());
    int controllerCases = 0;
    int liveCases = 0;
    for (int i = 0; i < rows.size(); ++i) {
        const QJsonObject row = rows.at(i).toObject();
        for (const QJsonValue &c : row.value(QStringLiteral("cases")).toArray()) {
            const QJsonObject fragment = c.toObject();
            const QJsonObject in = fragment.value(QStringLiteral("inputs")).toObject();
            const bool nvidia = in.value(QStringLiteral("has_nvidia")).toBool();
            const bool live = in.value(QStringLiteral("is_live")).toBool();
            const QStringList offlineImages = strings(in.value(QStringLiteral("offline_images")));
            const QByteArray where = (row.value(QStringLiteral("imgref")).toString() + QLatin1Char(' ')
                                      + QString::fromUtf8(QJsonDocument(in).toJson(QJsonDocument::Compact))).toUtf8();

            // The NVIDIA table, for every machine of the fixture.
            const imagecatalog::ImageChoice choice =
                imagecatalog::sourceAndTarget(catalog.leaves.at(i), nvidia, live, offlineImages);
            const QJsonObject want = fragment.value(QStringLiteral("recipe")).toObject();
            QVERIFY2(choice.image == want.value(QStringLiteral("image")).toString(), where);
            QVERIFY2(choice.targetImgref == want.value(QStringLiteral("targetImgref")).toString(), where);

            // The whole recipe, through the controller the wizard uses: the
            // user selects the leaf and changes nothing. On live media this
            // frontend shows no catalog (fisherman installs the running
            // system), so the live rows end at the table above.
            if (live) {
                ++liveCases;
                continue;
            }
            Machine machine(sharedCatalog(), false, QString(), offlineImages, nvidia);
            InstallerController controller;
            controller.selectCatalogImage(i);
            QCOMPARE(controller.catalogIndex(), i);
            const QString problems = recipeProblems(controller.recipe().toJson(), fragment);
            QVERIFY2(problems.isEmpty(), where + ": " + problems.toUtf8());
            // The account follows the leaf's flag.
            QVERIFY2(controller.needsUserCreation()
                         == row.value(QStringLiteral("leaf")).toObject().value(QStringLiteral("needs_user_creation")).toBool(),
                     where);
            ++controllerCases;
        }
    }
    QVERIFY(controllerCases >= rows.size());
    QVERIFY2(liveCases > 0, "the fixture has no live-media row for the NVIDIA table");
}

void BackendTest::catalogBrandingDefaultWinsInTheController()
{
    if (sharedCatalog().isEmpty())
        QSKIP("shared/catalog/fixtures is absent");
    // The catalog's default_image alone.
    {
        Machine machine(sharedCatalog(), false, QString(), {}, false, QByteArray("{}"));
        InstallerController c;
        QCOMPARE(c.image(), QStringLiteral("registry.example/os/atlas:stable"));
        QCOMPARE(c.imageLabel(), QStringLiteral("Atlas Stable"));
        // The list is flat: each row's title is the breadcrumb.
        QCOMPARE(c.catalogNames().value(2), QStringLiteral("Atlas › Atlas DX › Latest"));
    }
    // The branding's default_image wins over it.
    {
        Machine machine(sharedCatalog(), false, QString(), {}, false,
                        QByteArray(R"({"default_image": "registry.example/os/atlas:beta"})"));
        InstallerController c;
        QCOMPARE(c.image(), QStringLiteral("registry.example/os/atlas:beta"));
        QVERIFY(!c.needsUserCreation());
    }
    // Neither names a leaf: nothing is selected, never the first row.
    {
        QJsonObject stripped = QJsonDocument::fromJson(sharedCatalog()).object();
        stripped.remove(QStringLiteral("default_image"));
        Machine machine(QJsonDocument(stripped).toJson(), false, QString(), {}, false,
                        QByteArray(R"({"default_image": "registry.example/os/not-in-the-catalog:1"})"));
        InstallerController c;
        QVERIFY(c.hasCatalog());
        QCOMPARE(c.catalogIndex(), -1);
        QVERIFY(c.imageLabel().isEmpty());
    }
}

void BackendTest::catalogLoadSkipsAFileThatIsNoCatalog()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QVERIFY(writeFile(dir.filePath(QStringLiteral("broken.json")), "{ not json"));
    QVERIFY(writeFile(dir.filePath(QStringLiteral("no-images.json")), R"({"default_image": "x"})"));
    QVERIFY(writeFile(dir.filePath(QStringLiteral("first.json")),
                      R"({"images": [{"name": "First", "imgref": "example/first:1"}]})"));
    QVERIFY(writeFile(dir.filePath(QStringLiteral("second.json")),
                      R"({"images": [{"name": "Second", "imgref": "example/second:1"}]})"));
    // A file that is missing or is no catalog does not stop the search; the
    // first catalog is used, an empty `images` list included.
    const imagecatalog::Catalog catalog = imagecatalog::loadFirst({
        dir.filePath(QStringLiteral("absent.json")), dir.filePath(QStringLiteral("broken.json")),
        dir.filePath(QStringLiteral("no-images.json")), dir.filePath(QStringLiteral("first.json")),
        dir.filePath(QStringLiteral("second.json"))});
    QCOMPARE(catalog.leaves.size(), 1);
    QCOMPARE(catalog.leaves.first().imgref, QStringLiteral("example/first:1"));
    QVERIFY(!imagecatalog::loadFirst({dir.filePath(QStringLiteral("absent.json"))}).valid);
    QVERIFY(imagecatalog::parse(R"({"images": []})").valid);
}

void BackendTest::catalogLiveMediaReadsTheLeafOfTheLiveImage()
{
    if (sharedCatalog().isEmpty())
        QSKIP("shared/catalog/fixtures is absent");
    // The live image is a leaf that needs no account. It is not the first
    // leaf of the catalog, whose flag the old code read (#288).
    {
        Machine machine(sharedCatalog(), true, QStringLiteral("registry.example/os/boreal:latest"), {}, false);
        InstallerController c;
        QVERIFY(c.isLive());
        QVERIFY(!c.needsUserCreation());
        const QJsonObject recipe = c.recipe().toJson();
        // The image stays out: fisherman installs the running system. What
        // fisherman cannot read from the image comes from the leaf (#287).
        QVERIFY(!recipe.contains(QStringLiteral("image")));
        QVERIFY(recipe.value(QStringLiteral("composeFsBackend")).toBool());
        QCOMPARE(recipe.value(QStringLiteral("filesystem")).toString(), QStringLiteral("btrfs"));
        QCOMPARE(recipe.value(QStringLiteral("bootloader")).toString(), QStringLiteral("systemd"));
        QCOMPARE(c.filesystemChoices(), (QStringList{QStringLiteral("btrfs"), QStringLiteral("ext4")}));
        c.setUsername(QStringLiteral("alex"));
        QVERIFY(!c.recipe().toJson().contains(QStringLiteral("user")));
    }
    // The first leaf needs an account, the live image's does not.
    {
        Machine machine(sharedCatalog(), true, QStringLiteral("registry.example/os/atlas:beta"), {}, false);
        QVERIFY(!InstallerController().needsUserCreation());
    }
    // An image the catalog does not have needs an account, whatever the
    // other leaves say.
    {
        Machine machine(sharedCatalog(), true, QStringLiteral("registry.example/os/not-in-the-catalog:1"), {}, false);
        InstallerController c;
        QVERIFY(c.needsUserCreation());
        QCOMPARE(c.filesystemChoices(), InstallerController::ownFilesystems());
    }
}

void BackendTest::liveLeafTakesTheOperatorLayout()
{
    // tunaOS grouper: no catalog leaf, and the ISO builder's probe of the
    // running image in the operator recipe (tunaOS#4485).
    const QByteArray grouper(
        R"({"bootloader": "systemd", "composeFsBackend": true, "filesystem": "ext4", "user": {"groups": []}})");
    const imagecatalog::Leaf none = imagecatalog::liveLeaf(nullptr, grouper);
    QCOMPARE(none.bootloader, QStringLiteral("systemd"));
    QVERIFY(none.composefs);
    QCOMPARE(none.filesystem, QStringLiteral("ext4"));
    QCOMPARE(none.filesystems, QStringList{QStringLiteral("ext4")});

    // A leaf's values give way to the operator's, an explicit false included;
    // what the operator recipe does not set stays the leaf's.
    imagecatalog::Leaf leaf;
    leaf.bootloader = QStringLiteral("systemd");
    leaf.composefs = true;
    leaf.filesystem = QStringLiteral("btrfs");
    leaf.filesystems = {QStringLiteral("btrfs"), QStringLiteral("xfs")};
    leaf.defaultHostname = QStringLiteral("skipjack");
    const imagecatalog::Leaf el10 = imagecatalog::liveLeaf(
        &leaf, R"({"bootloader": "grub2", "composeFsBackend": false, "filesystem": "xfs"})");
    QCOMPARE(el10.bootloader, QStringLiteral("grub2"));
    QVERIFY(!el10.composefs);
    QCOMPARE(el10.filesystems, QStringList{QStringLiteral("xfs")});
    QCOMPARE(el10.defaultHostname, QStringLiteral("skipjack"));

    // Missing, empty or mistyped keys, no file, or a file that does not
    // parse: the leaf as it is (fisherman's defaults without one).
    for (const QByteArray &json : {QByteArray(), QByteArray(""), QByteArray("{ not json"),
                                   QByteArray(R"({"bootloader": "", "composeFsBackend": "true", "filesystem": 4})")}) {
        const imagecatalog::Leaf kept = imagecatalog::liveLeaf(&leaf, json);
        QCOMPARE(kept.bootloader, leaf.bootloader);
        QCOMPARE(kept.composefs, leaf.composefs);
        QCOMPARE(kept.filesystem, leaf.filesystem);
        QCOMPARE(kept.filesystems, leaf.filesystems);
        const imagecatalog::Leaf bare = imagecatalog::liveLeaf(nullptr, json);
        QVERIFY(bare.bootloader.isEmpty() && !bare.composefs && bare.filesystems.isEmpty());
    }
}

void BackendTest::catalogSelectionReplacesThePreviousLeaf()
{
    if (sharedCatalog().isEmpty())
        QSKIP("shared/catalog/fixtures is absent");
    Machine machine(sharedCatalog(), false, QString(), {}, false, QByteArray("{}"));
    InstallerController c;
    const QStringList refs = c.catalogImgrefs();
    const auto select = [&](const char *ref) { c.selectCatalogImage(refs.indexOf(QLatin1String(ref))); };

    // #287: a composefs leaf brings its filesystem; xfs does not stay.
    select("registry.example/os/boreal:latest");
    QVERIFY(c.recipe().composeFsBackend);
    QCOMPARE(c.filesystem(), QStringLiteral("btrfs"));
    QCOMPARE(c.filesystemChoices(), (QStringList{QStringLiteral("btrfs"), QStringLiteral("ext4")}));
    QCOMPARE(c.hostname(), QStringLiteral("boreal"));
    QCOMPARE(c.recipe().flatpakVarPath, QStringLiteral("state/os/default/var"));
    // The user picks the other choice; the partial recipe carries both
    // fields to fisherman.
    c.setFilesystem(QStringLiteral("ext4"));
    QJsonObject partial = QJsonDocument::fromJson(c.partialRecipe()).object();
    QVERIFY(partial.value(QStringLiteral("composeFsBackend")).toBool());
    QCOMPARE(partial.value(QStringLiteral("filesystem")).toString(), QStringLiteral("ext4"));

    // A leaf that sets nothing: no bootloader, composefs, var path or
    // filesystem of the leaf before it stays, and the hostname goes back
    // to the branding's.
    const QString brandingHostname = InstallerController().hostname();
    select("registry.example/os/cirrus:1");
    const QJsonObject recipe = c.recipe().toJson();
    QVERIFY(!recipe.contains(QStringLiteral("bootloader")));
    QVERIFY(!recipe.contains(QStringLiteral("composeFsBackend")));
    QVERIFY(!recipe.contains(QStringLiteral("flatpakVarPath")));
    QVERIFY(!recipe.contains(QStringLiteral("flatpaks")));
    QCOMPARE(c.filesystem(), InstallerController::ownFilesystems().first());
    QCOMPARE(c.filesystemChoices(), InstallerController::ownFilesystems());
    QVERIFY(c.filesystemChoices().size() > 1);
    QVERIFY(c.needsUserCreation());
    QVERIFY(c.hostname() != QStringLiteral("boreal"));

    // One choice only: the disk step shows no picker.
    select("registry.example/os/atlas:stable");
    QCOMPARE(c.filesystemChoices(), QStringList{QStringLiteral("xfs")});
    // [] is a list: "copy no Flatpak" reaches the recipe as [].
    select("registry.example/os/atlas:beta");
    QVERIFY(c.recipe().toJson().contains(QStringLiteral("flatpaks")));
    QVERIFY(c.recipe().toJson().value(QStringLiteral("flatpaks")).toArray().isEmpty());
    // A hostname the user set is not replaced by the next leaf's.
    c.setHostname(QStringLiteral("my-box"));
    select("registry.example/os/boreal:latest");
    QCOMPARE(c.hostname(), QStringLiteral("my-box"));
}

void BackendTest::nvidiaDetectionFollowsThePciFixture()
{
    // shared/probe/fixtures/pci/cases.json: a PCI display device with
    // NVIDIA's vendor id, and nothing else, is an NVIDIA GPU.
    const QString pci = QStringLiteral(PROBE_FIXTURES_DIR "/pci");
    QFile file(pci + QStringLiteral("/cases.json"));
    QVERIFY2(file.open(QIODevice::ReadOnly), qPrintable(file.fileName()));
    const QJsonArray cases = QJsonDocument::fromJson(file.readAll()).object().value(QStringLiteral("cases")).toArray();
    QVERIFY(cases.size() >= 4);
    for (const QJsonValue &v : cases) {
        const QJsonObject row = v.toObject();
        QVERIFY2(imagecatalog::hasNvidiaGpuInDevices(pci + QLatin1Char('/') + row.value(QStringLiteral("devices")).toString())
                     == row.value(QStringLiteral("has_nvidia")).toBool(),
                 qPrintable(row.value(QStringLiteral("name")).toString()));
    }
}

void BackendTest::catalogNvidiaDetection()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString devices = dir.filePath(QStringLiteral("bus/pci/devices"));
    QVERIFY(!imagecatalog::hasNvidiaGpu(dir.path())); // no PCI bus at all
    // An NVIDIA device that is not a display controller (its audio
    // function) is not a GPU.
    QVERIFY(writeFile(devices + QStringLiteral("/0000:01:00.1/vendor"), "0x10de\n"));
    QVERIFY(writeFile(devices + QStringLiteral("/0000:01:00.1/class"), "0x040300\n"));
    QVERIFY(writeFile(devices + QStringLiteral("/0000:00:02.0/vendor"), "0x8086\n"));
    QVERIFY(writeFile(devices + QStringLiteral("/0000:00:02.0/class"), "0x030000\n"));
    QVERIFY(!imagecatalog::hasNvidiaGpu(dir.path()));
    QVERIFY(writeFile(devices + QStringLiteral("/0000:01:00.0/vendor"), "0x10de\n"));
    QVERIFY(writeFile(devices + QStringLiteral("/0000:01:00.0/class"), "0x030200\n"));
    QVERIFY(imagecatalog::hasNvidiaGpu(dir.path()));

    // The registry of a reference: networkTargetsFollowTheFixture.
}

void BackendTest::catalogFilesystemProblemReachesTheDiskStep()
{
    InstallerController c;
    QVERIFY(c.filesystemProblem().isEmpty());
    // fisherman's answer for a composefs image on xfs (rules.go): the
    // problem is against composeFsBackend, and the disk step shows it in
    // the copy's words.
    c.applyValidateAnswer(R"({"protocol_version": 1, "valid": false, "errors": [
        {"field": "composeFsBackend", "code": "composefs_requires_fsverity",
         "message": "composefs-backend requires fs-verity"}]})");
    QCOMPARE(c.filesystemProblem(), c.text(QStringLiteral("validate_composefs_requires_fsverity")));
    QVERIFY(!c.filesystemProblem().isEmpty());
    c.applyValidateAnswer(R"({"protocol_version": 1, "valid": false, "errors": [
        {"field": "filesystem", "code": "filesystem_unsupported", "message": "no"}]})");
    QCOMPARE(c.filesystemProblem(), c.text(QStringLiteral("validate_filesystem_unsupported")));
    c.applyValidateAnswer(R"({"protocol_version": 1, "valid": true, "errors": []})");
    QVERIFY(c.filesystemProblem().isEmpty());
}

// ---- the first account's groups (shared/account/README.md, #302) -----------

void BackendTest::accountGroupsAreTheSharedFile()
{
    const QByteArray shared = readFixture(QStringLiteral(SHARED_GROUPS_FILE));
    if (shared.isEmpty())
        QSKIP("shared/account/groups.json is absent");
    // CMake compiles this file in (TUNA_SHARED_DIR), so there is no copy.
    QCOMPARE(account::defaultGroups(),
             strings(QJsonDocument::fromJson(shared).object().value(QStringLiteral("default_groups"))));
    QVERIFY(account::defaultGroups().size() > 1);
    QCOMPARE(Recipe{}.user.groups, account::defaultGroups());
    QCOMPARE(account::operatorRecipePath(false), QStringLiteral("/etc/bootc-installer/recipe.json"));
    QCOMPARE(account::operatorRecipePath(true), QStringLiteral("/run/host/etc/bootc-installer/recipe.json"));
}

void BackendTest::accountGroupCases()
{
    const QJsonArray cases = QJsonDocument::fromJson(readFixture(QStringLiteral(SHARED_GROUPS_FILE)))
                                 .object().value(QStringLiteral("cases")).toArray();
    if (cases.isEmpty())
        QSKIP("shared/account/groups.json is absent");
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    for (const QJsonValue &v : cases) {
        const QJsonObject c = v.toObject();
        const QByteArray name = c.value(QStringLiteral("name")).toString().toUtf8();
        const QJsonValue file = c.value(QStringLiteral("operator_recipe"));
        const QStringList want = strings(c.value(QStringLiteral("groups")));
        const QString path = dir.filePath(QStringLiteral("recipe.json"));
        QFile::remove(path);
        if (file.isNull()) {
            QVERIFY2(account::groups(QByteArray()) == want, name);
        } else {
            const QByteArray json = QJsonDocument(file.toObject()).toJson();
            QVERIFY2(account::groups(json) == want, name);
            QVERIFY(writeFile(path, json));
        }
        // The same through the file, as the controller reads it.
        QVERIFY2(account::groups(account::readOperatorRecipe(path)) == want, name);
    }
    // A file that does not parse is the default list; an empty file is such
    // a file, not "no file".
    QVERIFY(writeFile(dir.filePath(QStringLiteral("bad.json")), "{ not json"));
    QCOMPARE(account::groups(account::readOperatorRecipe(dir.filePath(QStringLiteral("bad.json")))),
             account::defaultGroups());
    QVERIFY(writeFile(dir.filePath(QStringLiteral("empty.json")), ""));
    QVERIFY(!account::readOperatorRecipe(dir.filePath(QStringLiteral("empty.json"))).isNull());
    QVERIFY(account::readOperatorRecipe(dir.filePath(QStringLiteral("absent.json"))).isNull());
}

// ---- cancel (#299) ----------------------------------------------------------

// "R", "S", "Z", ... for a live or zombie pid; 0 when it is gone.
static char processState(qint64 pid)
{
    QFile f(QStringLiteral("/proc/%1/stat").arg(pid));
    if (!f.open(QIODevice::ReadOnly))
        return 0;
    const QByteArray stat = f.readAll();
    const int close = stat.lastIndexOf(')');
    return close >= 0 && close + 2 < stat.size() ? stat.at(close + 2) : 0;
}

void BackendTest::cancelSignalsTheGroupAndIsNotACrash()
{
#if !QT_CONFIG(process) || !defined(Q_OS_UNIX)
    QSKIP("needs QProcess and POSIX process groups");
#else
    InstallerController c;
    QSignalSpy done(&c, &InstallerController::installCompleted);
    // A stand-in for the wrapper: bash with a child, as bash has pkexec or
    // sudo under it. The child's pid is the first line of output.
    c.launch({QStringLiteral("bash"), QStringLiteral("-c"), QStringLiteral("sleep 300 & echo child=$!; wait")},
             QByteArray("{}"));
    QVERIFY(c.installing());
    static const QRegularExpression childLine(QStringLiteral("child=(\\d+)"));
    qint64 child = 0;
    for (int i = 0; i < 50 && child == 0; ++i) {
        QVERIFY(!c.waitForInstall(100));
        child = childLine.match(c.log()).captured(1).toLongLong();
    }
    QVERIFY2(child > 0, "the stand-in wrapper printed no child pid");
    QVERIFY(processState(child) != 0 && processState(child) != 'Z');

    c.cancelInstall();
    QVERIFY(c.waitForInstall(5000));
    QCOMPARE(done.count(), 1);
    // Killed by a signal after a cancel: cancelled, not "fisherman crashed".
    QVERIFY(c.cancelled());
    QVERIFY(!c.succeeded());
    QCOMPARE(c.exitCode(), 130);
    QVERIFY2(c.log().contains(QStringLiteral("Installation cancelled.")), qPrintable(c.log()));
    QVERIFY2(!c.log().contains(QStringLiteral("crashed")), qPrintable(c.log()));
    // The signal went to the whole group: the wrapper's child is gone too.
    // Signalling the wrapper's pid alone left it running.
    char state = processState(child);
    for (int i = 0; i < 50 && state != 0 && state != 'Z'; ++i) {
        QTest::qSleep(100);
        state = processState(child);
    }
    QVERIFY2(state == 0 || state == 'Z', "the wrapper's child survived the cancel");
    // This test's own group was not signalled, or it would not be here.

    // A wrapper that ends with its own exit code after the cancel is
    // cancelled too.
    InstallerController second;
    second.launch({QStringLiteral("bash"), QStringLiteral("-c"),
                   QStringLiteral("trap 'exit 3' TERM; echo trap-is-\"\"set; sleep 300 & wait")}, QByteArray("{}"));
    // The marker is not in the command line the log repeats, so this waits
    // for the trap, not for the "Running:" line.
    for (int i = 0; i < 50 && !second.log().contains(QStringLiteral("trap-is-set")); ++i)
        QVERIFY(!second.waitForInstall(100));
    second.cancelInstall();
    QVERIFY(second.waitForInstall(5000));
    QVERIFY(second.cancelled());
    QCOMPARE(second.exitCode(), 130);
#endif
}

void BackendTest::exitCode130IsCancelled()
{
#if !QT_CONFIG(process)
    QSKIP("needs QProcess");
#else
    // fisherman's own "cancelled" exit code, with no cancel from this side
    // (the user stopped it some other way).
    InstallerController c;
    c.launch({QStringLiteral("bash"), QStringLiteral("-c"), QStringLiteral("exit 130")}, QByteArray("{}"));
    QVERIFY(c.waitForInstall(5000));
    QVERIFY(c.cancelled());
    QVERIFY(!c.succeeded());
    QVERIFY(!c.log().contains(QStringLiteral("failed")));
    // The screenshot hook takes the same path.
    InstallerController demo;
    demo.loadDemoState(QString(), 130);
    QVERIFY(demo.cancelled());
    demo.loadDemoState(QString(), 1);
    QVERIFY(!demo.cancelled());
    demo.loadDemoState(QString(), 0);
    QVERIFY(demo.succeeded() && !demo.cancelled());
#endif
}

void BackendTest::anEndWithoutCancelIsStillAFailure()
{
#if !QT_CONFIG(process) || !defined(Q_OS_UNIX)
    QSKIP("needs QProcess and POSIX signals");
#else
    InstallerController failed;
    failed.launch({QStringLiteral("bash"), QStringLiteral("-c"), QStringLiteral("exit 3")}, QByteArray("{}"));
    QVERIFY(failed.waitForInstall(5000));
    QVERIFY(!failed.cancelled());
    QVERIFY(!failed.succeeded());
    QCOMPARE(failed.exitCode(), 3);
    // A signal nobody here sent is a crash, and is reported as one.
    InstallerController crashed;
    crashed.launch({QStringLiteral("bash"), QStringLiteral("-c"), QStringLiteral("kill -SEGV $$")}, QByteArray("{}"));
    QVERIFY(crashed.waitForInstall(5000));
    QVERIFY(!crashed.cancelled());
    QVERIFY(crashed.log().contains(QStringLiteral("crashed")));
    // A cancel that arrives after a successful end changes nothing.
    InstallerController ok;
    ok.launch({QStringLiteral("bash"), QStringLiteral("-c"), QStringLiteral("exit 0")}, QByteArray("{}"));
    QVERIFY(ok.waitForInstall(5000));
    ok.cancelInstall();
    QVERIFY(ok.succeeded());
    QVERIFY(!ok.cancelled());
#endif
}

// ---- the QML sources ---------------------------------------------------------

// A QML file without its comments. Strings are kept, so "//" inside one is
// not a comment.
static QString qmlCode(const QString &text)
{
    QString out;
    bool inString = false;
    for (int i = 0; i < text.size(); ++i) {
        const QChar ch = text.at(i);
        if (inString) {
            out += ch;
            if (ch == QLatin1Char('\\') && i + 1 < text.size())
                out += text.at(++i);
            else if (ch == QLatin1Char('"'))
                inString = false;
        } else if (ch == QLatin1Char('"')) {
            inString = true;
            out += ch;
        } else if (ch == QLatin1Char('/') && text.mid(i, 2) == QLatin1String("//")) {
            while (i < text.size() && text.at(i) != QLatin1Char('\n'))
                ++i;
            out += QLatin1Char('\n');
        } else if (ch == QLatin1Char('/') && text.mid(i, 2) == QLatin1String("/*")) {
            const int end = text.indexOf(QLatin1String("*/"), i + 2);
            const QString comment = text.mid(i, end < 0 ? -1 : end + 2 - i);
            out += QString(comment.count(QLatin1Char('\n')), QLatin1Char('\n'));
            i += comment.size() - 1;
        } else {
            out += ch;
        }
    }
    return out;
}

// The lint (#300): string literals in a text, label or title property that
// are not the argument of qsTr(). Returns "line: literal" for each.
static QStringList bareUserStrings(const QString &qml)
{
    // The properties a person reads.
    static const QSet<QString> textKeys{
        QStringLiteral("text"), QStringLiteral("label"), QStringLiteral("title"),
        QStringLiteral("subtitle"), QStringLiteral("description"), QStringLiteral("placeholderText"),
        QStringLiteral("statusMessage"), QStringLiteral("displayText"), QStringLiteral("name"),
        QStringLiteral("Accessible.name"), QStringLiteral("Accessible.description"),
        QStringLiteral("ToolTip.text"), QStringLiteral("toolTip")};
    static const QRegularExpression lineKey(QStringLiteral("^\\s*([A-Za-z_][\\w.]*)\\s*:"));
    static const QRegularExpression inlineKey(QStringLiteral("([A-Za-z_][\\w.]*)\\s*:\\s*[^;{:]*$"));
    static const QRegularExpression literal(QStringLiteral("\"((?:[^\"\\\\]|\\\\.)*)\""));
    static const QRegularExpression words(QStringLiteral("[A-Za-z]{2,}"));
    static const QRegularExpression copyKey(QStringLiteral("^[a-z0-9_]+$"));
    static const QRegularExpression oneLineObject(QStringLiteral("^\\s*[A-Z][\\w.]*\\s*\\{.*\\}\\s*$"));

    QStringList problems;
    QString current; // the property whose value the line continues
    const QStringList lines = qmlCode(qml).split(QLatin1Char('\n'));
    for (int n = 0; n < lines.size(); ++n) {
        const QString &line = lines.at(n);
        const QString trimmed = line.trimmed();
        const QRegularExpressionMatch own = lineKey.match(line);
        const bool object = oneLineObject.match(line).hasMatch();
        if (own.hasMatch())
            current = own.captured(1);
        else if (trimmed.isEmpty() || trimmed.endsWith(QLatin1Char('{')) || trimmed.startsWith(QLatin1Char('}')))
            current.clear();

        QRegularExpressionMatchIterator it = literal.globalMatch(line);
        while (it.hasNext()) {
            const QRegularExpressionMatch m = it.next();
            const QString value = m.captured(1);
            const QString before = line.left(m.capturedStart()).trimmed();
            // `ListElement { stepId: "x"; name: qsTr("X") }`: each literal
            // belongs to the key written before it.
            QString key = current;
            if (object)
                key = inlineKey.match(line.left(m.capturedStart())).captured(1);
            if (!textKeys.contains(key))
                continue;
            if (!words.match(value).hasMatch())
                continue; // punctuation, a separator, an empty string
            if (before.endsWith(QLatin1String("qsTr(")))
                continue;
            // A branding copy key, the argument of InstallerController.text().
            if (copyKey.match(value).hasMatch() && line.contains(QLatin1String(".text(")))
                continue;
            // A comparison, an index or markup is not a sentence.
            if (before.endsWith(QLatin1String("===")) || before.endsWith(QLatin1String("!=="))
                || before.endsWith(QLatin1Char('[')) || value.startsWith(QLatin1Char('<'))
                || value.startsWith(QLatin1String("\\\"")))
                continue;
            problems << QStringLiteral("%1: \"%2\"").arg(n + 1).arg(value);
        }
        if (trimmed.endsWith(QLatin1Char('}')) || trimmed.endsWith(QLatin1Char(';')))
            current.clear();
    }
    return problems;
}

static QStringList qmlSources()
{
    QStringList out;
    for (const QString &root : {QStringLiteral(KDE_SOURCE_DIR "/src/qml"), QStringLiteral(KDE_SOURCE_DIR "/modules")}) {
        QDirIterator it(root, {QStringLiteral("*.qml")}, QDir::Files, QDirIterator::Subdirectories);
        while (it.hasNext())
            out << it.next();
    }
    out.sort();
    return out;
}

void BackendTest::qmlStringsGoThroughQsTr()
{
    // The lint finds what it is for, in each shape the pages use.
    QCOMPARE(bareUserStrings(QStringLiteral("Label {\n    text: \"Bare words\"\n}\n")).size(), 1);
    QCOMPARE(bareUserStrings(QStringLiteral("Button {\n    text: ok ? qsTr(\"Yes\")\n        : \"No way\"\n}\n")),
             QStringList{QStringLiteral("3: \"No way\"")});
    QCOMPARE(bareUserStrings(QStringLiteral("X {\n    label: \"Pass\" + word\n    placeholderText: \"Search images\"\n}\n")).size(), 2);
    QCOMPARE(bareUserStrings(QStringLiteral("    ListElement { stepId: \"welcome\"; name: \"Welcome\"; url: \"a/b.qml\" }\n")),
             QStringList{QStringLiteral("1: \"Welcome\"")});
    QCOMPARE(bareUserStrings(QStringLiteral("D {\n    title: \"Exit installer?\"\n    Accessible.name: \"Step \" + n\n}\n")).size(), 2);
    // And leaves alone what is not a sentence for a person.
    QVERIFY(bareUserStrings(QStringLiteral(
        "Label {\n    objectName: \"someName\"\n    icon.name: \"dialog-cancel\"\n"
        "    text: qsTr(\"Step %1 of %2\").arg(a).arg(b)\n"
        "    description: InstallerController.text(removable ? \"confirm_warning_removable\" : \"confirm_warning\", disk)\n"
        "    title: a === \"confirm\" ? InstallerController.text(\"confirm_title\") : qsTr(\"Other\")\n"
        "    // text: \"a comment\"\n"
        "    label: x + \" \\u2014 \" + y\n"
        "    onClicked: {\n        console.log(\"not a property a person reads\");\n    }\n}\n")).isEmpty());

    const QStringList files = qmlSources();
    QVERIFY2(files.size() >= 9, "the QML sources were not found");
    QStringList problems;
    int translated = 0;
    for (const QString &path : files) {
        const QString text = QString::fromUtf8(readFixture(path));
        translated += text.count(QStringLiteral("qsTr("));
        for (const QString &p : bareUserStrings(text))
            problems << QDir(QStringLiteral(KDE_SOURCE_DIR)).relativeFilePath(path) + QLatin1Char(':') + p;
    }
    QVERIFY2(problems.isEmpty(),
             qPrintable(QStringLiteral("wrap these in qsTr() (#300):\n  ") + problems.join(QStringLiteral("\n  "))));
    // Not vacuous: the pages do have strings, and they are wrapped.
    QVERIFY2(translated > 50, qPrintable(QStringLiteral("only %1 qsTr() calls").arg(translated)));
}

void BackendTest::cancelAsksFirstInTheQml()
{
    // The progress step's Cancel opens the dialog; only the dialog's own
    // action, and the exit dialog of the window, stop the install (#299).
    // The capture harness clicks the button and reads the dialog; this
    // holds the wiring from the other side.
    const QString progress = qmlCode(QString::fromUtf8(
        readFixture(QStringLiteral(KDE_SOURCE_DIR "/modules/progress/contents/ui/main.qml"))));
    QVERIFY(!progress.isEmpty());
    static const QRegularExpression button(
        QStringLiteral("objectName: \"cancelInstallButton\"[^}]*onClicked: cancelDialog\\.open\\(\\)"));
    QVERIFY2(button.match(progress).hasMatch(), "Cancel does not open the confirmation");
    QCOMPARE(progress.count(QStringLiteral("cancelInstall()")), 1);
    QVERIFY(progress.indexOf(QStringLiteral("cancelInstall()")) > progress.indexOf(QStringLiteral("cancelConfirmStop")));
    QVERIFY(progress.indexOf(QStringLiteral("cancelInstall()")) < progress.indexOf(QStringLiteral("cancelConfirmKeep")));
    // No other page stops an install.
    for (const QString &path : qmlSources()) {
        if (path.endsWith(QStringLiteral("progress/contents/ui/main.qml")) || path.endsWith(QStringLiteral("/Main.qml")))
            continue;
        QVERIFY2(!qmlCode(QString::fromUtf8(readFixture(path))).contains(QStringLiteral("cancelInstall")),
                 qPrintable(path));
    }
    // The cancelled page's heading is the branding copy key.
    const QString done = qmlCode(QString::fromUtf8(
        readFixture(QStringLiteral(KDE_SOURCE_DIR "/modules/done/contents/ui/main.qml"))));
    QVERIFY(done.contains(QStringLiteral("InstallerController.text(\"done_cancelled_title\")")));
    QVERIFY(!InstallerController().text(QStringLiteral("done_cancelled_title")).isEmpty());
}

void BackendTest::confirmPageListsNoLocaleRows()
{
    // #292: the welcome step's pickers go into the recipe, and the confirm
    // step lists them. The welcome step no longer says "not applied".
    const QString confirm = qmlCode(QString::fromUtf8(
        readFixture(QStringLiteral(KDE_SOURCE_DIR "/modules/confirm/contents/ui/main.qml"))));
    for (const QString &name : {QStringLiteral("confirmLanguage"), QStringLiteral("confirmKeyboard"),
                                QStringLiteral("confirmTimezone"), QStringLiteral("regionProblem")})
        QVERIFY2(confirm.contains(name), qPrintable(name));
    const QString welcome = qmlCode(QString::fromUtf8(
        readFixture(QStringLiteral(KDE_SOURCE_DIR "/modules/welcome/contents/ui/main.qml"))));
    QVERIFY(!welcome.contains(QStringLiteral("regionNotApplied")));
    QVERIFY(welcome.contains(QStringLiteral("regionProblem")));

    // Nothing picked: the recipe keeps the image's values.
    {
        InstallerController untouched;
        const QJsonObject recipe = untouched.recipe().toJson();
        for (const char *key : {"locale", "keyboard", "timezone"})
            QVERIFY2(!recipe.contains(QLatin1String(key)), key);
    }
    // The pickers' values reach the recipe, in fisherman's shape.
    InstallerController c;
    c.setLanguage(QStringLiteral("de"));
    c.setKeyboardLayout(QStringLiteral("de"));
    c.setTimezone(QStringLiteral("Europe/Berlin"));
    const QJsonObject recipe = c.recipe().toJson();
    QCOMPARE(recipe.value(QStringLiteral("locale")).toString(), QStringLiteral("de_DE.UTF-8"));
    QCOMPARE(recipe.value(QStringLiteral("keyboard")).toObject(),
             (QJsonObject{{QStringLiteral("layout"), QStringLiteral("de")}}));
    QCOMPARE(recipe.value(QStringLiteral("timezone")).toString(), QStringLiteral("Europe/Berlin"));
    // And the partial recipe that the live check sends has them.
    const QJsonObject partial = QJsonDocument::fromJson(c.partialRecipe()).object();
    QCOMPARE(partial.value(QStringLiteral("locale")).toString(), QStringLiteral("de_DE.UTF-8"));
    QCOMPARE(partial.value(QStringLiteral("timezone")).toString(), QStringLiteral("Europe/Berlin"));
    // A language with no locale name of fisherman's form: no key.
    QCOMPARE(region::localeName(QString()), QString());
    QCOMPARE(region::localeName(QStringLiteral("en")).left(3), QStringLiteral("en_"));
    Recipe empty;
    empty.disk = QStringLiteral("/dev/vda");
    const QJsonObject none = empty.toJson();
    for (const char *key : {"locale", "keyboard", "timezone"})
        QVERIFY2(!none.contains(QLatin1String(key)), key);
    // Round trip.
    QCOMPARE(Recipe::fromJson(recipe).toJson().value(QStringLiteral("keyboard")), recipe.value(QStringLiteral("keyboard")));
}

void BackendTest::networkTargetsFollowTheFixture()
{
    // shared/network/targets.json: the targets of each reference, the
    // timeout and the variables that turn the check off.
    QFile file(QStringLiteral(NETWORK_TARGETS_FILE));
    QVERIFY2(file.open(QIODevice::ReadOnly), qPrintable(file.fileName()));
    const QJsonObject fixture = QJsonDocument::fromJson(file.readAll()).object();
    const QJsonArray cases = fixture.value(QStringLiteral("cases")).toArray();
    QVERIFY(cases.size() >= 20);
    for (const QJsonValue &v : cases) {
        const QJsonObject row = v.toObject();
        QStringList got;
        for (const region::Target &t : region::connectivityTargets(row.value(QStringLiteral("imgref")).toString()))
            got << t.host + QLatin1Char(':') + QString::number(t.port);
        QCOMPARE(got, strings(row.value(QStringLiteral("targets"))));
    }
    QCOMPARE(region::CONNECT_TIMEOUT_MS, fixture.value(QStringLiteral("timeout_seconds")).toInt() * 1000);
    QStringList names;
    for (const char *name : region::SKIP_ENV_VARS)
        names << QString::fromLatin1(name);
    QCOMPARE(names, strings(fixture.value(QStringLiteral("skip_env"))));
    for (const QJsonValue &v : fixture.value(QStringLiteral("skip_cases")).toArray()) {
        const QJsonObject row = v.toObject();
        for (const QString &name : names)
            qunsetenv(name.toLatin1().constData());
        const QJsonObject env = row.value(QStringLiteral("env")).toObject();
        for (auto it = env.begin(); it != env.end(); ++it)
            qputenv(it.key().toLatin1().constData(), it.value().toString().toUtf8());
        QCOMPARE(region::connectivityCheckSkipped(), row.value(QStringLiteral("skip")).toBool());
    }
    for (const QString &name : names)
        qunsetenv(name.toLatin1().constData());
}

void BackendTest::connectivityTriesTheImageRegistryFirst()
{
    // The registry of the selected image, then the shared targets (#301).
    const QList<region::Target> targets =
        region::connectivityTargets(QStringLiteral("quay.io/centos-bootc/centos-bootc:c10s"));
    QCOMPARE(targets.size(), 3);
    QCOMPARE(targets.at(0), (region::Target{QStringLiteral("quay.io"), 443}));
    QCOMPARE(targets.at(1), (region::Target{QStringLiteral("ghcr.io"), 443}));
    QCOMPARE(targets.at(2), (region::Target{QStringLiteral("8.8.8.8"), 53}));
    // No image, or one on the shared registry: no row twice.
    QCOMPARE(region::connectivityTargets(QString()).size(), 2);
    QCOMPARE(region::connectivityTargets(QStringLiteral("ghcr.io/example/os:1")).size(), 2);
    QVERIFY(!region::networkReachable({region::Target{QStringLiteral("nonexistent.invalid"), 443}}));
    QVERIFY(!region::networkReachable({}));
    // The settings tool is the desktop's, and the page offers the action
    // next to Retry on the two steps that gate on the network.
    const QStringList settings = region::networkSettingsCommand();
    QVERIFY(settings.last().startsWith(QStringLiteral("kcmshell6 kcm_networkmanagement")));
    const QString gate = qmlCode(QString::fromUtf8(readFixture(QStringLiteral(KDE_SOURCE_DIR "/src/qml/NetworkGate.qml"))));
    QVERIFY(gate.contains(QStringLiteral("InstallerController.openNetworkSettings()")));
    for (const char *step : {"welcome", "confirm"}) {
        const QString page = qmlCode(QString::fromUtf8(
            readFixture(QStringLiteral(KDE_SOURCE_DIR "/modules/%1/contents/ui/main.qml").arg(QLatin1String(step)))));
        QVERIFY2(page.contains(QStringLiteral("NetworkGate {")), step);
        QVERIFY2(page.contains(QStringLiteral("!networkGate.blocked")), step);
    }
}

QTEST_APPLESS_MAIN(BackendTest)

#include "test_backend.moc"
