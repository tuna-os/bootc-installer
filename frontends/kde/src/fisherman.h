#pragma once

// How this frontend reaches fisherman: the ONE place that knows the path of
// the binary and how it gets its privileges (#290).
//
//   native          /usr/local/bin/fisherman, as the GNOME frontend runs it:
//                   pkexec for the install, sudo -n on live media only (the
//                   live user has passwordless sudo and can have no polkit
//                   agent). Probe and validate run it without privileges.
//   in a Flatpak    the fisherman this Flatpak built (/app/bin/fisherman),
//                   copied to $XDG_CACHE_HOME/bootc-installer/fisherman and
//                   run on the host from there. The copy is used only after
//                   the host's own sha256sum of it equals ours: the sandbox
//                   writing a file is no proof that pkexec on the host reads
//                   the same bytes. Never HOME/.cache: /var/home can be
//                   private to one sandbox even with --filesystem=host.
//
// The recipe always goes to `fisherman -` on stdin (shared/recipe/README.md).

#include <QByteArray>
#include <QProcessEnvironment>
#include <QString>
#include <QStringList>

#include <functional>

namespace fisherman {

inline constexpr const char *NATIVE_PATH = "/usr/local/bin/fisherman";
// The binary the Flatpak manifest builds. BOOTC_FISHERMAN_PATH replaces it,
// as it does for the GNOME frontend.
inline constexpr const char *BUNDLED_PATH = "/app/bin/fisherman";
inline constexpr const char *BUNDLED_ENV = "BOOTC_FISHERMAN_PATH";

// The two ways to run fisherman.
struct Commands {
    // argv prefix for `probe --json` and `validate --json --partial -`: the
    // binary the install runs, as the desktop user. Never pkexec or sudo.
    QStringList unprivileged;
    // The whole install command; the caller writes the recipe to its stdin
    // and closes it. Always a bash wrapper, so this frontend owns a process
    // it can signal as a group.
    QStringList install;
};

// THE resolver. `stagedPath` is the host-verified copy and is read only when
// `flatpak` is true; `live` is the probe's live.is_live.
Commands resolve(bool flatpak, bool live, const QString &stagedPath);

// `$XDG_CACHE_HOME/bootc-installer`. Empty, with `error` set, when the
// variable is not an absolute path.
QString cacheDir(const QProcessEnvironment &env, QString *error = nullptr);

struct HostResult {
    int exitCode = -1;
    QByteArray stdoutData;
};
// Runs an argv on the host and returns its exit code and stdout.
using HostRunner = std::function<HostResult(const QStringList &argv)>;

struct Staging {
    bool ok = false;
    QString path;  // the staged binary; empty for a native run
    QString error; // why staging failed; empty when ok
};

// Copies `source` to `<cacheDir>/fisherman` (0700) and has the host hash it.
// Refuses a cache directory or a target that is a symlink, belongs to
// another user or is writable by group or others.
Staging stage(const QString &source, const QString &cacheDir, const HostRunner &runOnHost);

// Staging for this process, done once: a no-op outside a Flatpak.
const Staging &staged();

// resolve() for this process. Call staged() first and report its error.
Commands commands(bool live);

} // namespace fisherman
