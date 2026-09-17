#include "installercontroller.h"
#include "log.h"
#include "offline.h"
#include "productname.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QStandardPaths>
#include <QTemporaryDir>

InstallerController::InstallerController(QObject *parent)
    : QObject(parent)
{
    m_hasTpm = QFileInfo::exists(QStringLiteral("/sys/class/tpm/tpm0"));
    m_productName = product::resolve();
}

void InstallerController::setDisk(const QString &v)
{
    if (m_recipe.disk == v)
        return;
    m_recipe.disk = v;
    Q_EMIT recipeChanged();
}

void InstallerController::setFilesystem(const QString &v)
{
    if (m_recipe.filesystem == v)
        return;
    m_recipe.filesystem = v;
    Q_EMIT recipeChanged();
}

void InstallerController::setBtrfsSubvolumes(bool v)
{
    if (m_recipe.btrfsSubvolumes == v)
        return;
    m_recipe.btrfsSubvolumes = v;
    Q_EMIT recipeChanged();
}

void InstallerController::setEncryptionType(const QString &v)
{
    if (m_recipe.encryption.type == v)
        return;
    m_recipe.encryption.type = v;
    // A type that takes no passphrase must not keep one lying around in the
    // recipe file.
    if (!v.endsWith(QLatin1String("passphrase")))
        m_recipe.encryption.passphrase.clear();
    Q_EMIT recipeChanged();
}

void InstallerController::setPassphrase(const QString &v)
{
    if (m_recipe.encryption.passphrase == v)
        return;
    m_recipe.encryption.passphrase = v;
    Q_EMIT recipeChanged();
}

void InstallerController::setHostname(const QString &v)
{
    if (m_recipe.hostname == v)
        return;
    m_recipe.hostname = v;
    Q_EMIT recipeChanged();
}

void InstallerController::setImage(const QString &v)
{
    if (m_recipe.image == v)
        return;
    m_recipe.image = v;
    Q_EMIT recipeChanged();
}

QString InstallerController::encryptionLabel(const QString &type) const
{
    if (type == QLatin1String("luks-passphrase"))
        return QStringLiteral("Passphrase (LUKS)");
    if (type == QLatin1String("tpm2-luks"))
        return QStringLiteral("TPM");
    if (type == QLatin1String("tpm2-luks-passphrase"))
        return QStringLiteral("TPM + passphrase");
    return QStringLiteral("None");
}

// The install log existed only in m_log, i.e. only in the TextArea on the
// progress page. Everything fisherman said about a failure was gone the moment
// the window closed — and after a failed install the next step is usually to
// close it and reboot. Mirror it to a file as it arrives, so it outlives both
// the window and the session that produced it.
void InstallerController::openLogFile()
{
    // A retry must not keep advertising the previous run's file.
    closeLogFile();
    if (!m_logPath.isEmpty()) {
        m_logPath.clear();
        Q_EMIT logPathChanged();
    }

    const QString dir = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    if (dir.isEmpty() || !QDir().mkpath(dir)) {
        qCWarning(logInstaller) << "no writable location for the install log:" << dir;
        return;
    }

    const QString path =
        QDir(dir).filePath(QStringLiteral("install-%1.log")
                               .arg(QDateTime::currentDateTimeUtc()
                                        .toString(QStringLiteral("yyyyMMdd-hhmmss"))));

    auto *file = new QFile(path, this);
    if (!file->open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text)) {
        qCWarning(logInstaller) << "cannot open the install log" << path << ":"
                                << file->errorString();
        delete file;
        return;
    }
    // fisherman's output is not expected to contain the passphrase, but this
    // file records a privileged install verbatim: keep it owner-only rather
    // than trusting the umask.
    file->setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner);

    m_logFile = file;
    m_logPath = path;
    qCInfo(logInstaller) << "writing the install log to" << path;
    Q_EMIT logPathChanged();
}

void InstallerController::closeLogFile()
{
    if (!m_logFile)
        return;
    m_logFile->close();
    m_logFile->deleteLater();
    m_logFile = nullptr;
}

void InstallerController::appendLine(const QString &line)
{
    m_log += line;
    if (!line.endsWith(QLatin1Char('\n')))
        m_log += QLatin1Char('\n');

    if (m_logFile) {
        m_logFile->write(line.toUtf8());
        if (!line.endsWith(QLatin1Char('\n')))
            m_logFile->write("\n");
        // Flushed per line: the interesting case is the one where the machine
        // is about to be rebooted or powered off by hand.
        m_logFile->flush();
    }

    Q_EMIT logChanged();
}

void InstallerController::drainBuffer(const QString &prefix)
{
    QStringList lines = m_buffer.split(QLatin1Char('\n'));
    if (lines.size() <= 1)
        return;
    for (int i = 0; i < lines.size() - 1; ++i)
        appendLine(prefix + lines.at(i));
    m_buffer = lines.last();
}

void InstallerController::fail(const QString &message)
{
    qCWarning(logInstaller) << "install failed:" << message;
    appendLine(QStringLiteral("\nERROR: %1").arg(message));
    closeLogFile();
    m_finished = true;
    m_exitCode = 1;
    Q_EMIT installCompleted(1);
}

void InstallerController::loadDemoState(const QString &log, int exitCode)
{
    m_log = log;
    m_finished = true;
    m_exitCode = exitCode;
    Q_EMIT logChanged();
    Q_EMIT installCompleted(exitCode);
}

void InstallerController::startInstall()
{
    if (m_process)
        return;

    // Offline install support (INSTALLER-FRONTENDS.md §4): live-ISO mode allows
    // an empty image; embedded stores are always passed — fisherman ignores
    // unhelpful ones.
    if (m_recipe.image.isEmpty() && !offline::liveIsoImage().isEmpty())
        m_recipe.liveMode = true;
    if (m_recipe.additionalImageStores.isEmpty())
        m_recipe.additionalImageStores = offline::offlineStores();

    m_log.clear();
    m_buffer.clear();
    m_finished = false;
    Q_EMIT logChanged();

    // Before the recipe is written, so the failures below are logged too.
    openLogFile();
    appendLine(QStringLiteral("Starting installation..."));

    // The recipe can hold a LUKS passphrase — write it 0600 in a fresh
    // 0700 private directory, never a fixed world-writable temp path.
    //
    // This used to be `<base>/tuna-installer/recipe.json` where base is
    // XDG_RUNTIME_DIR or /tmp (when unset — the default under sudo, whose
    // env_reset strips it). QDir::mkpath with a fixed name in a
    // world-writable directory:
    //   * follows a pre-existing attacker symlink when the file is opened
    //     with WriteOnly|Truncate,
    //   * creates the file 0644 (umask) and only THEN chmods it 0600, so
    //     the passphrase is briefly world-readable,
    //   * accepts a pre-created 0777 directory as-is (mode applied only on
    //     creation), giving a local user ownership of the path that is
    //     handed to root via sudo/pkexec fisherman.
    // QTemporaryDir is the mkdtemp analogue: unpredictable 0700 directory
    // with O_EXCL semantics, so none of those races exist. It is a member so
    // the directory survives until fisherman exits — a local QTemporaryDir
    // would auto-remove the recipe file the moment startInstall returns.
    if (!m_recipeDir.isValid())
        m_recipeDir = QTemporaryDir();
    if (!m_recipeDir.isValid()) {
        fail(QStringLiteral("Failed to create private recipe directory"));
        return;
    }
    m_recipePath = m_recipeDir.filePath(QStringLiteral("recipe.json"));
    QFile f(m_recipePath);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        fail(QStringLiteral("Failed to write recipe file"));
        return;
    }
    // Inside a 0700 dir the file needs no extra hardening, but keep 0600
    // explicit so the mode survives being copied/moved elsewhere.
    f.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner);
    f.write(QJsonDocument(m_recipe.toJson()).toJson(QJsonDocument::Indented));
    f.close();

    // pkexec /app/bin/fisherman in Flatpak, sudo /usr/local/bin/fisherman otherwise.
    QStringList cmd = offline::fishermanCommand();
    cmd << m_recipePath;

    m_process = new QProcess(this);
    m_process->setProgram(cmd.takeFirst());
    m_process->setArguments(cmd);

    // Which escalation path was taken (pkexec via flatpak-spawn, or sudo) is
    // the first thing anyone reading a failed install needs to know.
    appendLine(QStringLiteral("Running: %1 %2")
                   .arg(m_process->program(), m_process->arguments().join(QLatin1Char(' '))));

    // Without this, a fisherman that never starts — no pkexec in the sandbox,
    // the polkit agent missing, the binary not installed — emitted no
    // finished() either. The wizard sat on the progress page with a spinner
    // and "Starting installation..." forever, saying nothing.
    connect(m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        // Every other error is followed by finished(), which reports it below.
        if (error != QProcess::FailedToStart)
            return;
        const QString message = QStringLiteral("Could not start %1: %2")
                                    .arg(m_process->program(), m_process->errorString());
        m_process->deleteLater();
        m_process = nullptr;
        Q_EMIT installingChanged();
        fail(message);
    });

    connect(m_process, &QProcess::readyReadStandardOutput, this, [this]() {
        m_buffer += QString::fromUtf8(m_process->readAllStandardOutput());
        drainBuffer({});
    });
    connect(m_process, &QProcess::readyReadStandardError, this, [this]() {
        m_buffer += QString::fromUtf8(m_process->readAllStandardError());
        drainBuffer(QStringLiteral("[stderr] "));
    });
    connect(m_process, &QProcess::finished, this,
            [this](int exitCode, QProcess::ExitStatus status) {
        if (!m_buffer.isEmpty()) {
            appendLine(m_buffer);
            m_buffer.clear();
        }
        // The recipe may hold secrets — remove it as soon as fisherman is done.
        if (!m_recipePath.isEmpty())
            QFile::remove(m_recipePath);

        if (status == QProcess::CrashExit) {
            qCWarning(logInstaller) << "fisherman crashed";
            appendLine(QStringLiteral("\nERROR: fisherman crashed"));
            m_exitCode = 1;
        } else {
            m_exitCode = exitCode;
            if (exitCode != 0)
                qCWarning(logInstaller) << "fisherman exited with" << exitCode;
            appendLine(exitCode == 0
                           ? QStringLiteral("\n✓ Installation complete!")
                           : QStringLiteral("\n✗ Installation failed (exit code %1)").arg(exitCode));
        }
        if (!m_logPath.isEmpty())
            appendLine(QStringLiteral("Log: %1").arg(m_logPath));
        closeLogFile();
        m_finished = true;
        m_process->deleteLater();
        m_process = nullptr;
        Q_EMIT installingChanged();
        Q_EMIT installCompleted(m_exitCode);
    });

    m_process->start();
    Q_EMIT installingChanged();
}
