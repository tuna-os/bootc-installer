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

#include "branding.h"

#include <QVariantMap>
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

    // The product name, resolved ONCE at startup from the branding contract
    // (src/branding.h: branding.json, then os-release, then neutral). Every
    // user-visible string reads this; nothing names a product. CONSTANT: the
    // files cannot change under a running installer.
    Q_PROPERTY(QString productName READ productName CONSTANT)
    // Flavour text from the branding contract (shared/branding copy keys),
    // {name} already filled in; {disk} through text(). CONSTANT like the name.
    Q_PROPERTY(QVariantMap copy READ copy CONSTANT)
    Q_PROPERTY(QString storeUrl READ storeUrl CONSTANT)

    Q_PROPERTY(QString log READ log NOTIFY logChanged)

    // Where the same log is being written on disk, empty when the file could
    // not be opened. The done step shows it: the in-window log dies with the
    // window, and a failed install is exactly when someone needs to reboot,
    // ask for help, or attach the output to a bug report.
    Q_PROPERTY(QString logPath READ logPath NOTIFY logPathChanged)

    // Install progress, from fisherman's newline-delimited JSON protocol
    // (shared/progress/README.md). KDE had no progress bar at all: the
    // step showed a BusyIndicator and a log pane for the whole install,
    // which docs/PARITY.md listed as gap #2.
    //
    // installFraction, not step/totalSteps: fisherman computes total_steps
    // from the recipe, and the weights are wildly unequal — "Installing OS"
    // alone is 87% of a cold install while five other steps are 0% — so a
    // bar advanced one-nth per step sits near empty for the whole visible
    // install and then jumps.
    Q_PROPERTY(int installStep READ installStep NOTIFY progressChanged)
    Q_PROPERTY(int installTotalSteps READ installTotalSteps NOTIFY progressChanged)
    Q_PROPERTY(qreal installFraction READ installFraction NOTIFY progressChanged)
    Q_PROPERTY(QString installStepName READ installStepName NOTIFY progressChanged)

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
    QVariantMap copy() const { return m_branding.copyAsVariantMap(); }
    QString storeUrl() const { return m_branding.storeUrl; }
    // A copy line with {name} and {disk} filled in.
    Q_INVOKABLE QString text(const QString &key, const QString &disk = QString()) const
    {
        return m_branding.text(key, {{QStringLiteral("disk"), disk.isEmpty() ? QStringLiteral("the selected disk") : disk}});
    }
    // The done page's Restart: systemctl reboot on the host.
    Q_INVOKABLE void reboot();
    QString log() const { return m_log; }
    QString logPath() const { return m_logPath; }
    int installStep() const { return m_step; }
    int installTotalSteps() const { return m_totalSteps; }
    qreal installFraction() const { return m_fraction; }
    QString installStepName() const { return m_stepName; }
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
    void progressChanged();
    void installCompleted(int exitCode);

private:
    void openLogFile();
    void closeLogFile();
    void appendLine(const QString &line);
    // Parses one fisherman event and updates the progress properties.
    // Returns the text to show in the log pane: the event rendered for a
    // person, or the line unchanged when it is not an event (fisherman's
    // stderr is interleaved into the same stream and is already readable).
    QString consumeProgress(const QString &line);
    void resetProgress();
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
    int m_step = 0;
    int m_totalSteps = 0;
    qreal m_fraction = 0.0;
    QString m_stepName;
    // Carried across lines so a substep can interpolate inside its step.
    int m_cumulativePct = 0;
    int m_weightPct = 0;
    bool m_hasTpm = false;
    QString m_productName;
    branding::Branding m_branding;
    int m_exitCode = 0;
};
