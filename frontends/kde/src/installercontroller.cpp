#include "installercontroller.h"
#include "probe.h"
#include "log.h"
#include "offline.h"
#include "fisherman.h"
#include "account.h"
#include "branding.h"
#include "redact.h"
#include "region.h"

#include <QClipboard>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMetaObject>
#include <QRegularExpression>
#include <QStandardPaths>

#include <csignal>
#include <thread>

InstallerController::InstallerController(QObject *parent)
    : QObject(parent)
{
    // One check at a time, after a pause in the changes.
    m_validateTimer.setSingleShot(true);
    m_validateTimer.setInterval(300);
    connect(&m_validateTimer, &QTimer::timeout, this, &InstallerController::runValidate);

    // TPM 2.0 and the minimum requirements are fisherman's answers
    // (`fisherman probe --json`, shared/probe/README.md), read once. The
    // disk step runs the probe again when it opens, for hotplugged disks.
    // A capture points BOOTC_INSTALLER_FAKE_PROBE at a fixture with a
    // usable TPM, so the TPM choices show on a runner without one.
    const probe::Result facts = probe::run();
    m_hasTpm = facts.tpmUsable;
    m_unmet = facts.unmet;
    // Live media is fisherman's answer (probe's `live`). This used to be a
    // `bootc status` of our own plus /run/ostree-live and /proc/cmdline,
    // read inside the Flatpak sandbox.
    m_recipe.liveMode = facts.isLive;
    m_liveImage = facts.liveImage;
    m_probeOutput = facts.raw;
    // Product identity per shared/branding/README.md: branding.json, then
    // os-release, then neutral. Nothing in this frontend names a product.
    m_branding = branding::resolve();
    m_productName = m_branding.name;
    m_logoSource = branding::resolveLogo(m_branding.logo, offline::inFlatpak()).source();
    m_welcomeImageSource = branding::resolveLogo(
        m_branding.assets.value(QStringLiteral("welcome_image")), offline::inFlatpak()).source();
    m_completeImageSource = branding::resolveLogo(
        m_branding.assets.value(QStringLiteral("complete_image")), offline::inFlatpak()).source();
    m_recipe.distroID = m_branding.id;
    m_recipe.hostname = m_branding.defaultHostname;
    m_defaultHostname = m_branding.defaultHostname;
    m_offlineImages = facts.offlineImages;

    // The ISO builder's recipe (shared/account/README.md): the first
    // account's groups, the shared default list unless it names
    // `user.groups`, and on live media the running image's layout.
    const QByteArray operatorRecipe =
        account::readOperatorRecipe(account::operatorRecipePath(offline::inFlatpak()));
    m_recipe.user.groups = account::groups(operatorRecipe);
    m_seededHostname = m_recipe.hostname;
    m_filesystemChoices = ownFilesystems();
    // The probe does not report the GPU yet (shared/catalog/README.md).
    // BOOTC_INSTALLER_SYS_ROOT is the test seam for a machine with one.
    m_hasNvidia = imagecatalog::hasNvidiaGpu(
        qEnvironmentVariable("BOOTC_INSTALLER_SYS_ROOT", QStringLiteral("/sys")));

    // The image catalog selects the recipe's image, its per-image fields and
    // whether the account step is needed (shared/catalog/README.md).
    m_catalog = imagecatalog::load();
    if (!m_recipe.liveMode) {
        // The branding's default_image, then the catalog's. With neither,
        // nothing is selected and the disk step holds Next: this frontend
        // never picks the first row.
        const int def = m_catalog.defaultIndex(m_branding.defaultImage);
        if (def >= 0)
            selectCatalogImage(def);
    } else {
        // Live media has no image page: the image stays empty and fisherman
        // installs the running system. The leaf of the image the probe
        // names (live.live_image) says whether an account is needed. The
        // fields fisherman cannot read from the image are that leaf's, with
        // the layout the ISO builder probed over them (liveLeaf): an ISO
        // ships no catalog, and a composefs-native image installed with
        // none of them fails in fisherman's "Installing OS" (tunaOS#4485). An
        // image the catalog does not have needs an account.
        m_needsUser = m_catalog.needsUserCreation(m_liveImage);
        m_recipe.userRequired = m_needsUser;
        applyLeaf(imagecatalog::liveLeaf(m_catalog.find(m_liveImage), operatorRecipe));
    }

    // Region & language preflight defaults: the live session's own values.
    m_language = region::systemLanguage();
    m_keyboardLayout = region::systemKeyboardLayout();
    m_timezone = region::systemTimezone();
    for (const region::Language &l : region::availableLanguages()) {
        m_languageIds << l.id;
        m_languageNames << l.display;
    }
    if (!m_languageIds.contains(m_language) && !m_languageIds.isEmpty())
        m_language = m_languageIds.first();
    for (const region::Keymap &k : region::availableKeyboardLayouts()) {
        m_keyboardIds << k.id;
        m_keyboardNames << k.description;
    }
    m_timezones = region::availableTimezones();
    if (!m_timezones.contains(m_timezone))
        m_timezone = QStringLiteral("UTC");
    // The recipe gets a region value only when the user picks one (#292):
    // a value nobody looked at must not replace the image's own.

    checkFields();
}

QByteArray InstallerController::partialRecipe() const
{
    QJsonObject enc{{QStringLiteral("type"), m_recipe.encryption.type}};
    if (Recipe::needsPassphrase(m_recipe.encryption.type))
        enc[QStringLiteral("passphrase")] = m_recipe.encryption.passphrase;
    const QJsonObject partial{
        {QStringLiteral("hostname"), m_recipe.hostname},
        {QStringLiteral("filesystem"), m_recipe.filesystem},
        // With the filesystem, so fisherman can say that a composefs image
        // needs fs-verity before Install is pressed (#287).
        {QStringLiteral("composeFsBackend"), m_recipe.composeFsBackend},
        {QStringLiteral("btrfsSubvolumes"), m_recipe.btrfsSubvolumes},
        {QStringLiteral("encryption"), enc},
        // The username only: fisherman has no rule for the full name or the
        // password, and the password has no business on a validate call.
        {QStringLiteral("user"), QJsonObject{{QStringLiteral("username"), m_recipe.user.username}}},
    };
    // The region keys exactly as the recipe has them, so fisherman's
    // locale, keyboard and time zone rules apply before Install.
    const QJsonObject recipe = m_recipe.toJson();
    QJsonObject withRegion = partial;
    for (const char *key : {"locale", "keyboard", "timezone", "experimental"}) {
        if (recipe.contains(QLatin1String(key)))
            withRegion.insert(QLatin1String(key), recipe.value(QLatin1String(key)));
    }
    // The install source of the confirm step (#267): fisherman's static
    // sourceReuse rules, before Install.
    if (reuseSelected()) {
        const QJsonObject fragment = sourcecheck::reuseFragment(installRecipe());
        for (auto it = fragment.begin(); it != fragment.end(); ++it)
            withRegion.insert(it.key(), it.value());
    }
    return QJsonDocument(withRegion).toJson(QJsonDocument::Compact);
}

void InstallerController::checkFields()
{
    m_validateTimer.start();
}

void InstallerController::runValidate()
{
#if QT_CONFIG(process)
    if (m_validateProcess) {
        m_validateAgain = true;
        return;
    }
    // The staged fisherman in a Flatpak; without it there is no check.
    if (!fisherman::staged().ok)
        return;
    QStringList argv = fisherman::commands(m_recipe.liveMode).unprivileged + validate::arguments();
    m_validateProcess = new QProcess(this);
    m_validateProcess->setProgram(argv.takeFirst());
    m_validateProcess->setArguments(argv);
    connect(m_validateProcess, &QProcess::finished, this, [this](int code, QProcess::ExitStatus status) {
        // 0 valid, 1 invalid; anything else means no answer.
        if (status == QProcess::NormalExit && (code == 0 || code == 1))
            applyValidateAnswer(m_validateProcess->readAllStandardOutput());
        else
            qCWarning(logInstaller) << "fisherman validate could not run, exit" << code;
        m_validateProcess->deleteLater();
        m_validateProcess = nullptr;
        if (m_validateAgain) {
            m_validateAgain = false;
            checkFields();
        }
    });
    connect(m_validateProcess, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error != QProcess::FailedToStart)
            return;
        qCWarning(logInstaller) << "fisherman validate could not start:" << m_validateProcess->errorString();
        m_validateProcess->deleteLater();
        m_validateProcess = nullptr;
    });
    m_validateProcess->start();
    // The partial recipe on stdin, never argv: the passphrase is in it.
    m_validateProcess->write(partialRecipe());
    m_validateProcess->closeWriteChannel();
#endif
}

void InstallerController::applyValidateAnswer(const QByteArray &stdoutData)
{
    const validate::Result answer = validate::parse(stdoutData);
    if (!answer.ok)
        qCWarning(logInstaller) << "fisherman validate:" << answer.error;
    m_problems = answer.ok ? answer.problems : QList<validate::Problem>{};
    Q_EMIT problemsChanged();
}

QString InstallerController::problemText(const QString &fieldPrefix) const
{
    for (const validate::Problem &p : m_problems) {
        if (p.field != fieldPrefix && !p.field.startsWith(fieldPrefix + QLatin1Char('.')))
            continue;
        const QString line = p.code.isEmpty() ? QString() : text(validate::copyKey(p));
        return line.isEmpty() ? p.message : line;
    }
    return {};
}

QString InstallerController::reuseProblem() const
{
    if (!reuseSelected())
        return {};
    for (const validate::Problem &p : m_problems) {
        if (!p.code.startsWith(QLatin1String("source_reuse_")))
            continue;
        const QString line = text(validate::copyKey(p));
        return line.isEmpty() ? p.message : line;
    }
    return {};
}

QString InstallerController::outcomeOf(int exitCode, bool crashed, bool cancelRequested)
{
    if (!crashed && exitCode == 0)
        return QStringLiteral("succeeded");
    if (!crashed && exitCode == 130)
        return QStringLiteral("cancelled");
    // After a confirmed cancel a signal is the cancel too: this installer
    // signalled the wrapper's group. Another exit code is fisherman's own
    // failure, which came before the cancel reached it.
    if (cancelRequested && (crashed || exitCode > 128))
        return QStringLiteral("cancelled");
    return QStringLiteral("failed");
}

QJsonObject InstallerController::installRecipe() const
{
    const QJsonObject recipe = m_recipe.toJson();
    return reuseSelected() ? sourcecheck::applyReuse(recipe, m_reuseSource) : recipe;
}

QJsonObject InstallerController::planRecipe() const
{
    // The image startInstall() fills in when none was chosen, so the plan
    // is of the recipe that Install writes.
    Recipe recipe = m_recipe;
    if (recipe.image.isEmpty() && !recipe.liveMode)
        recipe.image = m_branding.defaultImage;
    if (recipe.targetImgref.isEmpty())
        recipe.targetImgref = recipe.image;
    const QJsonObject json = recipe.toJson();
    return reuseSelected() ? sourcecheck::applyReuse(json, m_reuseSource) : json;
}

QJsonObject InstallerController::confirmedRecipe() const
{
    // plan::bind() leaves the recipe as it is without a plan, for a manual
    // layout, or for a plan of another disk.
    return plan::bind(installRecipe(), m_plan);
}

void InstallerController::requestPlan()
{
    const int generation = ++m_planGeneration;
    if (!m_plan.isEmpty()) {
        m_plan = QJsonObject();
        Q_EMIT planChanged();
    }
#if QT_CONFIG(process)
    if (m_planProcess) {
        // The answer of an earlier request binds nothing.
        m_planProcess->disconnect(this);
        m_planProcess->kill();
        m_planProcess->deleteLater();
        m_planProcess = nullptr;
    }
    // The staged fisherman in a Flatpak; without it there is no plan.
    if (!fisherman::staged().ok)
        return;
    QStringList argv = fisherman::commands(m_recipe.liveMode).unprivileged + plan::arguments();
    auto *process = new QProcess(this);
    m_planProcess = process;
    process->setProgram(argv.takeFirst());
    process->setArguments(argv);
    auto *timer = new QTimer(process);
    timer->setSingleShot(true);
    connect(timer, &QTimer::timeout, process, [process]() {
        process->setProperty("timedOut", true);
        process->kill();
    });
    auto done = [this, process, generation](const plan::Result &result) {
        if (process != m_planProcess)
            return;
        m_planProcess = nullptr;
        process->deleteLater();
        applyPlanReply(generation, result);
    };
    connect(process, &QProcess::finished, this, [process, done](int code, QProcess::ExitStatus status) {
        if (process->property("timedOut").toBool()) {
            done(plan::failed(QStringLiteral("fisherman plan gave no answer in %1 s").arg(plan::TIMEOUT_MS / 1000)));
            return;
        }
        done(plan::fromExit(status == QProcess::NormalExit, code, process->readAllStandardOutput(),
                            process->readAllStandardError()));
    });
    connect(process, &QProcess::errorOccurred, this, [process, done](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart)
            done(plan::failed(QStringLiteral("cannot run %1").arg(process->program())));
    });
    process->start();
    timer->start(plan::TIMEOUT_MS);
    // The recipe on stdin, never argv: it can hold the passphrase.
    process->write(QJsonDocument(planRecipe()).toJson(QJsonDocument::Compact));
    process->closeWriteChannel();
#else
    Q_UNUSED(generation);
#endif
}

void InstallerController::applyPlanReply(int generation, const plan::Result &result)
{
    if (generation != m_planGeneration)
        return;
    if (!result.ok) {
        // An older fisherman has no plan; the step works as before.
        qCInfo(logInstaller) << "no install plan:" << result.error;
        return;
    }
    if (!result.valid) {
        // The field checks name the problem; the install refuses it.
        qCInfo(logInstaller) << "fisherman plan refused the recipe:" << result.errorCodes.join(QStringLiteral(", "));
        return;
    }
    m_plan = result.plan;
    qCInfo(logInstaller) << "install plan:" << plan::destroys(m_plan).size() << "device(s) destroyed, disk identity"
                         << plan::diskIdentity(m_plan).keys();
    Q_EMIT planChanged();
}

QVariantList InstallerController::planRows() const
{
    QVariantList rows;
    for (const auto &[title, subtitle] : plan::rows(m_plan, m_branding))
        rows << QVariantMap{{QStringLiteral("title"), title}, {QStringLiteral("subtitle"), subtitle}};
    return rows;
}

void InstallerController::refreshReuse()
{
    const QJsonObject recipe = m_recipe.toJson();
    QString updateRef = recipe.value(QLatin1String("targetImgref")).toString();
    if (updateRef.isEmpty())
        updateRef = recipe.value(QLatin1String("image")).toString();
    const QJsonObject source = sourcecheck::reuseSource(!m_probeOutput.isEmpty(), m_probeOutput, updateRef);
    // A different item, or none, drops the pick: the download stays the default.
    if (source.isEmpty() || source.value(QLatin1String("digest")) != m_reuseSource.value(QLatin1String("digest")))
        m_reuseSelected = false;
    m_reuseSource = source;
    Q_EMIT reuseChanged();
    Q_EMIT catalogChanged();
}

void InstallerController::setReuseSelected(bool selected)
{
    selected = selected && reuseOffered();
    if (selected == m_reuseSelected)
        return;
    m_reuseSelected = selected;
    Q_EMIT reuseChanged();
    // needsNetwork: a copy downloads nothing.
    Q_EMIT catalogChanged();
    Q_EMIT problemsChanged();
    // The confirm step asks checkSource() again after the pick.
    checkFields();
}

QStringList InstallerController::reuseLines() const
{
    QStringList out;
    for (const auto &line : sourcecheck::sourceReuseLines(m_sourceReuse)) {
        const QString shown = m_branding.text(line.first, {{QStringLiteral("value"), line.second}});
        if (!shown.isEmpty())
            out << shown;
    }
    return out;
}

QStringList InstallerController::receiptLines() const
{
    QStringList out;
    for (const auto &line : sourcecheck::receiptLines(m_receipt)) {
        const QString shown = m_branding.text(line.first, {{QStringLiteral("value"), line.second}});
        if (!shown.isEmpty())
            out << shown;
    }
    return out;
}

QStringList InstallerController::failureLines() const
{
    QStringList out;
    for (const QString &key : sourcecheck::failureLines(QJsonObject::fromVariantMap(m_installError))) {
        const QString shown = m_branding.text(key);
        if (!shown.isEmpty())
            out << shown;
    }
    return out;
}

QString InstallerController::regionProblem() const
{
    for (const QString &field : {QStringLiteral("locale"), QStringLiteral("keyboard"), QStringLiteral("timezone")}) {
        const QString line = problemText(field);
        if (!line.isEmpty())
            return line;
    }
    return {};
}

QString InstallerController::filesystemProblem() const
{
    // fisherman reports a composefs image on a filesystem without fs-verity
    // against `composeFsBackend`; the user fixes it with the filesystem.
    const QString line = problemText(QStringLiteral("filesystem"));
    return line.isEmpty() ? problemText(QStringLiteral("composeFsBackend")) : line;
}

QStringList InstallerController::ownFilesystems()
{
    return {QStringLiteral("xfs"), QStringLiteral("ext4"), QStringLiteral("btrfs")};
}

QString InstallerController::imageLabel() const
{
    return m_catalogIndex >= 0 ? m_catalog.leaves.at(m_catalogIndex).label : QString();
}

QString InstallerController::requirementsWarning() const
{
    if (m_unmet.isEmpty())
        return {};
    // One copy key per fisherman `unmet` id; an id this build does not know
    // gets the title alone.
    static const QHash<QString, QString> keys{
        {QStringLiteral("ram"), QStringLiteral("requirements_ram")},
        {QStringLiteral("cpu"), QStringLiteral("requirements_cpu")},
        {QStringLiteral("uefi"), QStringLiteral("requirements_uefi")},
    };
    QStringList lines{text(QStringLiteral("requirements_title"))};
    for (const QString &item : m_unmet) {
        if (keys.contains(item))
            lines << text(keys.value(item));
    }
    lines.removeAll(QString());
    return lines.join(QLatin1Char('\n'));
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
    checkFields();
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
    // A type that takes no passphrase (needs_passphrase in
    // encryption-choices.json) must not keep one lying around in the recipe.
    if (!Recipe::needsPassphrase(v))
        m_recipe.encryption.passphrase.clear();
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setPassphrase(const QString &v)
{
    if (m_recipe.encryption.passphrase == v)
        return;
    m_recipe.encryption.passphrase = v;
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setHostname(const QString &v)
{
    if (m_recipe.hostname == v)
        return;
    m_recipe.hostname = v;
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setImage(const QString &v)
{
    if (m_recipe.image == v)
        return;
    m_recipe.image = v;
    // An image set by hand is also the image updates follow.
    m_recipe.targetImgref = v;
    Q_EMIT recipeChanged();
}

QStringList InstallerController::catalogNames() const
{
    QStringList out;
    // The breadcrumb, not the label: in a flat list of the whole catalog
    // "Atlas Stable" is not unique, the path from the root is.
    for (const imagecatalog::Leaf &leaf : m_catalog.leaves)
        out << leaf.breadcrumb;
    return out;
}

QStringList InstallerController::catalogImgrefs() const
{
    QStringList out;
    for (const imagecatalog::Leaf &leaf : m_catalog.leaves)
        out << leaf.imgref;
    return out;
}

QStringList InstallerController::catalogDescs() const
{
    QStringList out;
    for (const imagecatalog::Leaf &leaf : m_catalog.leaves)
        out << leaf.desc;
    return out;
}

void InstallerController::selectCatalogImage(int index)
{
    // Live media installs the running system: the catalog only informs the
    // per-image fields there (see the constructor), never the image.
    if (m_recipe.liveMode)
        return;
    if (index < 0 || index >= m_catalog.leaves.size() || index == m_catalogIndex)
        return;
    const imagecatalog::Leaf &leaf = m_catalog.leaves.at(index);
    m_catalogIndex = index;
    // The NVIDIA table of shared/catalog/README.md: with an NVIDIA GPU the
    // NVIDIA image is installed and followed.
    const imagecatalog::ImageChoice choice =
        imagecatalog::sourceAndTarget(leaf, m_hasNvidia, m_recipe.liveMode, m_offlineImages);
    m_recipe.image = choice.image;
    m_recipe.targetImgref = choice.targetImgref;
    m_needsUser = leaf.needsUserCreation;
    m_recipe.userRequired = leaf.needsUserCreation;
    m_tourSlides = leaf.carousel;
    applyLeaf(leaf);
    Q_EMIT catalogChanged();
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::applyLeaf(const imagecatalog::Leaf &leaf)
{
    // Each value is the new leaf's, an empty one included: nothing of the
    // leaf selected before it may stay in the recipe.
    m_recipe.bootloader = leaf.bootloader;
    m_recipe.composeFsBackend = leaf.composefs;
    m_recipe.imageType = leaf.imageType;
    m_recipe.flatpakVarPath = leaf.flatpakVarPath;
    m_recipe.extrasSet = leaf.hasExtras;
    m_recipe.extras = leaf.extras;
    // A list this frontend could read offline, or no key at all: it never
    // downloads a list and never sends one of its own (#296).
    m_recipe.flatpaksSet = leaf.hasFlatpaks;
    m_recipe.flatpaks = leaf.flatpaks;
    // The filesystem the image asks for (#287). A leaf that names none gets
    // this frontend's own list and default.
    m_filesystemChoices = leaf.filesystems.isEmpty() ? ownFilesystems() : leaf.filesystems;
    m_recipe.filesystem = leaf.filesystem.isEmpty() ? ownFilesystems().first() : leaf.filesystem;
    if (m_recipe.filesystem != QLatin1String("btrfs"))
        m_recipe.btrfsSubvolumes = false;
    // The leaf's default_hostname, else the branding's. A name the user
    // set is not replaced.
    if (m_recipe.hostname == m_seededHostname) {
        m_recipe.hostname = leaf.defaultHostname.isEmpty() ? m_defaultHostname : leaf.defaultHostname;
        m_seededHostname = m_recipe.hostname;
    }
}

void InstallerController::setContinueAnyway(bool v)
{
    if (m_continueAnyway == v)
        return;
    m_continueAnyway = v;
    Q_EMIT continueAnywayChanged();
}

void InstallerController::setLanguage(const QString &v)
{
    // A pick, the current value included, goes into the recipe.
    m_recipe.locale = region::localeName(v);
    m_language = v;
    Q_EMIT regionChanged();
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setKeyboardLayout(const QString &v)
{
    // A pick, the current value included, goes into the recipe.
    m_recipe.keyboardLayout = v;
    m_keyboardLayout = v;
    Q_EMIT regionChanged();
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setTimezone(const QString &v)
{
    // A pick, the current value included, goes into the recipe.
    m_recipe.timezone = v;
    m_timezone = v;
    Q_EMIT regionChanged();
    Q_EMIT recipeChanged();
    checkFields();
}

QString InstallerController::timezoneDisplay(const QString &ianaId) const
{
    return region::timezoneDisplay(ianaId);
}

bool InstallerController::needsNetwork() const
{
    // Live media installs the running system; an image already in the host's
    // offline stores needs no download. Mirrors conn_check.py's skip.
    return !m_recipe.liveMode && !m_offlineImages.contains(m_recipe.image) && !reuseSelected();
}

void InstallerController::checkConnectivity()
{
    if (m_checkingOnline)
        return;
    m_checkingOnline = true;
    Q_EMIT onlineChanged();
    // The registry the selected image comes from is the host that matters;
    // the shared targets follow it (#301).
    // shared/network/targets.json has the order, the timeout and the
    // variables that turn the check off.
    const QString image = m_recipe.image.isEmpty() ? m_branding.defaultImage : m_recipe.image;
    const QList<region::Target> targets = region::connectivityTargets(image);
    const bool skipped = region::connectivityCheckSkipped();
    std::thread([this, targets, skipped]() {
        const bool ok = skipped || region::networkReachable(targets);
        QMetaObject::invokeMethod(
            this,
            [this, ok]() {
                m_checkingOnline = false;
                m_online = ok;
                m_onlineKnown = true;
                Q_EMIT onlineChanged();
            },
            Qt::QueuedConnection);
    }).detach();
}

void InstallerController::checkSource()
{
    const int generation = ++m_sourceGeneration;
    const sourcecheck::Request req = sourcecheck::fromRecipe(installRecipe(), m_recipe.liveMode);
    const QStringList args = sourcecheck::probeArguments(req);
    m_sourceCheck = QJsonObject();
    m_bootcStore = QJsonObject();
    m_sourceVisible = !args.isEmpty();
    Q_EMIT sourceCheckChanged();
    if (args.isEmpty())
        return;
    // The probe gets the image references only; the recipe stays here.
    std::thread([this, generation, req, args]() {
        QByteArray out;
        const bool ok = probe::runOutput(args, &out);
        QMetaObject::invokeMethod(
            this, [this, generation, req, ok, out]() { applySourceReply(generation, req, ok, out); },
            Qt::QueuedConnection);
    }).detach();
}

void InstallerController::applySourceReply(int generation, const sourcecheck::Request &req, bool ok,
                                           const QByteArray &probeOutput)
{
    if (generation != m_sourceGeneration)
        return;
    const QJsonObject view = sourcecheck::check(ok, probeOutput, req);
    if (view.value(QLatin1String("state")).toString() == QLatin1String("stale"))
        return;
    m_sourceCheck = view;
    m_bootcStore = sourcecheck::bootcStore(ok, probeOutput);
    Q_EMIT sourceCheckChanged();
}

QVariantList InstallerController::sourceRows() const
{
    auto row = [](const QString &title, const QString &subtitle = QString()) {
        return QVariantMap{{QStringLiteral("title"), title}, {QStringLiteral("subtitle"), subtitle}};
    };
    auto valueLine = [this](const QString &key, const QString &value) {
        return m_branding.text(key, {{QStringLiteral("value"), value}});
    };
    QVariantList rows;
    if (m_sourceCheck.isEmpty()) {
        rows << row(text(QStringLiteral("source_check_") + QStringLiteral("checking")));
        return rows;
    }
    const QStringList identities{QStringLiteral("install_from"), QStringLiteral("update_ref"),
                                 QStringLiteral("live_host_image")};
    const QStringList keys{reuseSelected() ? QStringLiteral("source_reuse_install_from")
                                           : QStringLiteral("source_install_from"),
                           QStringLiteral("source_update_ref"), QStringLiteral("source_live_host")};
    for (int i = 0; i < identities.size(); ++i) {
        const QString value = m_sourceCheck.value(identities.at(i)).toString();
        if (!value.isEmpty())
            rows << row(valueLine(keys.at(i), value));
    }
    rows << row(text(QStringLiteral("source_check_") + m_sourceCheck.value(QLatin1String("state")).toString()),
                text(m_sourceCheck.value(QLatin1String("reason_key")).toString()));
    for (const QJsonValue &line : m_sourceCheck.value(QLatin1String("defaults")).toArray()) {
        const QJsonObject d = line.toObject();
        rows << row(valueLine(d.value(QLatin1String("key")).toString(), d.value(QLatin1String("value")).toString()));
    }
    if (m_bootcStore.value(QLatin1String("state")).toString() == QLatin1String("listed")) {
        rows << row(text(QStringLiteral("bootc_store_listed")));
        for (const QJsonValue &entry : m_bootcStore.value(QLatin1String("items")).toArray()) {
            const QJsonObject item = entry.toObject();
            rows << row(item.value(QLatin1String("ref")).toString(),
                        text(QStringLiteral("bootc_store_kind_") + item.value(QLatin1String("kind")).toString()));
        }
    }
    return rows;
}

void InstallerController::openNetworkSettings()
{
    QStringList argv = offline::hostCommand(region::networkSettingsCommand());
    const QString program = argv.takeFirst();
#if QT_CONFIG(process)
    QProcess::startDetached(program, argv);
#else
    qCWarning(logInstaller) << "this build cannot start processes, not running" << program;
#endif
}

void InstallerController::poweroff()
{
    // Same host path as the install and the reboot: flatpak-spawn --host
    // when sandboxed. Mirrors dialog_poweroff.py's host systemctl call.
    QStringList argv = offline::hostCommand({QStringLiteral("systemctl"), QStringLiteral("poweroff")});
    const QString program = argv.takeFirst();
#if QT_CONFIG(process)
    QProcess::startDetached(program, argv);
#else
    qCWarning(logInstaller) << "this build cannot start processes, not running" << program;
#endif
}

void InstallerController::copyLogToClipboard()
{
    QClipboard *clipboard = QGuiApplication::clipboard();
    if (!clipboard) {
        qCWarning(logInstaller) << "no clipboard: cannot copy the install log";
        return;
    }
    clipboard->setText(logForSharing());
}

QString InstallerController::logForSharing() const
{
    return redact::recoveryKey(m_log, m_recoveryKey);
}

void InstallerController::cancelInstall()
{
#if QT_CONFIG(process)
    // Nothing running, or already asked: there is nothing more to signal.
    if (!m_process || m_cancelRequested)
        return;
    m_cancelRequested = true;
    appendLine(tr("Cancelling installation..."), false);
    signalInstallGroup(SIGTERM);
    QTimer::singleShot(5000, this, [this]() {
        if (m_process)
            signalInstallGroup(SIGKILL);
    });
#endif
}

void InstallerController::signalInstallGroup(int signal)
{
#if QT_CONFIG(process)
#ifdef Q_OS_UNIX
    // launch() made the wrapper the leader of its own process group, so
    // this reaches the bash, the pkexec or sudo and flatpak-spawn under it,
    // and never this installer. The wrapper's pid alone left its children
    // running (#299).
    const qint64 pid = m_process->processId();
    if (pid > 0 && ::killpg(static_cast<pid_t>(pid), signal) == 0)
        return;
#endif
    if (signal == SIGKILL)
        m_process->kill();
    else
        m_process->terminate();
#else
    Q_UNUSED(signal);
#endif
}

void InstallerController::setUsername(const QString &v)
{
    if (m_recipe.user.username == v)
        return;
    m_recipe.user.username = v;
    Q_EMIT recipeChanged();
    checkFields();
}

void InstallerController::setFullname(const QString &v)
{
    if (m_recipe.user.fullname == v)
        return;
    m_recipe.user.fullname = v;
    Q_EMIT recipeChanged();
}

void InstallerController::setUserPassword(const QString &v)
{
    if (m_recipe.user.password == v)
        return;
    m_recipe.user.password = v;
    Q_EMIT recipeChanged();
}

// The copy key for an encryption type; fisherman reads "" as "none".
static QString encryptionKey(const QString &type, const char *suffix)
{
    const QString id = type.isEmpty() ? QStringLiteral("none") : type;
    return QStringLiteral("encryption_") + QString(id).replace(QLatin1Char('-'), QLatin1Char('_'))
        + QLatin1String(suffix);
}

QString InstallerController::encryptionLabel(const QString &type) const
{
    return text(encryptionKey(type, "_label"));
}

QString InstallerController::encryptionDescription(const QString &type) const
{
    return text(encryptionKey(type, "_description"));
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
    // fisherman's output is not expected to contain the passphrase, and
    // appendLine() removes the recovery key, but this file records a
    // privileged install: keep it owner-only rather than trusting the umask.
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
// The step-name table: the fallback label for a step event without a
// step_id, from a fisherman older than tuna-os/fisherman#270. A step_id is
// labelled by the copy key step_<id> instead (stepLabel below); these labels
// match those keys' defaults.
static QString friendlyStep(const QString &name, const QString &product)
{
    static const QHash<QString, const char *> labels = {
        {QStringLiteral("Preparing disk"), QT_TRANSLATE_NOOP("InstallerController", "Checking your drive…")},
        {QStringLiteral("Partitioning disk"), QT_TRANSLATE_NOOP("InstallerController", "Setting up your drive…")},
        {QStringLiteral("Formatting EFI partition"), QT_TRANSLATE_NOOP("InstallerController", "Preparing the boot system…")},
        {QStringLiteral("Setting up disk encryption"), QT_TRANSLATE_NOOP("InstallerController", "Securing your drive…")},
        {QStringLiteral("Formatting root filesystem"), QT_TRANSLATE_NOOP("InstallerController", "Formatting your drive…")},
        {QStringLiteral("Mounting filesystem"), QT_TRANSLATE_NOOP("InstallerController", "Almost ready…")},
        {QStringLiteral("Formatting data disk (/var)"), QT_TRANSLATE_NOOP("InstallerController", "Preparing data storage…")},
        // The one label that names the product. It must say what THIS build
        // installs; nothing here may name a distro (CLAUDE.md).
        {QStringLiteral("Installing OS"), QT_TRANSLATE_NOOP("InstallerController", "Installing %1…")},
        {QStringLiteral("Enrolling TPM2 auto-unlock"), QT_TRANSLATE_NOOP("InstallerController", "Setting up auto-unlock…")},
        {QStringLiteral("Copying system Flatpaks"), QT_TRANSLATE_NOOP("InstallerController", "Installing your apps…")},
        {QStringLiteral("Configuring installed system"), QT_TRANSLATE_NOOP("InstallerController", "Configuring your system…")},
        {QStringLiteral("Finalizing installation"), QT_TRANSLATE_NOOP("InstallerController", "Finishing up…")},
    };
    const char *source = labels.value(name, nullptr);
    if (!source)
        return name;
    const QString label = InstallerController::tr(source);
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
    m_installError.clear();
    m_receipt = QJsonValue();
    Q_EMIT receiptChanged();
    m_sourceReuse = QJsonValue();
    Q_EMIT sourceReuseChanged();
    m_recoveryAck = false;
    Q_EMIT recoveryChanged();
    m_cumulativePct = 0;
    m_weightPct = 0;
    m_stepFrac = 0.0;
    m_postPullBase = -1.0;
    Q_EMIT progressChanged();
}

// Share of a step's weight the layer pull covers; the rest is for the
// export, deploy and bootloader phases after it, which have no counter.
static constexpr double kPullShare = 0.6;

// Bar positions for the silent phases after the pull, as a share of what is
// left of the step, matched as message prefixes. Without these an offline
// install sat at 1% through ten minutes of export and deploy (#115). Same
// table and semantics as shared/progress/progress_parser.py; the numbers are
// pinned by shared/progress/fraction-cases.json.
static double phaseMilestone(const QString &message)
{
    static const struct {
        const char *prefix;
        double share;
    } milestones[] = {
        {"Exporting image to OCI layout", 0.05},
        {"OCI export complete", 0.30},
        {"Using ", 0.32},
        {"Initializing ostree layout", 0.35},
        {"Writing ", 0.35},
        {"Deploying image", 0.35},
        {"OS deployed, installing bootloader", 0.90},
        {"Detected bootloader", 0.92},
        {"Installing bootloader", 0.92},
        {"Configuring EFI boot entry", 0.95},
        {"Configuring GRUB", 0.95},
        {"Configuring SELinux", 0.95},
        {"Generating initramfs", 0.95},
        {"bootc installation complete", 1.0},
    };
    for (const auto &m : milestones) {
        if (message.startsWith(QLatin1String(m.prefix)))
            return m.share;
    }
    return -1.0;
}

// The label for a step: the branding copy line step_<step_id>
// (shared/branding/README.md, "Install steps"), so a product can rebrand it.
// An event without a step_id, or an id the copy has no line for, falls back
// to the step-name table and then to fisherman's raw step_name.
QString InstallerController::stepLabel(const QString &stepId, const QString &stepName) const
{
    if (!stepId.isEmpty()) {
        const QString label = text(QStringLiteral("step_") + stepId);
        if (!label.isEmpty())
            return label;
    }
    return friendlyStep(stepName, m_productName);
}

// fisherman's own bar (overall_pct, 0-100) on step, substep and complete
// events since tuna-os/fisherman#270. It is authoritative: when the event
// carries it, it replaces whatever the derivation in consumeProgress()
// computed. Clamped to 0-1 and never below the bar before this event.
// Returns false for an event without it (an older fisherman).
static bool applyOverallPct(const QJsonObject &event, qreal before, qreal &fraction)
{
    const QJsonValue v = event.value(QStringLiteral("overall_pct"));
    if (!v.isDouble())
        return false;
    fraction = qMax(before, qBound(0.0, v.toDouble() / 100.0, 1.0));
    return true;
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
    const qreal before = m_fraction;

    if (type == QLatin1String("step")) {
        const int step = event.value(QStringLiteral("step")).toInt();
        const QString name = event.value(QStringLiteral("step_name")).toString();
        // A repeated or earlier step is ignored, as in the canonical parser:
        // it must not reset the bar.
        if (m_step > 0 && step <= m_step) {
            return QStringLiteral("[%1/%2] %3")
                .arg(step)
                .arg(event.value(QStringLiteral("total_steps")).toInt())
                .arg(name);
        }
        m_step = step;
        m_totalSteps = event.value(QStringLiteral("total_steps")).toInt();
        m_stepFrac = 0.0;
        m_postPullBase = -1.0;
        m_cumulativePct = event.value(QStringLiteral("cumulative_pct")).toInt();
        m_weightPct = event.value(QStringLiteral("weight_pct")).toInt();
        // The derivation, the fallback when the event has no overall_pct.
        m_fraction = m_cumulativePct / 100.0;
        applyOverallPct(event, before, m_fraction);
        m_stepName = stepLabel(event.value(QStringLiteral("step_id")).toString(), name);
        Q_EMIT progressChanged();
        // copyCancel: once a step has started, the disk changes.
        if (!m_sourceReuse.isNull())
            Q_EMIT sourceReuseChanged();
        return QStringLiteral("[%1/%2] %3").arg(m_step).arg(m_totalSteps).arg(name);
    }
    if (type == QLatin1String("substep") || type == QLatin1String("info")) {
        const QString message = event.value(QStringLiteral("message")).toString();
        if (type == QLatin1String("substep") && m_weightPct > 0) {
            // The layer pull covers the first kPullShare of the step; the
            // named phases after it cover the rest.
            static const QRegularExpression layers(
                QStringLiteral("^Pulling image: layer (\\d+)/(\\d+)"));
            double stepFrac = -1.0;
            const QRegularExpressionMatch m = layers.match(message);
            if (m.hasMatch()) {
                const double done = m.captured(1).toDouble();
                const double total = m.captured(2).toDouble();
                if (total > 0)
                    stepFrac = qMin(done / total, 1.0) * kPullShare;
            } else {
                const double share = phaseMilestone(message);
                if (share >= 0) {
                    if (m_postPullBase < 0)
                        m_postPullBase = m_stepFrac;
                    stepFrac = m_postPullBase + share * (1.0 - m_postPullBase);
                }
            }
            if (stepFrac >= 0) {
                // Never move backwards: a retried pull restarts its count.
                m_stepFrac = qMax(m_stepFrac, stepFrac);
                m_fraction = qMin((m_cumulativePct + m_stepFrac * m_weightPct) / 100.0, 1.0);
            }
        }
        if (type == QLatin1String("substep"))
            applyOverallPct(event, before, m_fraction);
        if (m_fraction != before)
            Q_EMIT progressChanged();
        return message.isEmpty() ? QString() : QStringLiteral("  ") + message;
    }
    if (type == QLatin1String("complete")) {
        // cumulative_pct only ever reaches 99; `complete` fills the bar.
        m_fraction = 1.0;
        Q_EMIT progressChanged();
        const QString message = event.value(QStringLiteral("message")).toString();
        return message.isEmpty() ? tr("Installation complete") : message;
    }
    if (type == QLatin1String("error")) {
        // The last one is kept; it does not move the bar.
        m_installError = sourcecheck::errorOf(event).toVariantMap();
        return tr("ERROR: %1").arg(event.value(QStringLiteral("message")).toString());
    }
    if (type == QLatin1String("source_reuse")) {
        // The copy of this computer's system before the first step (#267).
        // It moves no bar: the bar stays indeterminate until the first step.
        m_sourceReuse = sourcecheck::sourceReuseOf(event, m_sourceReuse);
        Q_EMIT sourceReuseChanged();
        const QString code = event.value(QStringLiteral("code")).toString();
        return tr("Source reuse: %1").arg(event.value(QStringLiteral("phase")).toString())
            + (code.isEmpty() ? QString() : QStringLiteral(" (%1)").arg(code));
    }
    if (type == QLatin1String("receipt")) {
        // What the install did with the installation receipt (#269). It
        // moves no bar and decides no outcome; the done page reads it.
        m_receipt = sourcecheck::receiptOf(event);
        Q_EMIT receiptChanged();
        const QJsonObject r = m_receipt.toObject();
        return tr("Installation receipt: %1").arg(r.value(QLatin1String("state")).toString());
    }
    if (type == QLatin1String("recovery_key")) {
        // Kept in memory for the done page, which holds Restart until the
        // user says that the key is saved (#129). The log pane shows it to
        // the same user on the same screen. It goes no further: the log
        // file and the clipboard copy get the redacted form (appendLine,
        // logForSharing), because a log is what a user attaches to a bug
        // report (#337).
        m_recoveryKey = event.value(QStringLiteral("key")).toString();
        Q_EMIT recoveryChanged();
        return tr("Recovery key: %1").arg(m_recoveryKey);
    }
    return QString();
}

void InstallerController::appendLine(const QString &line, bool parse)
{
    // The log PANE shows the event rendered for a person; the log FILE keeps
    // the raw protocol, because that is what gets attached to a bug report.
    // Only stdout carries the protocol: stderr is shown as it is. For that
    // same reason the file never holds the recovery key (#337): the event
    // type stays, the key's value does not.
    const QString shown = parse ? consumeProgress(line) : line;
    if (!shown.isEmpty()) {
        m_log += shown;
        if (!shown.endsWith(QLatin1Char('\n')))
            m_log += QLatin1Char('\n');
    }

    if (m_logFile) {
        // After consumeProgress(), so the key of this very event is known.
        const QString kept = redact::recoveryKey(line, m_recoveryKey);
        m_logFile->write(kept.toUtf8());
        if (!kept.endsWith(QLatin1Char('\n')))
            m_logFile->write("\n");
        // Flushed per line: the interesting case is the one where the machine
        // is about to be rebooted or powered off by hand.
        m_logFile->flush();
    }

    Q_EMIT logChanged();
}

// stdout and stderr used to be appended to ONE buffer. A stdout JSON event
// that arrived in two reads, with a stderr chunk in between, came out as two
// broken lines: the head of the event glued to the stderr text (and labelled
// stderr), then the tail of the event with no leading '{' — so the progress
// event was lost. Each stream now keeps its own partial line. Buffers hold
// bytes, not text, so a UTF-8 sequence split across reads is decoded whole.
void InstallerController::consumeStdout(const QByteArray &data)
{
    m_stdoutBuffer += data;
    drainBuffer(m_stdoutBuffer, {}, true);
}

void InstallerController::consumeStderr(const QByteArray &data)
{
    m_stderrBuffer += data;
    drainBuffer(m_stderrBuffer, QStringLiteral("[stderr] "), false);
}

void InstallerController::flushStreams()
{
    if (!m_stdoutBuffer.isEmpty())
        appendLine(QString::fromUtf8(m_stdoutBuffer), true);
    if (!m_stderrBuffer.isEmpty())
        appendLine(QStringLiteral("[stderr] ") + QString::fromUtf8(m_stderrBuffer), false);
    m_stdoutBuffer.clear();
    m_stderrBuffer.clear();
}

void InstallerController::drainBuffer(QByteArray &buffer, const QString &prefix, bool parse)
{
    qsizetype nl;
    while ((nl = buffer.indexOf('\n')) >= 0) {
        appendLine(prefix + QString::fromUtf8(buffer.left(nl)), parse);
        buffer.remove(0, nl + 1);
    }
}

void InstallerController::fail(const QString &message)
{
    qCWarning(logInstaller) << "install failed:" << message;
    appendLine(QLatin1Char('\n') + tr("ERROR: %1").arg(message), false);
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
    // 130 is fisherman's "cancelled", as on the live path.
    m_cancelled = exitCode == 130;
    Q_EMIT logChanged();
    Q_EMIT installCompleted(exitCode);
}

void InstallerController::startInstall()
{
    if (m_process)
        return;

    // Not live media and nothing chosen: the branding's default image. On
    // live media the image stays empty and fisherman installs the running
    // system; it rejects an empty image anywhere else (image_required). No
    // additionalImageStores: fisherman exposes the host's offline stores.
    if (m_recipe.image.isEmpty() && !m_recipe.liveMode)
        m_recipe.image = m_branding.defaultImage;
    // targetImgref is always in the recipe of a named image.
    if (m_recipe.targetImgref.isEmpty())
        m_recipe.targetImgref = m_recipe.image;

    m_log.clear();
    m_stdoutBuffer.clear();
    m_stderrBuffer.clear();
    m_finished = false;
    m_cancelRequested = false;
    m_cancelled = false;
    Q_EMIT logChanged();

    // Before the recipe is written, so the failures below are logged too.
    openLogFile();
    resetProgress();
    appendLine(tr("Starting installation..."), false);

    // The recipe can hold a LUKS passphrase. It goes to fisherman's stdin
    // (`fisherman -`, tuna-os/fisherman#276) and never to a file: this used
    // to be a 0600 file in a QTemporaryDir, handed to root by path.
    // Bound to the disk of the confirm step's plan (`diskIdentity`): fisherman
    // refuses the install if another device is now at that path
    // (disk_identity_mismatch, tuna-os/fisherman#371).
    const QByteArray recipeJson = QJsonDocument(confirmedRecipe()).toJson(QJsonDocument::Compact);

    // In a Flatpak fisherman is the staged copy the host verified
    // (fisherman.h). Without it nothing may run as root.
    const fisherman::Staging &staging = fisherman::staged();
    if (!staging.ok) {
        fail(tr("Could not prepare fisherman: %1").arg(staging.error));
        return;
    }
    launch(fisherman::commands(m_recipe.liveMode).install, recipeJson);
}

void InstallerController::launch(QStringList cmd, const QByteArray &recipeJson)
{
#if !QT_CONFIG(process)
    // Qt for WebAssembly: there is no process to start. Only the browser
    // harness builds this, and nothing there presses Install; if something
    // ever does, it gets the ordinary failure path rather than a silent hang.
    Q_UNUSED(cmd);
    Q_UNUSED(recipeJson);
    fail(tr("This build cannot start fisherman"));
#else
    if (m_process || cmd.isEmpty())
        return;
    m_process = new QProcess(this);
    m_process->setProgram(cmd.takeFirst());
    m_process->setArguments(cmd);
    // Its own process group: the cancel contract is "kill your wrapper's
    // group", which cancelInstall() does.
    offline::startInOwnProcessGroup(*m_process);

    // Which escalation path was taken (pkexec, or sudo on live media) is
    // the first thing anyone reading a failed install needs to know.
    appendLine(tr("Running: %1 %2")
                   .arg(m_process->program(), m_process->arguments().join(QLatin1Char(' '))),
               false);

    // Without this, a fisherman that never starts — no pkexec in the sandbox,
    // the polkit agent missing, the binary not installed — emitted no
    // finished() either. The wizard sat on the progress page with a spinner
    // and "Starting installation..." forever, saying nothing.
    connect(m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        // Every other error is followed by finished(), which reports it below.
        if (error != QProcess::FailedToStart)
            return;
        const QString message = tr("Could not start %1: %2")
                                    .arg(m_process->program(), m_process->errorString());
        m_process->deleteLater();
        m_process = nullptr;
        Q_EMIT installingChanged();
        fail(message);
    });

    connect(m_process, &QProcess::readyReadStandardOutput, this, [this]() {
        consumeStdout(m_process->readAllStandardOutput());
    });
    connect(m_process, &QProcess::readyReadStandardError, this, [this]() {
        consumeStderr(m_process->readAllStandardError());
    });
    connect(m_process, &QProcess::finished, this,
            [this](int exitCode, QProcess::ExitStatus status) {
        flushStreams();

        const bool crashed = status == QProcess::CrashExit;
        // Cancelled: fisherman's own exit code for it (130), or any end but
        // success after the user asked to stop. Killing the wrapper's group
        // ends it with a signal, which is not a crash to report (#299).
        const QString outcome = outcomeOf(exitCode, crashed, m_cancelRequested);
        if (outcome == QLatin1String("cancelled")) {
            m_cancelled = true;
            m_exitCode = 130;
            qCInfo(logInstaller) << "the install was cancelled";
            appendLine(QLatin1Char('\n') + tr("Installation cancelled."), false);
        } else if (crashed) {
            qCWarning(logInstaller) << "fisherman crashed";
            appendLine(QLatin1Char('\n') + tr("ERROR: fisherman crashed"), false);
            m_exitCode = 1;
        } else {
            m_exitCode = exitCode;
            if (exitCode != 0)
                qCWarning(logInstaller) << "fisherman exited with" << exitCode;
            appendLine(QLatin1Char('\n')
                           + (exitCode == 0 ? tr("✓ Installation complete!")
                                            : tr("✗ Installation failed (exit code %1)").arg(exitCode)),
                       false);
        }
        if (!m_logPath.isEmpty())
            appendLine(tr("Log: %1").arg(m_logPath), false);
        closeLogFile();
        m_finished = true;
        m_process->deleteLater();
        m_process = nullptr;
        Q_EMIT installingChanged();
        Q_EMIT installCompleted(m_exitCode);
    });

    m_process->start();
    // Buffered until the process starts, then written; closing the channel
    // is the EOF fisherman reads to.
    m_process->write(recipeJson);
    m_process->closeWriteChannel();
    Q_EMIT installingChanged();
#endif
}

bool InstallerController::waitForInstall(int ms)
{
#if QT_CONFIG(process)
    return !m_process || m_process->waitForFinished(ms);
#else
    Q_UNUSED(ms);
    return true;
#endif
}

void InstallerController::reboot()
{
    // Same host path as the install: flatpak-spawn --host when sandboxed.
    QStringList argv = offline::hostCommand({QStringLiteral("systemctl"), QStringLiteral("reboot")});
    const QString program = argv.takeFirst();
#if QT_CONFIG(process)
    QProcess::startDetached(program, argv);
#else
    qCWarning(logInstaller) << "this build cannot start processes, not running" << program;
#endif
}
