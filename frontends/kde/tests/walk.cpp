// The wizard, clicked through from the first screen to the last against the
// mock fishermand (tuna-os/fisherman, fisherman/docs/FISHERMAND.md).
//
// tests/test_daemon.cpp drives the controller. This program drives the real
// QML: the same Wizard.qml and step modules the installer loads, moved only
// by their own buttons. After each click it reads the wizard's step id,
// which is the screen id of shared/flow/screens.yaml and the `page=` of the
// readiness stamp. A walk fails when the wizard lands on a screen that the
// scenario does not reach, or skips one that it does.
//
// It can install only into a mock: the program starts `fishermand --mock`
// itself, on sockets in a temporary directory, and points the frontend at
// that directory. It never uses a daemon that it did not start. Without a
// mock binary ($FISHERMAND_BIN, <build dir>/fishermand,
// <source dir>/build/fishermand, PATH) it exits 77, which ctest reads as a
// skip.
//
// SPDX-License-Identifier: GPL-3.0-only

#include <QAccessible>
#include <QApplication>
#include <QDir>
#include <QEventLoop>
#include <QFileInfo>
#include <QIcon>
#include <QProcess>
#include <QQmlApplicationEngine>
#include <QQuickItem>
#include <QQuickStyle>
#include <QQuickWindow>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTextStream>
#include <QTimer>

#include <memory>

#include "installercontroller.h"

using namespace Qt::StringLiterals;

namespace
{

QTextStream out(stdout);

void settle(int ms)
{
    QEventLoop loop;
    QTimer::singleShot(ms, &loop, &QEventLoop::quit);
    loop.exec();
}

QString mockBinary()
{
    const QString env = qEnvironmentVariable("FISHERMAND_BIN");
    if (!env.isEmpty())
        return QFileInfo(env).isExecutable() ? env : QString();
    for (const QString &path : {QStringLiteral(WALK_BINARY_DIR "/fishermand"),
                                QStringLiteral(WALK_SOURCE_DIR "/build/fishermand")}) {
        if (QFileInfo(path).isExecutable())
            return path;
    }
    return QStandardPaths::findExecutable(u"fishermand"_s);
}

// The visual tree, which is what "on the screen" means (see capture.cpp).
QQuickItem *findItemByName(QQuickItem *root, const QString &name)
{
    if (!root)
        return nullptr;
    if (root->objectName() == name)
        return root;
    const QList<QQuickItem *> children = root->childItems();
    for (QQuickItem *child : children) {
        if (QQuickItem *found = findItemByName(child, name))
            return found;
    }
    return nullptr;
}

// Visible all the way up: an item of a step that is not on screen has a
// hidden ancestor.
bool onScreen(const QQuickItem *item)
{
    for (const QQuickItem *i = item; i; i = i->parentItem()) {
        if (!i->isVisible())
            return false;
    }
    return true;
}

// One wizard on one mock daemon.
class Walk
{
public:
    Walk(const QString &name, const QString &scenario, const QByteArray &firstBootTool,
         const QString &stepDelay = u"60ms"_s)
        : m_name(name)
    {
        out << "walk " << name << " (scenario " << scenario << ")\n";
        out.flush();
        if (!m_dir.isValid()) {
            fail(u"no temporary directory"_s);
            return;
        }
        m_mock.setProgram(mockBinary());
        m_mock.setArguments({u"--mock"_s, u"--scenario"_s, scenario, u"--socket-dir"_s, m_dir.path(),
                             // Slow enough by default that the install screen
                             // is on screen before a scripted failure ends
                             // the install.
                             u"--step-delay"_s, stepDelay});
        m_mock.setStandardErrorFile(QProcess::nullDevice());
        m_mock.setStandardOutputFile(QProcess::nullDevice());
        m_mock.start();
        const QString socket = m_dir.filePath(u"io.tunaos.Fisherman"_s);
        for (int i = 0; i < 200 && !QFileInfo::exists(socket); i++)
            settle(25);
        if (!QFileInfo::exists(socket)) {
            fail(u"the mock daemon did not open its sockets"_s);
            return;
        }
        // Only this mock: the directory is this walk's own.
        qputenv("TUNA_INSTALLER_BACKEND", "daemon");
        qputenv("FISHERMAND_SOCKET_DIR", m_dir.path().toLocal8Bit());
        qunsetenv("TUNA_FISHERMAN_SOCKET");
        qunsetenv("BOOTC_INSTALLER_FAKE_PROBE");
        qputenv("TUNA_FIRSTBOOT_TOOL", firstBootTool);
        // A stable release with no terms: no disclaimer and no EULA step.
        qputenv("TUNA_OS_RELEASE_FILE", WALK_TESTDATA_DIR "/os-release-stable");
        qputenv("TUNA_EULA_FILE", "/nonexistent/eula.xml");

        m_engine = std::make_unique<QQmlApplicationEngine>();
        m_engine->loadFromModule("org.tunaos.installer"_L1, "Main"_L1);
        if (m_engine->rootObjects().isEmpty()) {
            fail(u"the QML did not load"_s);
            return;
        }
        m_window = qobject_cast<QQuickWindow *>(m_engine->rootObjects().constFirst());
        m_controller = m_engine->singletonInstance<InstallerController *>(u"org.tunaos.installer"_s,
                                                                         u"InstallerController"_s);
        if (!m_window || !m_controller) {
            fail(u"no window or no controller"_s);
            return;
        }
        if (!m_controller->daemonBackend() || m_controller->daemonUnreachable()) {
            fail(u"the wizard does not talk to the mock: "_s + m_controller->daemonError());
            return;
        }
        m_window->resize(1000, 700);
        m_window->show();
        settle(700);
        m_seen << step();
    }

    ~Walk()
    {
        m_engine.reset();
        m_mock.terminate();
        if (!m_mock.waitForFinished(5000))
            m_mock.kill();
        m_mock.waitForFinished(5000);
    }

    bool ok() const { return m_ok; }
    InstallerController *controller() const { return m_controller; }
    QString step() const { return m_window ? m_window->property("currentStepId").toString() : QString(); }
    QQuickItem *item(const QString &name) const
    {
        return m_window ? findItemByName(m_window->contentItem(), name) : nullptr;
    }

    void fail(const QString &why)
    {
        if (m_ok) {
            out << "  FAIL (" << m_name << ", on " << step() << "): " << why << "\n";
            if (m_controller) {
                out << "    problems: hostname [" << m_controller->hostnameProblem() << "] encryption ["
                    << m_controller->encryptionProblem() << "] user [" << m_controller->usernameProblem()
                    << "] region [" << m_controller->regionProblem() << "]\n";
            }
        }
        m_ok = false;
    }

    void expect(bool condition, const QString &what)
    {
        if (m_ok && !condition)
            fail(what);
    }

    // The wizard is on `want` (at once, or within `ms`), and the slide is over.
    void at(const QString &want, int ms = 5000)
    {
        if (!m_ok)
            return;
        for (int waited = 0; step() != want && waited < ms; waited += 50)
            settle(50);
        if (step() != want) {
            fail(u"expected the %1 screen"_s.arg(want));
            return;
        }
        if (m_seen.isEmpty() || m_seen.last() != want)
            m_seen << want;
        settle(900);
        shot(want);
    }

    // A picture of the screen, with TUNA_WALK_SHOTS set to a directory.
    void shot(const QString &what)
    {
        const QString dir = qEnvironmentVariable("TUNA_WALK_SHOTS");
        if (dir.isEmpty() || !m_window)
            return;
        QDir().mkpath(dir);
        m_window->grabWindow().save(u"%1/%2-%3-%4.png"_s.arg(dir, m_name).arg(++m_shots, 2, 10, '0'_L1).arg(what));
    }

    // The counter of the header, "Step 3 of 9 · Keyboard Layout".
    QString counter() const
    {
        const QQuickItem *label = item(u"stepCounter"_s);
        return label ? label->property("text").toString() : QString();
    }

    // A screen reader must hear what a password field is for, not what is
    // in it.
    QString passwordName(const QString &name) const
    {
        QList<QQuickItem *> todo{item(name)};
        while (!todo.isEmpty()) {
            QQuickItem *i = todo.takeFirst();
            if (!i)
                continue;
            if (i->inherits("QQuickTextInput")) {
                QAccessibleInterface *a = QAccessible::queryAccessibleInterface(i);
                return a ? a->text(QAccessible::Name) : QString();
            }
            todo << i->childItems();
        }
        return {};
    }

    // A click the way a person's click reaches a button: only on a button
    // that is on screen and enabled.
    void click(const QString &name)
    {
        if (!m_ok)
            return;
        QQuickItem *button = item(name);
        if (!button || !onScreen(button)) {
            fail(u"no %1 on screen"_s.arg(name));
            return;
        }
        if (!button->isEnabled()) {
            fail(u"%1 is not enabled"_s.arg(name));
            return;
        }
        QMetaObject::invokeMethod(button, "clicked");
        settle(100);
    }

    bool enabled(const QString &name) const
    {
        const QQuickItem *button = item(name);
        return button && onScreen(button) && button->isEnabled();
    }

    bool shown(const QString &name) const
    {
        const QQuickItem *i = item(name);
        return i && onScreen(i);
    }

    void next(const QString &want)
    {
        click(u"nextButton"_s);
        at(want);
    }

    // From the first screen to the disk list of a live medium with a stable
    // release and no terms: the network, disclaimer and terms steps skip.
    void toDisk(bool rst = false)
    {
        at(u"try-or-install"_s);
        expect(shown(u"tryButton"_s), u"live media has no Try button"_s);
        expect(!shown(u"nextButton"_s), u"try-or-install shows the shared Next button"_s);
        expect(counter().startsWith(u"Step 1 of "_s), u"the first step is not step 1: "_s + counter());
        click(u"installNowButton"_s);
        at(u"language"_s);
        next(u"keyboard"_s);
        expect(counter().startsWith(u"Step 3 of "_s), u"the third step is not step 3: "_s + counter());
        // The row that applies is in view, with its check mark.
        if (m_ok) {
            const QQuickItem *list = findItemByName(findItemByName(m_window->contentItem(), u"keyboardPicker"_s),
                                                    u"pickerList"_s);
            const QQuickItem *row = list ? list->property("currentItem").value<QQuickItem *>() : nullptr;
            const qreal y = row ? row->mapToItem(list, QPointF(0, 0)).y() : -1;
            expect(row && y >= 0 && y + row->height() <= list->height() + 1,
                   u"the current keyboard layout is not in view"_s);
        }
        next(u"timezone"_s);
        // Back goes to the screen before, and Next comes here again.
        click(u"backButton"_s);
        at(u"keyboard"_s);
        next(u"timezone"_s);
        if (rst) {
            next(u"rst"_s);
            expect(shown(u"rstPowerOffButton"_s), u"the RST screen has no Power off"_s);
        }
        next(u"disk"_s);
    }

    void account()
    {
        if (!m_ok)
            return;
        expect(!enabled(u"nextButton"_s), u"Next is live before the account is typed"_s);
        m_controller->setUsername(u"alex"_s);
        m_controller->setUserPassword(u"account password 42"_s);
        if (QQuickItem *confirm = item(u"accountPasswordConfirm"_s))
            confirm->setProperty("text", u"account password 42"_s);
        settle(600);
        expect(passwordName(u"accountPassword"_s) == u"Password"_s,
               u"the password field is named \"%1\""_s.arg(passwordName(u"accountPassword"_s)));
        expect(passwordName(u"accountPasswordConfirm"_s) == u"Confirm password"_s,
               u"the confirmation field has another name"_s);
        shot(u"account-typed"_s);
    }

    // Install on the confirm screen, then the wizard moves by itself.
    void install(const QString &after)
    {
        expect(step() == u"confirm"_s, u"Install is pressed off the confirm screen"_s);
        expect(!m_controller->installing(), u"an install runs before Install was pressed"_s);
        click(u"nextButton"_s);
        // The step id changes with the click, before the slide: checked at
        // once, because a scripted failure can end the install in less
        // time than a slide takes.
        if (m_ok && step() != u"install"_s) {
            fail(u"Install did not open the install screen"_s);
            return;
        }
        m_seen << u"install"_s;
        expect(!shown(u"backButton"_s), u"Back is offered during the install"_s);
        expect(!shown(u"nextButton"_s), u"Next is offered during the install"_s);
        if (after != u"install"_s)
            at(after, 60000);
        else
            settle(900);
    }

    void recoveryKey()
    {
        if (!m_ok)
            return;
        static const QRegularExpression shape(u"^[a-z]{6,10}(-[a-z]{6,10}){7}$"_s);
        // The daemon makes the key after the install: wait for it.
        for (int waited = 0; m_controller->recoveryBusy() && waited < 15000; waited += 50)
            settle(50);
        settle(100);
        const QQuickItem *label = item(u"recoveryKeyLabel"_s);
        expect(label && shape.match(label->property("text").toString()).hasMatch(),
               u"the recovery key label does not hold a key of the contract's shape"_s);
        expect(shown(u"recoveryQrButton"_s) && enabled(u"recoveryQrButton"_s), u"no QR button"_s);
        expect(!enabled(u"recoveryDoneButton"_s), u"Done is live before the key was acknowledged"_s);
        expect(!shown(u"backButton"_s) && !shown(u"nextButton"_s), u"Back or Next on the recovery-key screen"_s);
        m_controller->setRecoveryAck(true);
        settle(100);
        click(u"recoveryDoneButton"_s);
        // The enrolment does not block: wait for the daemon's answer.
        for (int waited = 0; m_ok && m_controller->recoveryBusy() && waited < 15000; waited += 50)
            settle(50);
        expect(m_controller->recoveryEnrolled(), u"Done did not enrol the recovery key"_s);
    }

    bool finish(const QStringList &want)
    {
        if (m_ok && m_seen != want)
            fail(u"the screens were\n      %1\n    and not\n      %2"_s.arg(m_seen.join(u" > "_s), want.join(u" > "_s)));
        if (m_ok)
            out << "  ok: " << m_seen.join(u" > "_s) << "\n";
        out.flush();
        return m_ok;
    }

private:
    QString m_name;
    QTemporaryDir m_dir;
    QProcess m_mock;
    std::unique_ptr<QQmlApplicationEngine> m_engine;
    QQuickWindow *m_window = nullptr;
    InstallerController *m_controller = nullptr;
    QStringList m_seen;
    bool m_ok = true;
    int m_shots = 0;
};

// happy: an empty disk and a TPM 2.0. No wipe-or-free and no encryption
// step. The key, the handoff with a restart.
bool walkHappy()
{
    Walk w(u"happy"_s, u"happy"_s, "none");
    w.toDisk();
    w.expect(!w.enabled(u"nextButton"_s), u"Next is live before a disk was picked"_s);
    w.expect(w.shown(u"tooSmallDisks"_s), u"the disk that is too small is not listed"_s);
    if (w.ok())
        w.controller()->setDisk(u"/dev/nvme0n1"_s);
    settle(200);
    w.next(u"account"_s);
    w.account();
    w.next(u"confirm"_s);
    w.install(u"recovery-key"_s);
    w.expect(w.ok() && w.controller()->succeeded(), u"the install did not succeed"_s);
    w.recoveryKey();
    w.at(u"handoff"_s);
    w.expect(w.ok() && w.controller()->handoffMode() == u"reboot"_s, u"the handoff mode is not reboot"_s);
    w.click(u"handoffContinueButton"_s);
    for (int waited = 0; w.ok() && w.controller()->handoffState() != u"started"_s && waited < 15000; waited += 50)
        settle(50);
    settle(300);
    w.expect(w.ok() && w.controller()->handoffState() == u"started"_s, u"Continue did not start the handoff"_s);
    // A restart is on its way: the screen stays and says so.
    w.expect(w.step() == u"handoff"_s, u"the wizard left the handoff screen during a restart"_s);
    w.expect(w.shown(u"handoffStarted"_s), u"the handoff screen does not say that the restart started"_s);
    return w.finish({u"try-or-install"_s, u"language"_s, u"keyboard"_s, u"timezone"_s, u"keyboard"_s, u"timezone"_s,
                     u"disk"_s, u"account"_s, u"confirm"_s, u"install"_s, u"recovery-key"_s, u"handoff"_s});
}

// handoff-migrate on a medium that names a first-boot tool: no account step, and
// after Continue the session goes on, so the wizard shows the done screen.
bool walkMigrate()
{
    // gnome-initial-setup, not plasma-setup: the wizard checks a claim of
    // plasma-setup against the unit, and the build host has none.
    Walk w(u"migrate"_s, u"handoff-migrate"_s, "gnome-initial-setup");
    w.toDisk();
    if (w.ok())
        w.controller()->setDisk(u"/dev/nvme0n1"_s);
    settle(200);
    w.next(u"confirm"_s);
    w.expect(w.shown(u"confirmFirstBoot"_s), u"confirm does not say that the first-boot tool makes the user"_s);
    w.install(u"recovery-key"_s);
    w.recoveryKey();
    w.at(u"handoff"_s);
    w.expect(w.ok() && w.controller()->handoffMode() == u"migrate"_s, u"the handoff mode is not migrate"_s);
    w.expect(w.shown(u"handoffFirstBoot"_s), u"handoff does not say that the first-boot tool asks for the user"_s);
    w.click(u"handoffContinueButton"_s);
    w.at(u"done"_s);
    w.expect(w.ok() && w.controller()->sessionKeepsRunning(), u"the session does not keep running after a migrate"_s);
    w.expect(!w.shown(u"doneRestartButton"_s), u"done offers a restart after a migrate"_s);
    w.expect(!w.shown(u"doneRetryButton"_s), u"done offers Try again after a good install"_s);
    return w.finish({u"try-or-install"_s, u"language"_s, u"keyboard"_s, u"timezone"_s, u"keyboard"_s, u"timezone"_s,
                     u"disk"_s, u"confirm"_s, u"install"_s, u"recovery-key"_s, u"handoff"_s, u"done"_s});
}

// existing-data and no-tpm: the wipe-or-free choice, the passphrase, and
// Not now on the handoff.
bool walkExistingDataNoTpm()
{
    Walk w(u"existing-data"_s, u"existing-data,no-tpm"_s, "none");
    w.toDisk();
    if (w.ok())
        w.controller()->setDisk(u"/dev/nvme0n1"_s);
    settle(200);
    w.next(u"wipe-or-free"_s);
    w.expect(!w.shown(u"nextButton"_s), u"wipe-or-free shows the shared Next button"_s);
    w.expect(w.shown(u"eraseDiskButton"_s), u"wipe-or-free has no erase choice"_s);
    w.click(u"freeSpaceButton"_s);
    w.at(u"encryption"_s);
    w.expect(w.shown(u"encryptionNoTpm"_s), u"the encryption screen does not say why it asks"_s);
    w.expect(!w.enabled(u"nextButton"_s), u"Next is live with no passphrase"_s);
    if (w.ok()) {
        if (QQuickItem *field = w.item(u"encryptionPassphrase"_s))
            field->setProperty("text", u"correct horse battery staple"_s);
        if (QQuickItem *field = w.item(u"encryptionPassphraseConfirm"_s))
            field->setProperty("text", u"correct horse battery"_s);
        settle(700);
    }
    w.expect(!w.enabled(u"nextButton"_s), u"Next is live while the two passphrases differ"_s);
    if (w.ok()) {
        if (QQuickItem *field = w.item(u"encryptionPassphraseConfirm"_s))
            field->setProperty("text", u"correct horse battery staple"_s);
        settle(900);
    }
    w.next(u"account"_s);
    w.account();
    w.next(u"confirm"_s);
    w.expect(w.shown(u"confirmKeepsData"_s), u"confirm does not say that the data stays"_s);
    w.expect(!w.shown(u"confirmWarning"_s), u"confirm says that a free-space install erases the disk"_s);
    w.expect(w.ok() && w.controller()->daemonConfig().value(u"installMode"_s).toString() == u"free_space"_s,
             u"the install mode is not free_space"_s);
    w.install(u"recovery-key"_s);
    w.recoveryKey();
    w.at(u"handoff"_s);
    w.click(u"handoffNotNowButton"_s);
    w.at(u"done"_s);
    w.expect(w.ok() && w.controller()->handoffState().isEmpty(), u"Not now started a handoff"_s);
    w.expect(w.shown(u"doneRestartButton"_s), u"done has no restart after Not now"_s);
    return w.finish({u"try-or-install"_s, u"language"_s, u"keyboard"_s, u"timezone"_s, u"keyboard"_s, u"timezone"_s,
                     u"disk"_s, u"wipe-or-free"_s, u"encryption"_s, u"account"_s, u"confirm"_s, u"install"_s,
                     u"recovery-key"_s, u"handoff"_s, u"done"_s});
}

// device-lost and repart-error: from the install straight to the done
// screen, no key and no handoff, and Try again goes to the disk list.
bool walkFailure(const QString &scenario, const QString &reason)
{
    Walk w(scenario, scenario, "none");
    w.toDisk();
    if (w.ok())
        w.controller()->setDisk(u"/dev/nvme0n1"_s);
    settle(200);
    w.next(u"account"_s);
    w.account();
    w.next(u"confirm"_s);
    w.install(u"done"_s);
    w.expect(w.ok() && !w.controller()->succeeded() && !w.controller()->cancelled(), u"the install did not fail"_s);
    w.expect(w.ok() && w.controller()->failureReason() == reason, u"the failure reason is not %1"_s.arg(reason));
    const QQuickItem *heading = w.item(u"doneHeading"_s);
    w.expect(w.ok() && heading && heading->property("text").toString() == w.controller()->text(u"done_failed_title"_s),
             u"the done screen does not show the failure heading"_s);
    w.expect(!w.shown(u"doneRestartButton"_s), u"the failure screen offers a restart"_s);
    w.click(u"doneRetryButton"_s);
    w.at(u"disk"_s);
    w.expect(w.ok() && !w.controller()->installFinishedFlag(), u"Try again kept the old result"_s);
    return w.finish({u"try-or-install"_s, u"language"_s, u"keyboard"_s, u"timezone"_s, u"keyboard"_s, u"timezone"_s,
                     u"disk"_s, u"account"_s, u"confirm"_s, u"install"_s, u"done"_s, u"disk"_s});
}

// cancel: Cancel asks first, the confirmed cancel ends on the cancelled
// done screen.
bool walkCancel()
{
    Walk w(u"cancel"_s, u"cancel"_s, "none", u"5ms"_s);
    w.toDisk();
    if (w.ok())
        w.controller()->setDisk(u"/dev/nvme0n1"_s);
    settle(200);
    w.next(u"account"_s);
    w.account();
    w.next(u"confirm"_s);
    w.install(u"install"_s);
    // The mock waits in install_os until Cancel.
    for (int waited = 0; w.ok() && w.controller()->installStep() < 5 && waited < 30000; waited += 50)
        settle(50);
    settle(500);
    w.expect(w.ok() && w.controller()->installing(), u"the install ended before Cancel"_s);
    w.click(u"cancelInstallButton"_s);
    settle(500);
    w.expect(w.ok() && w.controller()->installing(), u"one click on Cancel stopped the install"_s);
    QObject *stop = nullptr;
    if (QQuickItem *cancel = w.item(u"cancelInstallButton"_s)) {
        for (QObject *o = cancel; o && !stop; o = o->parent())
            stop = o->findChild<QObject *>(u"cancelConfirmStop"_s);
    }
    w.expect(stop != nullptr, u"the cancel question has no Stop action"_s);
    if (w.ok() && stop)
        QMetaObject::invokeMethod(stop, "trigger");
    w.at(u"done"_s, 60000);
    w.expect(w.ok() && w.controller()->cancelled(), u"the install was not cancelled"_s);
    const QQuickItem *heading = w.item(u"doneHeading"_s);
    w.expect(w.ok() && heading
                 && heading->property("text").toString() == w.controller()->text(u"done_cancelled_title"_s),
             u"the done screen does not show the cancelled heading"_s);
    w.expect(w.shown(u"doneRetryButton"_s), u"the cancelled screen has no Try again"_s);
    return w.finish({u"try-or-install"_s, u"language"_s, u"keyboard"_s, u"timezone"_s, u"keyboard"_s, u"timezone"_s,
                     u"disk"_s, u"account"_s, u"confirm"_s, u"install"_s, u"done"_s});
}

// rst: the warning before the disk list. It does not block: Next goes on,
// and the disk list has no disk to pick.
bool walkRst()
{
    Walk w(u"rst"_s, u"rst"_s, "none");
    w.toDisk(true);
    w.expect(!w.enabled(u"nextButton"_s), u"Next is live with no disk to pick"_s);
    w.expect(w.shown(u"diskRescanButton"_s) && w.shown(u"diskPowerOffButton"_s),
             u"the empty disk list offers no rescan or power off"_s);
    return w.finish({u"try-or-install"_s, u"language"_s, u"keyboard"_s, u"timezone"_s, u"keyboard"_s, u"timezone"_s,
                     u"rst"_s, u"disk"_s});
}

// low-ram: the wizard starts on the requirements screen and holds Next
// until the person says to continue anyway.
bool walkLowRam()
{
    Walk w(u"low-ram"_s, u"low-ram"_s, "none");
    w.at(u"requirements"_s);
    w.expect(!w.enabled(u"nextButton"_s), u"Next is live under an unmet requirement"_s);
    w.expect(w.shown(u"powerOffButton"_s), u"the requirements screen has no Power off"_s);
    w.expect(w.shown(u"continueAnywayCheck"_s), u"the requirements screen has no Continue anyway"_s);
    if (w.ok())
        w.controller()->setContinueAnyway(true);
    settle(200);
    w.next(u"try-or-install"_s);
    return w.finish({u"requirements"_s, u"try-or-install"_s});
}

// no-uefi: no way on.
bool walkNoUefi()
{
    Walk w(u"no-uefi"_s, u"no-uefi"_s, "none");
    w.at(u"requirements"_s);
    w.expect(!w.enabled(u"nextButton"_s), u"Next is live without UEFI"_s);
    w.expect(!w.shown(u"continueAnywayCheck"_s), u"a boot without UEFI offers Continue anyway"_s);
    if (w.ok())
        w.controller()->setContinueAnyway(true);
    settle(200);
    w.expect(!w.enabled(u"nextButton"_s), u"Continue anyway opened a boot without UEFI"_s);
    return w.finish({u"requirements"_s});
}

} // namespace

int main(int argc, char *argv[])
{
    qputenv("QT_QPA_PLATFORM", "offscreen");
    qputenv("QT_QUICK_BACKEND", "software");
    qputenv("QSG_RENDER_LOOP", "basic");

    QApplication app(argc, argv);
    if (qEnvironmentVariableIsEmpty("QT_QUICK_CONTROLS_STYLE"))
        QQuickStyle::setStyle(u"org.kde.desktop"_s);
    if (QIcon::themeName().isEmpty() || QIcon::themeName() == u"hicolor"_s)
        QIcon::setThemeName(u"breeze"_s);

    if (mockBinary().isEmpty()) {
        if (qEnvironmentVariableIsSet("TUNA_REQUIRE_FISHERMAND")) {
            out << "FAIL: TUNA_REQUIRE_FISHERMAND is set and there is no mock fishermand.\n";
            return 1;
        }
        out << "SKIP: no mock fishermand. Set FISHERMAND_BIN (go build ./fisherman/cmd/fishermand).\n";
        return 77;
    }
    QTemporaryDir home;
    qputenv("XDG_DATA_HOME", home.filePath(u"data"_s).toLocal8Bit());
    qputenv("XDG_CACHE_HOME", home.filePath(u"cache"_s).toLocal8Bit());
    qputenv("BOOTC_INSTALLER_PRODUCT_NAME", "Marlin");

    int failed = 0;
    failed += walkLowRam() ? 0 : 1;
    failed += walkNoUefi() ? 0 : 1;
    failed += walkRst() ? 0 : 1;
    failed += walkHappy() ? 0 : 1;
    failed += walkMigrate() ? 0 : 1;
    failed += walkExistingDataNoTpm() ? 0 : 1;
    failed += walkFailure(u"device-lost"_s, u"device_lost"_s) ? 0 : 1;
    failed += walkFailure(u"repart-error"_s, u"repart_failed"_s) ? 0 : 1;
    failed += walkCancel() ? 0 : 1;
    out << (failed ? "FAILED: " : "PASSED: ") << (9 - failed) << " of 9 walks\n";
    return failed ? 1 : 0;
}
