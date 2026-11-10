#pragma once

// The wizard's state and the fisherman backend, exposed to QML.
//
// The wizard's recipe, the privileged fisherman QProcess (the recipe goes to
// its stdin, `fisherman -`), and fisherman's answers: `probe --json` for the
// hardware and live media, `validate --json --partial` for the fields.

#include <QFile>
#include <QObject>
#if QT_CONFIG(process)
#include <QProcess>
#else
// Qt for WebAssembly builds without QProcess. The browser harness never
// starts an install, so the pointer only has to exist; it stays null.
class QProcess;
#endif
#include <QString>
#include <QTimer>
#include <qqmlintegration.h>

#include "branding.h"

#include <QVariantList>
#include <QVariantMap>
#include "imagecatalog.h"
#include "recipe.h"
#include "validate.h"

class InstallerController : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON

    Q_PROPERTY(QString disk READ disk WRITE setDisk NOTIFY recipeChanged)
    Q_PROPERTY(bool diskRemovable READ diskRemovable WRITE setDiskRemovable NOTIFY recipeChanged)
    Q_PROPERTY(QString filesystem READ filesystem WRITE setFilesystem NOTIFY recipeChanged)
    Q_PROPERTY(bool btrfsSubvolumes READ btrfsSubvolumes WRITE setBtrfsSubvolumes NOTIFY recipeChanged)
    Q_PROPERTY(QString encryptionType READ encryptionType WRITE setEncryptionType NOTIFY recipeChanged)
    Q_PROPERTY(QString passphrase READ passphrase WRITE setPassphrase NOTIFY recipeChanged)
    Q_PROPERTY(QString hostname READ hostname WRITE setHostname NOTIFY recipeChanged)
    Q_PROPERTY(QString image READ image WRITE setImage NOTIFY recipeChanged)
    // The image updates follow. The confirm step shows it when it is not
    // `image` (the offline NVIDIA case of shared/catalog/README.md).
    Q_PROPERTY(QString targetImgref READ targetImgref NOTIFY recipeChanged)
    // "product channel" of the selected catalog leaf, "" without one.
    Q_PROPERTY(QString imageLabel READ imageLabel NOTIFY catalogChanged)
    // The filesystems the user can pick: the selected leaf's `filesystems`,
    // else its one `filesystem`, else this frontend's own list. The disk
    // step shows a picker when there is more than one.
    Q_PROPERTY(QStringList filesystemChoices READ filesystemChoices NOTIFY catalogChanged)
    // The account the installed system gets (the recipe's `user` block, with
    // the groups of shared/account/groups.json). Required unless the image
    // creates its own first user (needs_user_creation: false in the
    // catalog): the wizard then skips the account step and the recipe omits
    // the block. True when no catalog has the image.
    Q_PROPERTY(QString username READ username WRITE setUsername NOTIFY recipeChanged)
    Q_PROPERTY(QString fullname READ fullname WRITE setFullname NOTIFY recipeChanged)
    Q_PROPERTY(QString userPassword READ userPassword WRITE setUserPassword NOTIFY recipeChanged)
    Q_PROPERTY(bool needsUserCreation READ needsUserCreation NOTIFY catalogChanged)

    // The image catalog (shared/catalog/README.md). Hidden on live media,
    // and empty when no manifest is installed.
    Q_PROPERTY(bool hasCatalog READ hasCatalog CONSTANT)
    Q_PROPERTY(QStringList catalogNames READ catalogNames NOTIFY catalogChanged)
    Q_PROPERTY(QStringList catalogImgrefs READ catalogImgrefs NOTIFY catalogChanged)
    Q_PROPERTY(QStringList catalogDescs READ catalogDescs NOTIFY catalogChanged)
    Q_PROPERTY(int catalogIndex READ catalogIndex NOTIFY catalogChanged)

    // fisherman's tpm.usable from `fisherman probe --json`
    // (shared/probe/README.md). TPM options are hidden, not disabled, when
    // false: offering them on a machine without one only fails later, at
    // install time. False when the probe failed.
    Q_PROPERTY(bool hasTpm READ hasTpm CONSTANT)
    // fisherman's system.unmet ("ram", "cpu", "uefi"), and the welcome
    // step's warning built from the requirements_* copy keys; empty when
    // every requirement is met or the probe failed. A warning, not a gate —
    // except the two blocking cases below, which mirror the GNOME cpu/ram
    // windows (continue anyway) and the unsupported window (power off).
    Q_PROPERTY(QStringList unmetRequirements READ unmetRequirements CONSTANT)
    Q_PROPERTY(QString requirementsWarning READ requirementsWarning CONSTANT)
    // True when the machine did not boot UEFI: like BootcUnsupportedWindow,
    // there is no continue path, only powering off.
    Q_PROPERTY(bool requirementsFatal READ requirementsFatal CONSTANT)
    // True when any requirement is unmet (ram, cpu or uefi).
    Q_PROPERTY(bool requirementsBlocking READ requirementsBlocking CONSTANT)
    // The user's explicit override for the non-fatal gates. Starts false:
    // an unmet CPU/RAM requirement holds the welcome step until it is set.
    Q_PROPERTY(bool continueAnyway READ continueAnyway WRITE setContinueAnyway NOTIFY continueAnywayChanged)
    // Every encryption type, in display order (Recipe::encryptionTypes()).
    // The encryption step repeats over it and hides the tpm2- ones without
    // a TPM; what each is called comes from encryptionLabel/Description.
    Q_PROPERTY(QStringList encryptionTypes READ encryptionTypes CONSTANT)

    // fisherman's probe: the host booted from live media (live.is_live), and
    // the booted image. On live media the recipe leaves `image` empty and
    // fisherman installs the running system.
    Q_PROPERTY(bool isLive READ isLive CONSTANT)
    Q_PROPERTY(QString liveImage READ liveImage CONSTANT)

    // Region & language preflight (the GNOME language/keyboard/timezone
    // steps, folded into the welcome step to keep the seven-module shape).
    // Wizard state, not recipe state: fisherman's Recipe has no such fields,
    // and the shared schema test pins the recipe to exactly those fields —
    // so these are shown back on the confirm screen, where GNOME shows them,
    // and never written to the recipe.
    Q_PROPERTY(QString language READ language WRITE setLanguage NOTIFY regionChanged)
    Q_PROPERTY(QString keyboardLayout READ keyboardLayout WRITE setKeyboardLayout NOTIFY regionChanged)
    Q_PROPERTY(QString timezone READ timezone WRITE setTimezone NOTIFY regionChanged)
    Q_PROPERTY(QStringList languageIds READ languageIds CONSTANT)
    Q_PROPERTY(QStringList languageNames READ languageNames CONSTANT)
    Q_PROPERTY(QStringList keyboardLayoutIds READ keyboardLayoutIds CONSTANT)
    Q_PROPERTY(QStringList keyboardLayoutNames READ keyboardLayoutNames CONSTANT)
    Q_PROPERTY(QStringList timezones READ timezones CONSTANT)

    // Network preflight (the GNOME conn_check step). `online` starts true and
    // is corrected by one background probe: failing closed would hold the
    // wizard on every machine whose firewall drops the probe. The welcome
    // step blocks only when the check has actually failed AND the install
    // needs the network (not live, selected image not already on disk).
    Q_PROPERTY(bool online READ online NOTIFY onlineChanged)
    Q_PROPERTY(bool onlineKnown READ onlineKnown NOTIFY onlineChanged)
    Q_PROPERTY(bool checkingOnline READ checkingOnline NOTIFY onlineChanged)
    Q_PROPERTY(bool needsNetwork READ needsNetwork NOTIFY catalogChanged)

    // The selected catalog leaf's `carousel` slides (fisherman's images.json,
    // shown by the GNOME tour step): title/description/image maps for the
    // done screen. Empty when the leaf names none.
    Q_PROPERTY(QVariantList tourSlides READ tourSlides NOTIFY catalogChanged)

    // fisherman's problems with the fields (`validate --json --partial`), in
    // the words of the copy key validate_<code>; empty when there is none or
    // the check could not run. The encryption step shows the passphrase
    // problem and holds Next on it; the account step does the same with the
    // username's; the confirm step shows the hostname's.
    Q_PROPERTY(QString hostnameProblem READ hostnameProblem NOTIFY problemsChanged)
    Q_PROPERTY(QString encryptionProblem READ encryptionProblem NOTIFY problemsChanged)
    Q_PROPERTY(QString usernameProblem READ usernameProblem NOTIFY problemsChanged)
    // The filesystem's, which includes a composefs image on a filesystem
    // without fs-verity (#287). The disk step shows it and holds Next.
    Q_PROPERTY(QString filesystemProblem READ filesystemProblem NOTIFY problemsChanged)
    // fisherman's answer for the recipe's locale, keyboard and time zone:
    // the first problem, or "".
    Q_PROPERTY(QString regionProblem READ regionProblem NOTIFY problemsChanged)
    // The recipe's `locale` for the picked language, for the confirm step.
    Q_PROPERTY(QString localeName READ localeName NOTIFY regionChanged)

    // The product name, resolved ONCE at startup from the branding contract
    // (src/branding.h: branding.json, then os-release, then neutral). Every
    // user-visible string reads this; nothing names a product. CONSTANT: the
    // files cannot change under a running installer.
    Q_PROPERTY(QString productName READ productName CONSTANT)
    // Theme icon name or safely encoded local URL, using the host path only
    // when sandboxed. Welcome and successful completion share this source.
    Q_PROPERTY(QString logoSource READ logoSource CONSTANT)
    // The branding contract's optional artwork (`assets.welcome_image`,
    // `assets.complete_image`), resolved with the same rules as the logo.
    // Empty when unset; the welcome and done steps then fall back to
    // logoSource and finally to a themed icon.
    Q_PROPERTY(QString welcomeImageSource READ welcomeImageSource CONSTANT)
    Q_PROPERTY(QString completeImageSource READ completeImageSource CONSTANT)
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
    // The install ended because it was cancelled: fisherman's exit code 130,
    // or any unsuccessful end after cancelInstall(). The done step then
    // shows the cancelled page, not the failure page (#299).
    Q_PROPERTY(bool cancelled READ cancelled NOTIFY installCompleted)

    // The key fisherman emits once, after TPM enrolment (#129). The
    // "recovery_key" branch in consumeProgress() used to format a log line
    // and keep nothing, so after the install there was nothing left to show.
    Q_PROPERTY(QString recoveryKey READ recoveryKey NOTIFY recoveryChanged)
    Q_PROPERTY(bool recoveryAck READ recoveryAck WRITE setRecoveryAck NOTIFY recoveryChanged)
    // Restart is held while an unacknowledged key is on screen: leaving the
    // done page is what ends the chance to read it.
    Q_PROPERTY(bool recoveryKeyPending READ recoveryKeyPending NOTIFY recoveryChanged)

public:
    explicit InstallerController(QObject *parent = nullptr);

    QString disk() const { return m_recipe.disk; }
    void setDisk(const QString &v);
    bool diskRemovable() const { return m_diskRemovable; }
    void setDiskRemovable(bool v)
    {
        if (m_diskRemovable == v)
            return;
        m_diskRemovable = v;
        Q_EMIT recipeChanged();
    }
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
    QString targetImgref() const { return m_recipe.targetImgref; }
    QString imageLabel() const;
    QStringList filesystemChoices() const { return m_filesystemChoices; }
    // This frontend's own list, for an image whose catalog leaf names none.
    static QStringList ownFilesystems();
    QString username() const { return m_recipe.user.username; }
    void setUsername(const QString &v);
    QString fullname() const { return m_recipe.user.fullname; }
    void setFullname(const QString &v);
    QString userPassword() const { return m_recipe.user.password; }
    void setUserPassword(const QString &v);

    // The assembled recipe, for tests: what startInstall() hands fisherman.
    // QML reads the individual properties above, never this.
    const Recipe &recipe() const { return m_recipe; }
    bool hasTpm() const { return m_hasTpm; }
    QStringList unmetRequirements() const { return m_unmet; }
    QString requirementsWarning() const;
    bool requirementsFatal() const { return m_unmet.contains(QStringLiteral("uefi")); }
    bool requirementsBlocking() const { return !m_unmet.isEmpty(); }
    bool continueAnyway() const { return m_continueAnyway; }
    void setContinueAnyway(bool v);
    bool needsUserCreation() const { return m_needsUser; }
    bool hasCatalog() const { return !m_catalog.leaves.isEmpty(); }
    QStringList catalogNames() const;
    QStringList catalogImgrefs() const;
    QStringList catalogDescs() const;
    int catalogIndex() const { return m_catalogIndex; }
    Q_INVOKABLE void selectCatalogImage(int index);
    QString language() const { return m_language; }
    void setLanguage(const QString &v);
    QString keyboardLayout() const { return m_keyboardLayout; }
    void setKeyboardLayout(const QString &v);
    QString timezone() const { return m_timezone; }
    void setTimezone(const QString &v);
    QStringList languageIds() const { return m_languageIds; }
    QStringList languageNames() const { return m_languageNames; }
    QStringList keyboardLayoutIds() const { return m_keyboardIds; }
    QStringList keyboardLayoutNames() const { return m_keyboardNames; }
    QStringList timezones() const { return m_timezones; }
    Q_INVOKABLE QString timezoneDisplay(const QString &ianaId) const;
    bool online() const { return m_online; }
    bool onlineKnown() const { return m_onlineKnown; }
    bool checkingOnline() const { return m_checkingOnline; }
    bool needsNetwork() const;
    Q_INVOKABLE void checkConnectivity();
    // Opens the desktop's own network settings on the host, best effort.
    Q_INVOKABLE void openNetworkSettings();
    QVariantList tourSlides() const { return m_tourSlides; }
    QStringList encryptionTypes() const { return Recipe::encryptionTypes(); }
    Q_INVOKABLE bool needsPassphrase(const QString &type) const { return Recipe::needsPassphrase(type); }
    Q_INVOKABLE bool needsTpm2(const QString &type) const { return Recipe::needsTpm2(type); }
    bool isLive() const { return m_recipe.liveMode; }
    QString liveImage() const { return m_liveImage; }
    QString hostnameProblem() const { return problemText(QStringLiteral("hostname")); }
    QString encryptionProblem() const { return problemText(QStringLiteral("encryption")); }
    QString usernameProblem() const { return problemText(QStringLiteral("user.username")); }
    QString filesystemProblem() const;
    QString regionProblem() const;
    QString localeName() const { return m_recipe.locale; }
    // The fields as a partial recipe for `validate --json --partial -`.
    QByteArray partialRecipe() const;
    // Takes in fisherman's answer (validate --json stdout). Public for tests.
    void applyValidateAnswer(const QByteArray &stdoutData);
    QString productName() const { return m_productName; }
    QString logoSource() const { return m_logoSource; }
    QString welcomeImageSource() const { return m_welcomeImageSource; }
    QString completeImageSource() const { return m_completeImageSource; }
    QVariantMap copy() const { return m_branding.copyAsVariantMap(); }
    QString storeUrl() const { return m_branding.storeUrl; }
    // A copy line with {name} and {disk} filled in.
    Q_INVOKABLE QString text(const QString &key, const QString &disk = QString()) const
    {
        return m_branding.text(key, {{QStringLiteral("disk"), disk.isEmpty() ? tr("the selected disk") : disk}});
    }
    // The done page's Restart: systemctl reboot on the host.
    Q_INVOKABLE void reboot();
    // Power off on the host (the unsupported-window path: flatpak-spawn
    // --host when sandboxed, the same hostCommand reboot() uses).
    Q_INVOKABLE void poweroff();
    // Copies the in-window install log to the clipboard: the file outlives
    // the window, but a failed install pasted into a bug report usually
    // starts from this button (the GNOME BootcDialogOutput copy action).
    Q_INVOKABLE void copyLogToClipboard();
    // Stops a running install. The progress step calls this only after the
    // user confirmed. SIGTERM to the wrapper's whole process group, SIGKILL
    // five seconds later if it is still there: fisherman runs as root and
    // cannot be signalled from here, it cancels when its parent dies
    // (fisherman#267).
    Q_INVOKABLE void cancelInstall();
    QString log() const { return m_log; }
    QString logPath() const { return m_logPath; }
    int installStep() const { return m_step; }
    int installTotalSteps() const { return m_totalSteps; }
    qreal installFraction() const { return m_fraction; }
    QString installStepName() const { return m_stepName; }
    bool installing() const { return m_process != nullptr; }
    bool installFinishedFlag() const { return m_finished; }
    int exitCode() const { return m_exitCode; }
    bool succeeded() const { return m_finished && m_exitCode == 0 && !m_cancelled; }
    bool cancelled() const { return m_finished && m_cancelled; }
    QString recoveryKey() const { return m_recoveryKey; }
    bool recoveryAck() const { return m_recoveryAck; }
    void setRecoveryAck(bool v);
    // A failed install enrolled nothing, and a non-TPM install was never
    // given a key, so neither is held: a user must not be asked to tick a
    // box about a key they do not have.
    bool recoveryKeyPending() const
    {
        return succeeded() && !m_recoveryKey.isEmpty() && !m_recoveryAck;
    }

    // What an encryption type is called: the branding copy keys
    // encryption_<type>_label and _description (shared/branding/README.md).
    // The encryption and confirm steps both read these, so they cannot
    // drift apart.
    Q_INVOKABLE QString encryptionLabel(const QString &type) const;
    Q_INVOKABLE QString encryptionDescription(const QString &type) const;

    // Writes the recipe and launches fisherman. The ONLY thing that starts an
    // install — nothing on step activation does. Kept that way on purpose: the
    // screenshot harness walks every step, and must never install anything.
    Q_INVOKABLE void startInstall();

    // Screenshot/demo hook: fills the log and result so the progress and done
    // steps can be photographed. Runs no process and touches no disk.
    Q_INVOKABLE void loadDemoState(const QString &log, int exitCode);

    // fisherman's output, one read at a time. The live QProcess path calls
    // these from readyReadStandardOutput/-Error and finished(); they are
    // public so the tests can interleave the two streams the way a pipe does.
    // Only stdout lines are parsed as progress events.
    void consumeStdout(const QByteArray &data);
    void consumeStderr(const QByteArray &data);
    // Emits whatever partial line is left in either stream.
    void flushStreams();
    // Starts `command` as the install, writes `recipeJson` to its stdin and
    // closes it. startInstall() calls this with fisherman.h's command; it is
    // public so the tests can run the cancel path against a stand-in.
    void launch(QStringList command, const QByteArray &recipeJson);
    // Blocks until the install process ends, at most `ms`. For tests, which
    // run without an event loop; true when no process is left.
    bool waitForInstall(int ms);

Q_SIGNALS:
    void recipeChanged();
    void catalogChanged();
    void continueAnywayChanged();
    void regionChanged();
    void onlineChanged();
    void logChanged();
    void logPathChanged();
    void installingChanged();
    void progressChanged();
    void recoveryChanged();
    void problemsChanged();
    void installCompleted(int exitCode);

private:
    void openLogFile();
    void closeLogFile();
    void appendLine(const QString &line, bool parse = true);
    // Parses one fisherman event and updates the progress properties.
    // Returns the text to show in the log pane: the event rendered for a
    // person, or the line unchanged when it is not an event.
    QString consumeProgress(const QString &line);
    // The label for a step: copy key step_<stepId>, else the step name.
    QString stepLabel(const QString &stepId, const QString &stepName) const;
    void resetProgress();
    void drainBuffer(QByteArray &buffer, const QString &prefix, bool parse);
    void fail(const QString &message);
    // A problem's line: the copy for its code, or fisherman's message.
    QString problemText(const QString &fieldPrefix) const;
    // Asks fisherman about the fields after a pause in the changes.
    void checkFields();
    void runValidate();
    // Everything a catalog leaf decides except the image itself.
    void applyLeaf(const imagecatalog::Leaf &leaf);
    void signalInstallGroup(int signal);

    Recipe m_recipe;
    bool m_diskRemovable = false;
    // The hostname the branding ships, so a catalog default_hostname only
    // applies when the user has not picked their own yet.
    QString m_defaultHostname;
    imagecatalog::Catalog m_catalog;
    int m_catalogIndex = -1;
    bool m_needsUser = true;
    bool m_hasNvidia = false;
    QStringList m_filesystemChoices;
    // The hostname this frontend last put in the recipe, so a new leaf's
    // default_hostname replaces it and a name the user typed stays.
    QString m_seededHostname;
    bool m_cancelRequested = false;
    bool m_cancelled = false;
    bool m_continueAnyway = false;
    QString m_liveImage;
    QStringList m_offlineImages;
    QString m_language;
    QString m_keyboardLayout;
    QString m_timezone;
    QStringList m_languageIds;
    QStringList m_languageNames;
    QStringList m_keyboardIds;
    QStringList m_keyboardNames;
    QStringList m_timezones;
    bool m_online = true;
    bool m_onlineKnown = false;
    bool m_checkingOnline = false;
    QVariantList m_tourSlides;
    QList<validate::Problem> m_problems;
    QTimer m_validateTimer;
    QProcess *m_validateProcess = nullptr;
    bool m_validateAgain = false;
    QString m_log;
    QFile *m_logFile = nullptr;
    QString m_logPath;
    // One partial line per stream; see consumeStdout().
    QByteArray m_stdoutBuffer;
    QByteArray m_stderrBuffer;
    QProcess *m_process = nullptr;
    bool m_finished = false;
    int m_step = 0;
    int m_totalSteps = 0;
    qreal m_fraction = 0.0;
    QString m_stepName;
    QString m_recoveryKey;
    bool m_recoveryAck = false;
    // Carried across lines so a substep can interpolate inside its step.
    int m_cumulativePct = 0;
    int m_weightPct = 0;
    // How far through the current step the bar is (0-1); never decreases
    // inside a step. m_postPullBase is m_stepFrac when the first post-pull
    // phase message arrived, or negative before that.
    double m_stepFrac = 0.0;
    double m_postPullBase = -1.0;
    bool m_hasTpm = false;
    QStringList m_unmet;
    QString m_productName;
    QString m_logoSource;
    QString m_welcomeImageSource;
    QString m_completeImageSource;
    branding::Branding m_branding;
    int m_exitCode = 0;
};
