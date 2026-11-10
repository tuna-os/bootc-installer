#include "fisherman.h"

#include "log.h"
#include "offline.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#if QT_CONFIG(process)
#include <QProcess>
#endif

#ifdef Q_OS_UNIX
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace fisherman {

namespace {

// One argument for a POSIX shell.
QString shellQuote(const QString &s)
{
    QString out = s;
    out.replace(QLatin1Char('\''), QLatin1String("'\\''"));
    return QLatin1Char('\'') + out + QLatin1Char('\'');
}

// Safe to hold a helper that root will run: ours, not a symlink, and not
// writable by anyone else. A path that does not exist yet is safe.
bool isPrivate(const QString &path, QString *why)
{
#ifdef Q_OS_UNIX
    struct stat st{};
    if (::lstat(QFile::encodeName(path).constData(), &st) != 0) {
        if (errno == ENOENT)
            return true;
        *why = QStringLiteral("cannot stat %1").arg(path);
        return false;
    }
    if (S_ISLNK(st.st_mode)) {
        *why = QStringLiteral("%1 is a symlink").arg(path);
        return false;
    }
    if (st.st_uid != ::getuid()) {
        *why = QStringLiteral("%1 belongs to another user").arg(path);
        return false;
    }
    if (st.st_mode & (S_IWGRP | S_IWOTH)) {
        *why = QStringLiteral("%1 is writable by group or others").arg(path);
        return false;
    }
#else
    Q_UNUSED(path);
    Q_UNUSED(why);
#endif
    return true;
}

Staging failed(const QString &why)
{
    qCWarning(logInstaller) << "staging fisherman:" << why;
    return {false, QString(), why};
}

HostResult runOnHost(const QStringList &argv)
{
    HostResult r;
#if QT_CONFIG(process)
    QStringList cmd = offline::hostCommand(argv);
    QProcess p;
    p.start(cmd.takeFirst(), cmd);
    if (!p.waitForFinished(10000)) {
        p.kill();
        p.waitForFinished(1000);
        return r;
    }
    if (p.exitStatus() == QProcess::NormalExit)
        r.exitCode = p.exitCode();
    r.stdoutData = p.readAllStandardOutput();
#else
    Q_UNUSED(argv);
#endif
    return r;
}

} // namespace

Commands resolve(bool flatpak, bool live, const QString &stagedPath)
{
    const QStringList dash{QStringLiteral("-")};
    if (flatpak) {
        // Flatpak runtimes ship no pkexec; escalate on the host. pkexec runs
        // inside a host-side bash, not straight from flatpak-spawn: fisherman
        // runs as root and cancels when its PARENT dies
        // (tuna-os/fisherman#267), and under `flatpak-spawn --host pkexec`
        // that parent was the host's flatpak-session-helper, which this
        // frontend cannot kill. No redirection: stdin, stdout and stderr all
        // pass through flatpak-spawn.
        const QStringList host{QStringLiteral("flatpak-spawn"), QStringLiteral("--host")};
        return {host + QStringList{stagedPath},
                host + QStringList{QStringLiteral("bash"), QStringLiteral("-c"),
                                   QStringLiteral("pkexec %1 -; exit $?").arg(shellQuote(stagedPath))}};
    }
    const QString native = QString::fromLatin1(NATIVE_PATH);
    // pkexec, as every frontend; sudo -n only on live media, where the live
    // user has passwordless sudo and there can be no polkit agent.
    return {QStringList{native},
            QStringList{QStringLiteral("bash"), QStringLiteral("-c"),
                        live ? QStringLiteral("sudo -n /usr/local/bin/fisherman -; exit $?")
                             : QStringLiteral("pkexec /usr/local/bin/fisherman -; exit $?")}};
}

QString cacheDir(const QProcessEnvironment &env, QString *error)
{
    const QString cache = env.value(QStringLiteral("XDG_CACHE_HOME"));
    if (cache.isEmpty() || !QDir::isAbsolutePath(cache)) {
        if (error)
            *error = QStringLiteral("XDG_CACHE_HOME is not an absolute path");
        return {};
    }
    return QDir(cache).filePath(QStringLiteral("bootc-installer"));
}

Staging stage(const QString &source, const QString &cacheDir, const HostRunner &runHost)
{
    if (cacheDir.isEmpty() || !QDir::isAbsolutePath(cacheDir))
        return failed(QStringLiteral("no absolute cache directory to stage fisherman in"));
    const QString target = QDir(cacheDir).filePath(QStringLiteral("fisherman"));
    QString why;
    for (const QString &path : {QFileInfo(cacheDir).path(), cacheDir, target}) {
        if (!isPrivate(path, &why))
            return failed(why);
    }

    QFile packaged(source);
    if (!packaged.open(QIODevice::ReadOnly))
        return failed(QStringLiteral("cannot read %1: %2").arg(source, packaged.errorString()));
    const QByteArray bytes = packaged.readAll();
    const QByteArray expected = QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex();

    if (!QDir().mkpath(cacheDir))
        return failed(QStringLiteral("cannot create %1").arg(cacheDir));
    QFile::setPermissions(cacheDir, QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner);
    QFile::remove(target);
    QFile out(target);
    if (!out.open(QIODevice::WriteOnly | QIODevice::Truncate) || out.write(bytes) != bytes.size())
        return failed(QStringLiteral("cannot write %1: %2").arg(target, out.errorString()));
    out.close();
    out.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner);

    // The host's own view of the file, through the portal that will run it.
    const HostResult seen = runHost({QStringLiteral("sha256sum"), QStringLiteral("--"), target});
    const QByteArray digest = seen.stdoutData.simplified().split(' ').value(0);
    if (seen.exitCode != 0 || digest != expected)
        return failed(QStringLiteral("the staged fisherman at %1 is not the same file on the host").arg(target));
    qCInfo(logInstaller) << "staged and host-verified fisherman at" << target;
    return {true, target, QString()};
}

const Staging &staged()
{
    static const Staging result = [] {
        if (!offline::inFlatpak())
            return Staging{true, QString(), QString()};
        const QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
        QString error;
        const QString dir = cacheDir(env, &error);
        if (dir.isEmpty())
            return failed(error);
        return stage(env.value(QString::fromLatin1(BUNDLED_ENV), QString::fromLatin1(BUNDLED_PATH)),
                     dir, runOnHost);
    }();
    return result;
}

Commands commands(bool live)
{
    return resolve(offline::inFlatpak(), live, staged().path);
}

} // namespace fisherman
