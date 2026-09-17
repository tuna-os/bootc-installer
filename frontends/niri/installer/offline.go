// Offline-install and sandbox plumbing.
// Contract: ../../INSTALLER-FRONTENDS.md §3 (privileges) and §4 (offline).

package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

func inFlatpak() bool {
	_, err := os.Stat("/.flatpak-info")
	return err == nil
}

// fishermanCommand returns the program+args that run fisherman with privileges.
//
// Flatpak runtimes ship no pkexec; escalate host-side. The live ISO symlinks
// the flatpak-bundled fisherman to /usr/local/bin and installs the polkit
// policy for it (tunaOS customize-live.sh).
func fishermanCommand() []string {
	if inFlatpak() {
		return []string{"flatpak-spawn", "--host", "pkexec", "/usr/local/bin/fisherman"}
	}
	return []string{"sudo", "/usr/local/bin/fisherman"}
}

// hostCommand wraps argv so it executes on the host when sandboxed.
func hostCommand(argv ...string) []string {
	if inFlatpak() {
		return append([]string{"flatpak-spawn", "--host"}, argv...)
	}
	return argv
}

func runHost(argv ...string) ([]byte, error) {
	cmd := hostCommand(argv...)
	return exec.Command(cmd[0], cmd[1:]...).Output()
}

// liveISOImage returns the booted bootc image ref when running from live
// media, or "" otherwise. Non-empty means the recipe may omit `image`
// (bootc installs the running container).
func liveISOImage() string {
	out, err := runHost("bootc", "status", "--json")
	if err != nil {
		return ""
	}
	var status struct {
		Status struct {
			Booted struct {
				Image struct {
					Image struct {
						Image string `json:"image"`
					} `json:"image"`
				} `json:"image"`
			} `json:"booted"`
		} `json:"status"`
	}
	if json.Unmarshal(out, &status) != nil {
		return ""
	}
	ref := status.Status.Booted.Image.Image.Image
	if ref == "" {
		return ""
	}
	live := false
	if _, err := os.Stat("/run/ostree-live"); err == nil {
		live = true
	} else if cmdline, err := os.ReadFile("/proc/cmdline"); err == nil {
		live = strings.Contains(string(cmdline), "rd.live.image")
	}
	if !live {
		return ""
	}
	return ref
}

// offlineStores returns embedded OCI store roots present on this medium.
func offlineStores() []string {
	var stores []string
	if env := os.Getenv("TUNA_OFFLINE_STORES"); env != "" {
		stores = append(stores, strings.Split(env, ":")...)
	}
	if listing, err := os.ReadFile("/etc/tuna-installer/offline-stores"); err == nil {
		for _, line := range strings.Split(string(listing), "\n") {
			line = strings.TrimSpace(line)
			if line != "" && !strings.HasPrefix(line, "#") {
				stores = append(stores, line)
			}
		}
	}
	stores = append(stores, "/usr/share/tuna-installer/oci-store")

	seen := map[string]bool{}
	var existing []string
	for _, s := range stores {
		if seen[s] {
			continue
		}
		seen[s] = true
		if info, err := os.Stat(s); err == nil && info.IsDir() {
			existing = append(existing, s)
		}
	}
	return existing
}

// offlineImages returns image refs available across the given stores.
func offlineImages(stores []string) []string {
	seen := map[string]bool{}
	var refs []string
	for _, store := range stores {
		out, err := runHost("podman", "images", "--root", store, "--format", "json")
		if err != nil {
			continue
		}
		var imgs []struct {
			Names []string `json:"Names"`
		}
		if json.Unmarshal(out, &imgs) != nil {
			continue
		}
		for _, img := range imgs {
			for _, n := range img.Names {
				if !seen[n] {
					seen[n] = true
					refs = append(refs, n)
				}
			}
		}
	}
	return refs
}

// writeRecipe writes the recipe 0600 into a fresh private directory under
// XDG_RUNTIME_DIR (it may hold secrets). The caller removes the directory —
// recipeDir gives it back from the returned path.
//
// The directory matters as much as the file mode. This used to be a fixed
// <base>/tuna-installer created with os.MkdirAll, writing to the constant
// name recipe.json. When XDG_RUNTIME_DIR is unset — the default under sudo
// (env_reset strips it), from a TTY, and from any launcher that is not a
// logind session — base is /tmp, so the whole path was predictable. MkdirAll
// returns nil for an existing directory without correcting its mode, so a
// pre-created 0777 /tmp/tuna-installer was adopted as-is, and os.WriteFile
// opens without O_EXCL or O_NOFOLLOW, so the predictable filename could be
// pre-planted as a symlink or swapped after the write.
//
// That path is handed straight to sudo/pkexec fisherman, so controlling it
// means choosing the image root installs, the disk it goes on, whether
// encryption is applied, and the initial user account.
//
// os.MkdirTemp creates a 0700 directory with an unpredictable name and
// O_EXCL semantics; O_EXCL|O_NOFOLLOW on the file itself turns a pre-planted
// file or symlink into a hard failure instead of a redirected write.
func writeRecipe(data []byte) (string, error) {
	base := os.Getenv("XDG_RUNTIME_DIR")
	if base == "" {
		base = os.TempDir()
	}
	dir, err := os.MkdirTemp(base, "tuna-installer-")
	if err != nil {
		return "", err
	}
	path := filepath.Join(dir, "recipe.json")
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL|syscall.O_NOFOLLOW, 0o600)
	if err != nil {
		os.RemoveAll(dir)
		return "", err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		os.RemoveAll(dir)
		return "", err
	}
	if err := f.Close(); err != nil {
		os.RemoveAll(dir)
		return "", err
	}
	return path, nil
}

// recipeDir is the private directory writeRecipe created for path.
func recipeDir(path string) string { return filepath.Dir(path) }

// productName returns the PRETTY_NAME from os-release — the per-variant
// product name ("Skipjack", "Bonito", ...) that tunaOS's branding pipeline
// (build_scripts/90-image-info.sh) writes into /etc/os-release at image build
// time. The installer shows this instead of a hardcoded "TunaOS" so a Skipjack
// ISO says Skipjack.
//
// /run/host/etc/os-release is checked FIRST and preferred: this app ships as a
// flatpak (org.tunaos.InstallerNiri), and inside the sandbox /etc/os-release is
// the runtime's (Freedesktop/GNOME), not the host image's. Only the host copy
// carries the variant.
//
// Returns "" when neither file is readable or PRETTY_NAME is absent/empty; the
// caller decides the fallback.
func productName() string {
	return productNameFrom("/run/host/etc/os-release", "/etc/os-release")
}

func productNameFrom(paths ...string) string {
	for _, path := range paths {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if !strings.HasPrefix(line, "PRETTY_NAME=") {
				continue
			}
			// os-release values are usually quoted; they may also be empty,
			// in which case fall through to the next file.
			val := strings.TrimSpace(strings.TrimPrefix(line, "PRETTY_NAME="))
			val = strings.Trim(val, `"'`)
			if val != "" {
				return val
			}
		}
	}
	return ""
}
