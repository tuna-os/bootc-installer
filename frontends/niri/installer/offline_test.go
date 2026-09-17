package main

// Unit tests for offline.go — offline-install and sandbox plumbing.
// Contract: ../../INSTALLER-FRONTENDS.md §3 (privileges) and §4 (offline).

import (
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func TestFishermanCommandOutsideFlatpak(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	got := fishermanCommand()
	want := []string{"sudo", "/usr/local/bin/fisherman"}
	if len(got) != len(want) {
		t.Fatalf("fishermanCommand() = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("fishermanCommand() = %v, want %v", got, want)
		}
	}
}

func TestHostCommandPassthroughOutsideFlatpak(t *testing.T) {
	if inFlatpak() {
		t.Skip("running inside a Flatpak sandbox")
	}
	got := hostCommand("bootc", "status")
	want := []string{"bootc", "status"}
	if len(got) != len(want) || got[0] != want[0] || got[1] != want[1] {
		t.Fatalf("hostCommand() = %v, want %v", got, want)
	}
}

func TestOfflineStoresEnvParsingDedupAndDirFilter(t *testing.T) {
	base := t.TempDir()
	dirA := filepath.Join(base, "store-a")
	dirB := filepath.Join(base, "store-b")
	plain := filepath.Join(base, "plain-file")
	for _, d := range []string{dirA, dirB} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(plain, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TUNA_OFFLINE_STORES", strings.Join([]string{dirA, dirB, plain, dirA}, ":"))

	got := offlineStores()
	// dirA and dirB present exactly once, in order; the plain file and the
	// default store (not a directory in the test environment) are filtered.
	if len(got) != 2 {
		t.Fatalf("offlineStores() = %v, want exactly [dirA, dirB]", got)
	}
	if got[0] != dirA || got[1] != dirB {
		t.Fatalf("offlineStores() = %v, want [%s, %s]", got, dirA, dirB)
	}
}

func TestOfflineImagesEmptyWithoutStores(t *testing.T) {
	if got := offlineImages(nil); len(got) != 0 {
		t.Fatalf("offlineImages(nil) = %v, want empty", got)
	}
	// A store root that cannot exist yields nothing rather than an error.
	if got := offlineImages([]string{filepath.Join(t.TempDir(), "missing-store")}); len(got) != 0 {
		t.Fatalf("offlineImages(missing store) = %v, want empty", got)
	}
}

func TestWriteRecipe(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("XDG_RUNTIME_DIR", dir)

	path, err := writeRecipe([]byte(`{"image":"localhost/foo:1"}`))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(path, filepath.Join(dir, "tuna-installer-")) {
		t.Fatalf("recipe path %s not under runtime dir %s", path, dir)
	}
	defer os.RemoveAll(recipeDir(path))

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != `{"image":"localhost/foo:1"}` {
		t.Errorf("recipe content = %q", data)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	// The recipe may hold a LUKS passphrase / user password — never readable
	// by other users.
	if info.Mode().Perm() != 0o600 {
		t.Errorf("recipe mode = %v, want 0600", info.Mode().Perm())
	}
}

func TestWriteRecipeFallsBackToTmp(t *testing.T) {
	t.Setenv("XDG_RUNTIME_DIR", "")
	path, err := writeRecipe([]byte("{}"))
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(recipeDir(path))
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "{}" {
		t.Errorf("recipe content = %q", data)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("recipe mode = %v, want 0600", info.Mode().Perm())
	}
}

// The recipe path is handed to sudo/pkexec fisherman, so the DIRECTORY has to
// be as private and as unguessable as the file. A fixed <base>/tuna-installer
// created with os.MkdirAll adopted a pre-existing 0777 directory as-is, which
// let a local user swap the recipe root then reads.
func TestWriteRecipeDirectoryIsPrivate(t *testing.T) {
	t.Setenv("XDG_RUNTIME_DIR", t.TempDir())

	path, err := writeRecipe([]byte("{}"))
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(recipeDir(path))

	info, err := os.Stat(recipeDir(path))
	if err != nil {
		t.Fatal(err)
	}
	if perm := info.Mode().Perm(); perm != 0o700 {
		t.Errorf("recipe directory mode = %v, want 0700", perm)
	}
}

func TestWriteRecipeDirectoryIsNotReused(t *testing.T) {
	base := t.TempDir()
	t.Setenv("XDG_RUNTIME_DIR", base)

	first, err := writeRecipe([]byte("{}"))
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(recipeDir(first))
	second, err := writeRecipe([]byte("{}"))
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(recipeDir(second))

	if recipeDir(first) == recipeDir(second) {
		t.Errorf("both recipes landed in %s; the directory must be per-call", recipeDir(first))
	}
	// The old fixed name must not be created at all.
	if _, err := os.Stat(filepath.Join(base, "tuna-installer")); !os.IsNotExist(err) {
		t.Errorf("fixed directory %s/tuna-installer should no longer be used", base)
	}
}

// A pre-created world-writable directory at the old fixed name must not be
// adopted — os.MkdirAll used to return nil for it without fixing the mode.
func TestWriteRecipeIgnoresPrecreatedWorldWritableDir(t *testing.T) {
	base := t.TempDir()
	t.Setenv("XDG_RUNTIME_DIR", base)

	hostile := filepath.Join(base, "tuna-installer")
	if err := os.Mkdir(hostile, 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(hostile, 0o777); err != nil { // defeat the umask
		t.Fatal(err)
	}

	path, err := writeRecipe([]byte("{}"))
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(recipeDir(path))

	if recipeDir(path) == hostile {
		t.Fatalf("recipe was written into the pre-created 0777 directory %s", hostile)
	}
	info, err := os.Stat(recipeDir(path))
	if err != nil {
		t.Fatal(err)
	}
	if perm := info.Mode().Perm(); perm != 0o700 {
		t.Errorf("recipe directory mode = %v, want 0700", perm)
	}
}

// A symlink planted at the recipe path must make the write fail loudly rather
// than redirect it: os.WriteFile followed symlinks, O_EXCL|O_NOFOLLOW does not.
func TestWriteRecipeRefusesPreplantedFile(t *testing.T) {
	base := t.TempDir()
	t.Setenv("XDG_RUNTIME_DIR", base)

	path, err := writeRecipe([]byte("{}"))
	if err != nil {
		t.Fatal(err)
	}
	dir := recipeDir(path)
	defer os.RemoveAll(dir)

	// Simulate an attacker who owns the directory: replace the recipe with a
	// symlink and write again into the same place.
	victim := filepath.Join(base, "victim")
	if err := os.WriteFile(victim, []byte("original"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(victim, path); err != nil {
		t.Fatal(err)
	}

	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL|syscall.O_NOFOLLOW, 0o600)
	if err == nil {
		f.Close()
		t.Fatal("open of a pre-planted symlink succeeded; it must fail")
	}
	data, err := os.ReadFile(victim)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "original" {
		t.Errorf("victim file was clobbered: %q", data)
	}
}
