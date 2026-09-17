#pragma once

// The wizard's state and the fisherman backend, exposed to QML.
//
// This is the old Wizard/QWidget page logic with the widgets removed: the
// Recipe, the recipe file writing, the privileged fisherman QProcess and the
// live-ISO/offline handling are unchanged — they just talk to QML properties
// now instead of QLabels.

#include <QFile>
#include <QObject>
#include <QProcess>
#include <QString>
#include <QTemporaryDir>
#include <qqmlintegration.h>

#include "recipe.h"

class InstallerController : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON

    Q_PROPERTY(QString disk READ disk WRITE setDisk NOTIFY recipeChanged)
    Q_PROPERTY(QString filesystem READ filesystem WRITE setFilesystem NOTIFY recipeChanged)
    Q_PROPERTY(bool btrfsSubvolumes READ btrfsSubvolumes WRITE setBtrfsSubvolumes NOTIFY recipeChanged)
    Q_PROPERTY(QString encryptionType READ encryptionType WRITE setEncryptionType NOTIFY recipeChanged)
    Q_PROPERTY(QString passphrase READ passphrase WRITE setPassphrase NOTIFY recipeChanged)
    Q_PROPERTY(QString hostname READ hostname WRITE setHostname NOTIFY recipeChanged)
    Q_PROPERTY(QString image READ image WRITE setImage NOTIFY recipeChanged)

    // /sys/class/tpm/tpm0 — the same probe the XFCE frontend uses. TPM
    // options are hidden, not disabled, when absent: offering them on a
    // machine without a TPM only fails later, at install time.
    Q_PROPERTY(bool hasTpm READ hasTpm CONSTANT)

    // The variant's name — "Skipjack", "Bonito", … — resolved ONCE at startup
    // from os-release (see src/productname.h). Every user-visible string that
    // used to say "TunaOS" reads this instead, so a Skipjack ISO says
    // Skipjack. CONSTANT: os-release cannot change under a running installer.
    Q_PROPERTY(QString productName READ productName CONSTANT)

    Q_PROPERTY(QString log READ log NOTIFY logChanged)

    // Where the same log is being written on disk, empty when the file could
    // not be opened. The done step shows it: the in-window log dies with the
    // window, and a failed install is exactly when someone needs to reboot,
    // ask for help, or attach the output to a bug report.
    Q_PROPERTY(QString logPath READ logPath NOTIFY logPathChanged)

    Q_PROPERTY(bool installing READ installing NOTIFY installingChanged)
    Q_PROPERTY(bool installFinished READ installFinishedFlag NOTIFY installCompleted)
    Q_PROPERTY(int exitCode READ exitCode NOTIFY installCompleted)
    Q_PROPERTY(bool succeeded READ succeeded NOTIFY installCompleted)

public:
    explicit InstallerController(QObject *parent = nullptr);

    QString disk() const { return m_recipe.disk; }
    void setDisk(const QString &v);
    QString filesystem() const { return m_recipe.filesystem; }
    void setFilesystem(const QString &v);
    bool btrfsSubvolumes() const { return m_recipe.btrfsSubvolumes; }
    void setBtrfsSubvolumes(bool v);
    QString encryptionType() const { return m_recipe.encryption.type; }
    void setEncryptionType(const QString &v);
    QString passphrase() const { return m_recipe.encryption.passphrase; }
    void setPassphrase(const QString &v);
    QString hostname() const { return m_recipe.hostname; }
    void setHostname(const QString &v);
    QString image() const { return m_recipe.image; }
    void setImage(const QString &v);

    bool hasTpm() const { return m_hasTpm; }
    QString productName() const { return m_productName; }
    QString log() const { return m_log; }
    QString logPath() const { return m_logPath; }
    bool installing() const { return m_process != nullptr; }
    bool installFinishedFlag() const { return m_finished; }
    int exitCode() const { return m_exitCode; }
    bool succeeded() const { return m_finished && m_exitCode == 0; }

    // Human-readable label for an encryption type, shared by the encryption
    // and confirm steps so they cannot drift apart.
    Q_INVOKABLE QString encryptionLabel(const QString &type) const;

    // Writes the recipe and launches fisherman. The ONLY thing that starts an
    // install — nothing on step activation does. Kept that way on purpose: the
    // screenshot harness walks every step, and must never install anything.
    Q_INVOKABLE void startInstall();

    // Screenshot/demo hook: fills the log and result so the progress and done
    // steps can be photographed. Runs no process and touches no disk.
    Q_INVOKABLE void loadDemoState(const QString &log, int exitCode);

Q_SIGNALS:
    void recipeChanged();
    void logChanged();
    void logPathChanged();
    void installingChanged();
    void installCompleted(int exitCode);

private:
    void openLogFile();
    void closeLogFile();
    void appendLine(const QString &line);
    void drainBuffer(const QString &prefix);
    void fail(const QString &message);

    Recipe m_recipe;
    QTemporaryDir m_recipeDir;
    QString m_recipePath;
    QString m_log;
    QFile *m_logFile = nullptr;
    QString m_logPath;
    QString m_buffer;
    QProcess *m_process = nullptr;
    bool m_finished = false;
    bool m_hasTpm = false;
    QString m_productName;
    int m_exitCode = 0;
};
