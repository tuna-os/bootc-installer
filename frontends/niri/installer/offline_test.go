package main

// Unit tests for offline.go — offline-install and sandbox plumbing.
// Contract: ../../INSTALLER-FRONTENDS.md §3 (privileges) and §4 (offline).

import (
	"errors"
	"os"
	"os/exec"
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

// Not `flatpak-spawn --host pkexec`: fisherman's parent would be the host's
// session helper, and it could never be cancelled.
func TestFishermanCommandRunsPkexecInsideAHostBashInFlatpak(t *testing.T) {
	got := fishermanCommandFor(true)
	want := []string{"flatpak-spawn", "--host", "bash", "-c",
		`pkexec /usr/local/bin/fisherman "$1"; exit $?`, "--"}
	if strings.Join(got, "\x00") != strings.Join(want, "\x00") {
		t.Fatalf("fishermanCommandFor(true) = %q, want %q", got, want)
	}
}

// The wrapper's bash for real (everything after `flatpak-spawn --host`),
// pkexec stubbed on PATH, and a recipe path a shell would act on if it were
// interpolated into the script.
func TestFlatpakWrapperPassesOutputAndStatusThrough(t *testing.T) {
	dir := t.TempDir()
	writeStub(t, dir, "pkexec", "#!/bin/sh\nprintf '%s|%s\\n' \"$1\" \"$2\"\necho to-stderr >&2\nexit 7\n")
	recipe := filepath.Join(dir, "a b $(touch pwned) ;x.json")
	argv := append(fishermanCommandFor(true), recipe)[2:]

	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Env = append(os.Environ(), pathWith(dir))
	cmd.Dir = dir
	var stdout, stderr strings.Builder
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 7 {
		t.Fatalf("exit = %v, want status 7", err)
	}
	if got, want := stdout.String(), "/usr/local/bin/fisherman|"+recipe+"\n"; got != want {
		t.Errorf("stdout = %q, want %q", got, want)
	}
	if stderr.String() != "to-stderr\n" {
		t.Errorf("stderr = %q", stderr.String())
	}
	if _, err := os.Stat(filepath.Join(dir, "pwned")); err == nil {
		t.Error("the recipe path was executed as shell")
	}
}

func TestWrapperLeadsItsOwnProcessGroupAndGetsForwardedSignals(t *testing.T) {
	cmd := wrapperCommand([]string{"sleep", "30"})
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = cmd.Process.Kill() }()
	pid := cmd.Process.Pid
	pgid, err := syscall.Getpgid(pid)
	if err != nil {
		t.Fatal(err)
	}
	if pgid != pid || pgid == syscall.Getpgrp() {
		t.Fatalf("wrapper pgid = %d, pid = %d, ours = %d", pgid, pid, syscall.Getpgrp())
	}

	sigs := make(chan os.Signal, 1)
	go forwardSignals(pid, sigs)
	sigs <- syscall.SIGTERM
	close(sigs)
	err = cmd.Wait()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("wait = %v, want the wrapper killed", err)
	}
	ws := exitErr.Sys().(syscall.WaitStatus)
	if !ws.Signaled() || ws.Signal() != syscall.SIGTERM {
		t.Fatalf("wrapper status = %v, want SIGTERM", ws)
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
