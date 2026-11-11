// End to end: InstallerController drives the real backend launch path.
//
// This is the code the Install button runs, minus the button: the
// controller selects an image from a catalog, launches
// `bash -c 'pkexec /usr/local/bin/fisherman -; exit $?'` (fisherman.h's
// native command; shared/e2e/fake-bin/pkexec stands in for a polkit agent),
// writes the recipe to its stdin, streams its stdout/stderr into the log,
// persists the log file and emits installCompleted(exitCode) when the
// process exits. shared/e2e/setup.sh has put the validating shim at that
// path, so what runs is the real fisherman's Validate() on the recipe this
// controller produced.
//
// Built with -DBUILD_E2E=ON as tuna-installer-e2e. Exit 0 only when the
// controller reports success and its log carried fisherman's completion event.

#include "installercontroller.h"
#include "account.h"

#include <QCoreApplication>
#include <QEventLoop>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextStream>
#include <QTimer>

#include <functional>

int main(int argc, char *argv[])
{
    QCoreApplication app(argc, argv);
    QTextStream out(stdout);

    const QByteArray disk = qgetenv("TUNA_E2E_DISK");
    if (disk.isEmpty()) {
        out << "FAIL: TUNA_E2E_DISK is not set (run shared/e2e/setup.sh)\n";
        return 2;
    }

    // The catalog every E2E driver gives its frontend (shared/e2e/catalog.json),
    // copied next to the recipe so shared/e2e/check-recipe.py can judge "an
    // account iff the image needs one" against it. This run installs the
    // canary leaf, which needs an account. The composefs leaf has its own
    // filesystem and needs none: selecting it first shows that the next
    // leaf's values replace it (#287).
    const QString e2eDir = qEnvironmentVariable("TUNA_E2E_DIR", QStringLiteral("/tmp/tuna-e2e"));
    const QString catalogPath = e2eDir + QStringLiteral("/catalog.json");
    const QString canary = QStringLiteral("quay.io/centos-bootc/centos-bootc:c10s");
    const QString composefsLeaf = QStringLiteral("registry.example/os/composefs:1");
    QJsonObject sharedCatalog;
    {
        QFile source(QStringLiteral(E2E_CATALOG_FILE));
        if (!source.open(QIODevice::ReadOnly)) {
            out << "FAIL: cannot read " << source.fileName() << "\n";
            return 2;
        }
        const QByteArray text = source.readAll();
        sharedCatalog = QJsonDocument::fromJson(text).object();
        QFile::remove(catalogPath);
        QFile catalog(catalogPath);
        if (!catalog.open(QIODevice::WriteOnly) || catalog.write(text) != text.size()) {
            out << "FAIL: cannot write " << catalogPath << "\n";
            return 2;
        }
    }
    qputenv("FISHERMAN_IMAGES_PATH", catalogPath.toUtf8());

    InstallerController controller;
    // The catalog's default_image is the selection at the start
    // (shared/catalog/README.md, "Default selection").
    const QString defaultImage = sharedCatalog.value(QStringLiteral("default_image")).toString();
    if (controller.catalogIndex() != controller.catalogImgrefs().indexOf(defaultImage)) {
        out << "FAIL: the image selected at start is not the catalog's default_image "
            << defaultImage << "\n";
        return 1;
    }
    // What a user picks on the disk step: the disk, then the composefs
    // image, then the image this run installs.
    controller.setDisk(QString::fromUtf8(disk));
    controller.selectCatalogImage(controller.catalogImgrefs().indexOf(composefsLeaf));
    if (controller.filesystem() != QLatin1String("btrfs") || controller.needsUserCreation()) {
        out << "FAIL: the composefs leaf did not bring its filesystem and its account flag\n";
        return 1;
    }
    controller.selectCatalogImage(controller.catalogImgrefs().indexOf(canary));
    if (controller.image() != canary || controller.filesystem() != QLatin1String("xfs")
        || controller.recipe().composeFsBackend || !controller.needsUserCreation()) {
        out << "FAIL: selecting the canary left values of the leaf before it in the recipe\n";
        return 1;
    }
    controller.setEncryptionType(QStringLiteral("none"));
    controller.setHostname(QStringLiteral("kde-e2e"));

    // The account step. First a name fisherman refuses, through the same
    // `validate --json --partial -` the step runs while the user types (the
    // shim hands it to the real fisherman): the step must show the problem
    // and hold Next on it. Then the account the user actually creates.
    const auto waitFor = [](const std::function<bool()> &done, int ms) {
        QEventLoop wait;
        QTimer poll;
        QObject::connect(&poll, &QTimer::timeout, &wait, [&] {
            if (done())
                wait.quit();
        });
        QTimer::singleShot(ms, &wait, &QEventLoop::quit);
        poll.start(50);
        wait.exec();
        return done();
    };
    controller.setUsername(QStringLiteral("root"));
    if (!waitFor([&] { return !controller.usernameProblem().isEmpty(); }, 15000)) {
        out << "FAIL: fisherman reported no problem with the username \"root\" — the "
               "account step's validate --json --partial call is not reaching it\n";
        return 1;
    }
    out << "e2e: username \"root\" refused: " << controller.usernameProblem() << "\n";
    const QString username = QStringLiteral("kdeuser");
    controller.setUsername(username);
    controller.setFullname(QStringLiteral("KDE E2E"));
    controller.setUserPassword(QStringLiteral("kde-e2e-password"));
    if (!waitFor([&] { return controller.usernameProblem().isEmpty(); }, 15000)) {
        out << "FAIL: fisherman still reports a problem with the username \"" << username
            << "\": " << controller.usernameProblem() << "\n";
        return 1;
    }

    int exitCode = -1;
    QEventLoop loop;
    QObject::connect(&controller, &InstallerController::installCompleted, &loop,
                     [&](int code) { exitCode = code; loop.quit(); });
    QTimer::singleShot(120000, &loop, [&] {
        out << "FAIL: no installCompleted after 120s\n";
        loop.quit();
    });

    out << "e2e: pressing Install\n";
    controller.startInstall();
    loop.exec();

    out << "e2e: log path " << controller.logPath() << "\n";
    out << controller.log() << "\n";
    if (exitCode != 0) {
        out << "FAIL: fisherman exit code " << exitCode << "\n";
        return 1;
    }
    if (!controller.succeeded()) {
        out << "FAIL: controller does not report success\n";
        return 1;
    }
    // Where the progress bar ended up. This checked the log text for
    // fisherman's raw `"type":"complete"` event, which worked only while the
    // controller stored the protocol verbatim; it now renders events for the
    // log pane and keeps the raw lines in the log FILE, so that string is no
    // longer in log().
    //
    // Asserting the bar instead is the stronger check anyway, and matches
    // what the XFCE and Niri drivers do: a controller that does not parse
    // fisherman's protocol still reaches installCompleted(0) and still
    // reports success, and only the bar shows the difference.
    if (controller.installFraction() != 1.0) {
        out << "FAIL: the progress bar ended at " << controller.installFraction()
            << ", not 1.0 — the controller is not parsing fisherman's progress "
               "protocol (shared/progress/README.md)\n";
        return 1;
    }
    if (!controller.log().contains(QLatin1String("Installation complete"))) {
        out << "FAIL: the log carried no completion event\n";
        return 1;
    }
    // The recipe fisherman was handed on stdin, as the shim kept it: it
    // must create the account (shared/e2e/check-recipe.py then runs the
    // real fisherman's full validate and the schema over the same file).
    QFile kept(e2eDir + QStringLiteral("/recipe.json"));
    if (!kept.open(QIODevice::ReadOnly)) {
        out << "FAIL: the shim kept no recipe at " << kept.fileName() << "\n";
        return 1;
    }
    const QJsonObject recipe = QJsonDocument::fromJson(kept.readAll()).object();
    if (recipe.value(QStringLiteral("image")).toString() != canary
        || recipe.value(QStringLiteral("targetImgref")).toString() != canary
        || recipe.value(QStringLiteral("filesystem")).toString() != QLatin1String("xfs")
        || recipe.value(QStringLiteral("bootloader")).toString() != QLatin1String("grub2")
        || recipe.contains(QStringLiteral("composeFsBackend"))
        || !recipe.value(QStringLiteral("flatpaks")).isArray()) {
        out << "FAIL: the recipe does not carry the selected catalog leaf\n";
        return 1;
    }
    const QJsonObject user = recipe.value(QStringLiteral("user")).toObject();
    if (user.value(QStringLiteral("username")).toString() != username
        || user.value(QStringLiteral("password")).toString().isEmpty()
        || user.value(QStringLiteral("groups")).toArray()
               != QJsonArray::fromStringList(account::defaultGroups())) {
        out << "FAIL: the recipe's user block is not the account the step created: "
            << QJsonDocument(QJsonObject{{QStringLiteral("username"), user.value(QStringLiteral("username"))},
                                         {QStringLiteral("groups"), user.value(QStringLiteral("groups"))}})
                   .toJson(QJsonDocument::Compact)
            << "\n";
        return 1;
    }
    out << "OK: KDE controller reached installCompleted(0) through pkexec /usr/local/bin/fisherman\n";
    return 0;
}
