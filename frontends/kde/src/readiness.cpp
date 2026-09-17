#include "readiness.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QQuickWindow>
#include <QSaveFile>
#include <QVariant>

using namespace Qt::StringLiterals;

namespace
{
// $XDG_RUNTIME_DIR is per-user, tmpfs, and cleared between sessions, so a
// stale stamp cannot survive a reboot and be read as a fresh success.
constexpr auto StampName = "tuna-installer-ready";
constexpr auto AppId = "org.tunaos.InstallerKde";
} // namespace

namespace readiness
{

bool writeStamp(const QString &runtimeDir, const QString &page, qint64 msSinceEpoch)
{
    if (runtimeDir.isEmpty())
        return false;

    // A bare `page=` would parse downstream as a real page named "".
    const QString slug = page.isEmpty() ? u"unknown"_s : page;

    const QString body = u"app_id=%1\nwindow=ApplicationWindow\nsignal=frame-swapped\nmapped_at=%2\npage=%3\n"_s
                             .arg(QString::fromLatin1(AppId))
                             .arg(msSinceEpoch / 1000.0, 0, 'f', 3)
                             .arg(slug);

    // QSaveFile writes to a temporary and renames on commit, so a reader over
    // SSH never sees a half-written stamp and concludes the wrong thing came
    // up.
    QSaveFile file(QDir(runtimeDir).filePath(QString::fromLatin1(StampName)));
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text))
        return false;
    if (file.write(body.toUtf8()) < 0)
        return false;
    return file.commit();
}

void armStamp(QObject *root)
{
    auto *window = qobject_cast<QQuickWindow *>(root);
    if (!window)
        return;

    // Single-shot: frameSwapped fires on every frame, and this does file I/O.
    auto *connection = new QMetaObject::Connection;
    *connection = QObject::connect(window, &QQuickWindow::frameSwapped, window, [window, connection]() {
        QObject::disconnect(*connection);
        delete connection;

        // Main.qml already exposes the wizard position as currentStepId; absent or
        // unreadable, the stamp still says a frame was presented, which is the
        // part a smoke test cannot get any other way.
        const QVariant page = window->property("currentStepId");

        writeStamp(qEnvironmentVariable("XDG_RUNTIME_DIR"),
                   page.isValid() ? page.toString() : QString(),
                   QDateTime::currentMSecsSinceEpoch());
    });
}

} // namespace readiness
