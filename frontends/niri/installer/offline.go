// Sandbox plumbing: how this backend reaches fisherman and the host.
//
// There is ONE resolver here, resolveFisherman. Probe, validate and install
// all take their fisherman from it, so the three can never run different
// binaries:
//
//	native       /usr/local/bin/fisherman; the install escalates with pkexec
//	live media   the same binary; the install escalates with `sudo -n` (the
//	             live user has passwordless sudo and may have no polkit agent)
//	Flatpak      the bundled /app/bin/fisherman, staged to
//	             $XDG_CACHE_HOME/bootc-installer/fisherman and checked on the
//	             host by SHA256 before anything runs it
//
// The staged copy is what makes the Flatpak work on a machine that is not
// the live ISO, and what ties the fisherman that runs to the commit the
// Flatpak pins. This is the GNOME frontend's rule
// (bootc_installer/utils/fisherman_runner.py), in Go.
//
// Live media and offline image stores are fisherman's facts (probe's `live`
// and `offline`, probe.go).

package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

// nativeFisherman is where a native install and the live ISO keep fisherman.
const nativeFisherman = "/usr/local/bin/fisherman"

// bundledFishermanEnv overrides the binary the Flatpak stages (tests).
const bundledFishermanEnv = "BOOTC_FISHERMAN_PATH"

// bundledFisherman is the fisherman the Flatpak manifest builds.
const bundledFisherman = "/app/bin/fisherman"

// stageTimeout bounds the host-side checksum; it only bounds a hung
// flatpak-spawn.
const stageTimeout = 10 * time.Second

func inFlatpak() bool {
	_, err := os.Stat("/.flatpak-info")
	return err == nil
}

// Fisherman is the resolved way to run fisherman: where the binary is on the
// host, and how this process reaches the host.
type Fisherman struct {
	Flatpak bool
	// Path is the binary on the host: nativeFisherman, or the staged copy.
	Path string
}

// Argv is the unprivileged command for `probe --json` and `validate --json`:
// the binary the install runs, on the host, as the desktop user. Never
// pkexec or sudo.
func (f Fisherman) Argv(args ...string) []string {
	argv := []string{}
	if f.Flatpak {
		argv = append(argv, "flatpak-spawn", "--host")
	}
	return append(append(argv, f.Path), args...)
}

// The wrapper scripts run the escalation under a bash. fisherman runs as
// root, so nothing here can signal it; it cancels when its PARENT dies
// (tuna-os/fisherman#267), and bash is a parent this backend can kill. No
// redirection: stdin (the recipe), stdout and stderr all pass through.
//
// The native scripts are the ones every frontend runs
// (tests/unit/test_no_frontend_detection.py). The staged path of a Flatpak
// is "$1", never spliced into the script.
const (
	pkexecWrapperScript = `pkexec /usr/local/bin/fisherman -; exit $?`
	sudoWrapperScript   = `sudo -n /usr/local/bin/fisherman -; exit $?`
	stagedWrapperScript = `pkexec "$1" -; exit $?`
)

// InstallArgv is the privileged command the recipe is piped to
// (`fisherman -`). pkexec, except on live media outside a Flatpak, where it
// is `sudo -n`. `live` is fisherman's own answer (probe's live.is_live),
// never /run/ostree-booted, which every installed ostree host has.
func (f Fisherman) InstallArgv(live bool) []string {
	if f.Flatpak {
		return []string{"flatpak-spawn", "--host", "bash", "-c", stagedWrapperScript, "bash", f.Path}
	}
	if live {
		return []string{"bash", "-c", sudoWrapperScript}
	}
	return []string{"bash", "-c", pkexecWrapperScript}
}

// stagedFishermanPath is where the Flatpak stages its fisherman: the
// application cache, which Flatpak always shares with the host. Never
// HOME/.cache: /var/home can be private to one sandbox even with
// --filesystem=host.
func stagedFishermanPath(xdgCacheHome string) (string, error) {
	if xdgCacheHome == "" || !filepath.IsAbs(xdgCacheHome) {
		return "", errors.New("XDG_CACHE_HOME must be an absolute path in a Flatpak")
	}
	return filepath.Join(xdgCacheHome, "bootc-installer", "fisherman"), nil
}

// pathIsPrivate says whether a path is safe to hold a helper that root will
// run: missing, or a real file or directory of this user that nobody else
// can write.
func pathIsPrivate(path string) error {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("cannot stat %s: %w", path, err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("%s is a symlink", path)
	}
	if st, ok := info.Sys().(*syscall.Stat_t); ok && int(st.Uid) != os.Getuid() {
		return fmt.Errorf("%s is owned by uid %d, not %d", path, st.Uid, os.Getuid())
	}
	if info.Mode().Perm()&0o022 != 0 {
		return fmt.Errorf("%s is group- or world-writable", path)
	}
	return nil
}

func sha256File(path string) (string, error) {
	fh, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer fh.Close()
	sum := sha256.New()
	if _, err := io.Copy(sum, fh); err != nil {
		return "", err
	}
	return hex.EncodeToString(sum.Sum(nil)), nil
}

// hostSHA256 is the checksum of a path as the HOST sees it.
type hostSHA256 func(path string) (string, error)

// spawnHostSHA256 asks the host through the same portal that will run the
// binary. A copy that worked inside the sandbox is no proof that pkexec on
// the host reads the same bytes.
func spawnHostSHA256(path string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), stageTimeout)
	defer cancel()
	out, err := exec.CommandContext(ctx, "flatpak-spawn", "--host", "sha256sum", "--", path).Output()
	if err != nil {
		return "", fmt.Errorf("sha256sum on the host: %w", err)
	}
	fields := strings.Fields(string(out))
	if len(fields) == 0 {
		return "", errors.New("sha256sum on the host printed nothing")
	}
	return fields[0], nil
}

// stageFisherman copies the bundled fisherman to the staged path and checks
// that the host reads the same bytes. It refuses a staging path somebody
// else could have written.
func stageFisherman(source, staged string, onHost hostSHA256) error {
	dir := filepath.Dir(staged)
	// The cache home, the staging directory and the file itself, as GNOME
	// checks them.
	for _, path := range []string{filepath.Dir(dir), dir, staged} {
		if err := pathIsPrivate(path); err != nil {
			return fmt.Errorf("refusing to stage fisherman: %w", err)
		}
	}
	want, err := sha256File(source)
	if err != nil {
		return fmt.Errorf("the bundled fisherman cannot be read: %w", err)
	}
	if have, err := sha256File(staged); err != nil || have != want {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return fmt.Errorf("cannot stage fisherman: %w", err)
		}
		if err := copyExecutable(source, staged); err != nil {
			return fmt.Errorf("cannot stage fisherman: %w", err)
		}
	}
	seen, err := onHost(staged)
	if err != nil {
		return fmt.Errorf("cannot verify the staged fisherman: %w", err)
	}
	if seen != want {
		return fmt.Errorf("the staged fisherman at %s is not the bundled one on the host", staged)
	}
	return nil
}

// copyExecutable writes source to a temporary file beside dest and renames
// it, so a reader on the host never runs a half-written binary.
func copyExecutable(source, dest string) error {
	in, err := os.Open(source)
	if err != nil {
		return err
	}
	defer in.Close()
	tmp, err := os.CreateTemp(filepath.Dir(dest), ".fisherman-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := io.Copy(tmp, in); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Chmod(0o700); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), dest)
}

// resolveFishermanFor is resolveFisherman with its inputs given (tests).
func resolveFishermanFor(flatpak bool, xdgCacheHome, source string, onHost hostSHA256) (Fisherman, error) {
	if !flatpak {
		return Fisherman{Path: nativeFisherman}, nil
	}
	staged, err := stagedFishermanPath(xdgCacheHome)
	if err != nil {
		return Fisherman{}, err
	}
	if err := stageFisherman(source, staged, onHost); err != nil {
		return Fisherman{}, err
	}
	return Fisherman{Flatpak: true, Path: staged}, nil
}

// resolveFisherman is the one place this backend decides which fisherman
// runs. In a Flatpak it stages and verifies the bundled binary first; an
// error means nothing may run.
func resolveFisherman() (Fisherman, error) {
	source := os.Getenv(bundledFishermanEnv)
	if source == "" {
		source = bundledFisherman
	}
	return resolveFishermanFor(inFlatpak(), os.Getenv("XDG_CACHE_HOME"), source, spawnHostSHA256)
}

// hostCommand wraps argv so it executes on the host when sandboxed.
func hostCommand(argv ...string) []string {
	if inFlatpak() {
		return append([]string{"flatpak-spawn", "--host"}, argv...)
	}
	return argv
}
