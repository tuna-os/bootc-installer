#ifndef OFFLINE_H
#define OFFLINE_H

// Offline-install and sandbox plumbing shared by the wizard pages.
// Contract: ../../INSTALLER-FRONTENDS.md §3 (privileges) and §4 (offline).

#include <QSet>
#include <QString>
#include <QStringList>
#include <QtCore/qtcore-config.h>

class QProcess;

namespace offline {

// True when running inside a Flatpak sandbox.
bool inFlatpak();

// Command (program + leading args) that runs fisherman with privileges;
// the caller appends the recipe path. Inside Flatpak:
// flatpak-spawn --host bash -c 'pkexec /usr/local/bin/fisherman "$1"; exit $?' --
// Outside: sudo /usr/local/bin/fisherman.
QStringList fishermanCommand();
// The same, for an explicit sandbox state (tests).
QStringList fishermanCommand(bool flatpak);

#if QT_CONFIG(process)
// Makes `process` start as the leader of its own process group, so the
// fisherman wrapper can be signalled as a group without touching ours.
void startInOwnProcessGroup(QProcess &process);
#endif

// Wrap argv so it executes on the host when sandboxed (flatpak-spawn --host).
QStringList hostCommand(const QStringList &argv);

// Image ref of the booted live system, or empty when not on live media.
// Non-empty means the recipe may omit `image` (bootc installs the running container).
QString liveIsoImage();

// Embedded OCI store roots present on this medium (§4B conventions).
QStringList offlineStores();

// Image refs available across the given stores (podman images --root).
QSet<QString> offlineImages(const QStringList &stores);

} // namespace offline

#endif // OFFLINE_H
