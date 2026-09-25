#include "installercontroller.h"
#include "tpm.h"
#include "log.h"
#include "offline.h"
#include "branding.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QTemporaryDir>

InstallerController::InstallerController(QObject *parent)
    : QObject(parent)
{
    // BOOTC_INSTALLER_FAKE_TPM only ever makes the two TPM choices VISIBLE,
    // and exists because hiding them means a capture taken on a machine
    // without a TPM -- every CI runner -- renders a two-option encryption
    // page. docs/PARITY.md is read off those screenshots, so this frontend
    // was recorded as having no TPM support when it has offered both TPM
    // modes all along. Picking one still writes an ordinary recipe; fisherman
    // is what fails, later and loudly, if there is no TPM to enrol against.
    // Same variable and same meaning as the XFCE frontend's core.has_tpm().
    const QByteArray fakeTpm = qgetenv("BOOTC_INSTALLER_FAKE_TPM");
    m_hasTpm = (!fakeTpm.isEmpty() && fakeTpm != "0")
        || tpm::probe2(QStringLiteral("/"));
    // Product identity per shared/branding/README.md: branding.json, then
    // os-release, then neutral. Nothing in this frontend names a product.
    m_branding = branding::resolve();
    m_productName = m_branding.name;
    m_recipe.distroID = m_branding.id;
    m_recipe.hostname = m_branding.defaultHostname;
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

// Friendly labels for fisherman's step names, matching the other frontends
// (shared/progress/progress_parser.py). An unknown step falls back to its raw
// name, so a new step in fisherman degrades to showing what it really is
// rather than showing nothing.
static QString friendlyStep(const QString &name, const QString &product)
{
    static const QHash<QString, QString> labels = {
        {QStringLiteral("Preparing disk"), QStringLiteral("Checking your drive…")},
        {QStringLiteral("Partitioning disk"), QStringLiteral("Setting up your drive…")},
        {QStringLiteral("Formatting EFI partition"), QStringLiteral("Preparing the boot system…")},
        {QStringLiteral("Setting up disk encryption"), QStringLiteral("Securing your drive…")},
        {QStringLiteral("Formatting root filesystem"), QStringLiteral("Formatting your drive…")},
        {QStringLiteral("Mounting filesystem"), QStringLiteral("Almost ready…")},
        {QStringLiteral("Formatting data disk (/var)"), QStringLiteral("Preparing data storage…")},
        // The one label that names the product. It must say what THIS build
        // installs; nothing here may name a distro (CLAUDE.md).
        {QStringLiteral("Installing OS"), QStringLiteral("Installing %1…")},
        {QStringLiteral("Enrolling TPM2 auto-unlock"), QStringLiteral("Setting up auto-unlock…")},
        {QStringLiteral("Copying system Flatpaks"), QStringLiteral("Installing your apps…")},
        {QStringLiteral("Configuring installed system"), QStringLiteral("Configuring your system…")},
        {QStringLiteral("Finalizing installation"), QStringLiteral("Finishing up…")},
    };
    const QString label = labels.value(name, name);
    return label.contains(QLatin1String("%1")) ? label.arg(product) : label;
}

void InstallerController::setRecoveryAck(bool v)
{
    if (m_recoveryAck == v)
        return;
    m_recoveryAck = v;
    Q_EMIT recoveryChanged();
}

void InstallerController::resetProgress()
{
    m_step = 0;
    m_totalSteps = 0;
    m_fraction = 0.0;
    m_stepName.clear();
    m_recoveryKey.clear();
    m_recoveryAck = false;
    Q_EMIT recoveryChanged();
    m_cumulativePct = 0;
    m_weightPct = 0;
    Q_EMIT progressChanged();
}

QString InstallerController::consumeProgress(const QString &line)
{
    const QString trimmed = line.trimmed();
    if (!trimmed.startsWith(QLatin1Char('{')))
        return line;
    QJsonParseError err{};
    const QJsonDocument doc = QJsonDocument::fromJson(trimmed.toUtf8(), &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject())
        return line;

    const QJsonObject event = doc.object();
    const QString type = event.value(QStringLiteral("type")).toString();

    if (type == QLatin1String("step")) {
        m_step = event.value(QStringLiteral("step")).toInt();
        m_totalSteps = event.value(QStringLiteral("total_steps")).toInt();
        const QString name = event.value(QStringLiteral("step_name")).toString();
        m_cumulativePct = event.value(QStringLiteral("cumulative_pct")).toInt();
        m_weightPct = event.value(QStringLiteral("weight_pct")).toInt();
        m_fraction = m_cumulativePct / 100.0;
        m_stepName = friendlyStep(name, m_productName);
        Q_EMIT progressChanged();
        return QStringLiteral("[%1/%2] %3").arg(m_step).arg(m_totalSteps).arg(name);
    }
    if (type == QLatin1String("substep") || type == QLatin1String("info")) {
        const QString message = event.value(QStringLiteral("message")).toString();
        if (type == QLatin1String("substep") && m_weightPct > 0) {
            // Interpolate across the image pull: it is the long step, and
            // without this the bar freezes there for most of the install.
            static const QRegularExpression layers(
                QStringLiteral("Pulling image: layer (\\d+)/(\\d+)"));
            const QRegularExpressionMatch m = layers.match(message);
            if (m.hasMatch()) {
                const double done = m.captured(1).toDouble();
                const double total = m.captured(2).toDouble();
                if (total > 0) {
                    m_fraction = qMin((m_cumulativePct + (done / total) * m_weightPct) / 100.0, 1.0);
                    Q_EMIT progressChanged();
                }
            }
        }
        return message.isEmpty() ? QString() : QStringLiteral("  ") + message;
    }
    if (type == QLatin1String("complete")) {
        // cumulative_pct only ever reaches 99; `complete` fills the bar.
        m_fraction = 1.0;
        Q_EMIT progressChanged();
        const QString message = event.value(QStringLiteral("message")).toString();
        return message.isEmpty() ? QStringLiteral("Installation complete") : message;
    }
    if (type == QLatin1String("error"))
        return QStringLiteral("ERROR: ") + event.value(QStringLiteral("message")).toString();
    if (type == QLatin1String("recovery_key")) {
        // Kept in the log as well as on the done page: the log is what gets
        // pasted into a bug report, and a key that only ever existed on a
        // screen the user already dismissed is no better than one that was
        // never shown (#129).
        m_recoveryKey = event.value(QStringLiteral("key")).toString();
        Q_EMIT recoveryChanged();
        return QStringLiteral("Recovery key: ") + m_recoveryKey;
    }
    return QString();
}

void InstallerController::appendLine(const QString &line)
{
    // The log PANE shows the event rendered for a person; the log FILE keeps
    // the raw protocol, because that is what gets attached to a bug report.
    const QString shown = consumeProgress(line);
    if (!shown.isEmpty()) {
        m_log += shown;
        if (!shown.endsWith(QLatin1Char('\n')))
            m_log += QLatin1Char('\n');
    }

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
    // Through appendLine(), the path a real install takes, so the bar and the
    // step caption are the live code rather than something the harness paints
    // on. Assigning m_log directly, as this used to, is how a screen can be
    // photographed without running any of what it is supposed to show.
    m_log.clear();
    resetProgress();
    const QStringList lines = log.split(QLatin1Char('\n'));
    for (const QString &line : lines) {
        if (!line.trimmed().isEmpty())
            appendLine(line);
    }
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
    // Not a live ISO and nothing chosen: the branding's default image. Empty
    // stays empty and validation reports "No OS image specified".
    if (m_recipe.image.isEmpty() && !m_recipe.liveMode)
        m_recipe.image = m_branding.defaultImage;
    if (m_recipe.additionalImageStores.isEmpty())
        m_recipe.additionalImageStores = offline::offlineStores();

    m_log.clear();
    m_buffer.clear();
    m_finished = false;
    Q_EMIT logChanged();

    // Before the recipe is written, so the failures below are logged too.
    openLogFile();
    resetProgress();
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

void InstallerController::reboot()
{
    // Same host path as the install: flatpak-spawn --host when sandboxed.
    QStringList argv = offline::hostCommand({QStringLiteral("systemctl"), QStringLiteral("reboot")});
    const QString program = argv.takeFirst();
    QProcess::startDetached(program, argv);
}
