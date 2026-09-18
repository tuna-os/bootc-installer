// End to end: InstallerController drives the real backend launch path.
//
// This is the code the Install button runs, minus the button: the
// controller writes the 0600 recipe into its private directory, launches
// `sudo /usr/local/bin/fisherman <recipe>` (the same fishermanCommand() the
// shipped binary uses outside Flatpak), streams its stdout/stderr into the
// log, persists the log file and emits installCompleted(exitCode) when the
// process exits. shared/e2e/setup.sh has put the validating shim at that
// path, so what runs is the real fisherman's Validate() on the recipe this
// controller produced.
//
// Built with -DBUILD_E2E=ON as tuna-installer-e2e. Exit 0 only when the
// controller reports success and its log reached step 9.

#include "installercontroller.h"

#include <QCoreApplication>
#include <QEventLoop>
#include <QFile>
#include <QTextStream>
#include <QTimer>

int main(int argc, char *argv[])
{
    QCoreApplication app(argc, argv);
    QTextStream out(stdout);

    const QByteArray disk = qgetenv("TUNA_E2E_DISK");
    if (disk.isEmpty()) {
        out << "FAIL: TUNA_E2E_DISK is not set (run shared/e2e/setup.sh)\n";
        return 2;
    }

    InstallerController controller;
    // What a user picks on the disk and options steps. The image is the
    // ostree + grub2 canary the VM job installs; no composefs on xfs.
    controller.setDisk(QString::fromUtf8(disk));
    controller.setFilesystem(QStringLiteral("xfs"));
    controller.setImage(QStringLiteral("quay.io/centos-bootc/centos-bootc:c10s"));
    controller.setEncryptionType(QStringLiteral("none"));
    controller.setHostname(QStringLiteral("kde-e2e"));

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
    if (!controller.log().contains(QLatin1String("[9/9]"))) {
        out << "FAIL: the log never reached step 9\n";
        return 1;
    }
    out << "OK: KDE controller reached installCompleted(0) through sudo /usr/local/bin/fisherman\n";
    return 0;
}
