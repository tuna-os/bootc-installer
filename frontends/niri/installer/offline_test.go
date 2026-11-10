package main

// Unit tests for offline.go: the ONE resolver that decides which fisherman
// runs and how (#290).

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"syscall"
	"testing"
)

const stagedForTests = "/home/u/.var/app/org.example.Installer/cache/bootc-installer/fisherman"

// The argv for native, Flatpak and live media, for the install and for the
// unprivileged commands.
func TestFishermanArgv(t *testing.T) {
	native := Fisherman{Path: nativeFisherman}
	flatpak := Fisherman{Flatpak: true, Path: stagedForTests}
	cases := []struct {
		name string
		got  []string
		want []string
	}{
		{"native install: pkexec",
			native.InstallArgv(false),
			[]string{"bash", "-c", `pkexec /usr/local/bin/fisherman -; exit $?`}},
		{"live install: sudo -n",
			native.InstallArgv(true),
			[]string{"bash", "-c", `sudo -n /usr/local/bin/fisherman -; exit $?`}},
		{"Flatpak install: pkexec on the host, the staged binary",
			flatpak.InstallArgv(false),
			[]string{"flatpak-spawn", "--host", "bash", "-c", `pkexec "$1" -; exit $?`, "bash", stagedForTests}},
		{"Flatpak install on live media: still pkexec, still staged",
			flatpak.InstallArgv(true),
			[]string{"flatpak-spawn", "--host", "bash", "-c", `pkexec "$1" -; exit $?`, "bash", stagedForTests}},
		{"native probe", native.Argv("probe", "--json"),
			[]string{"/usr/local/bin/fisherman", "probe", "--json"}},
		{"Flatpak probe: the staged binary, no escalation", flatpak.Argv("probe", "--json"),
			[]string{"flatpak-spawn", "--host", stagedForTests, "probe", "--json"}},
	}
	for _, c := range cases {
		if !reflect.DeepEqual(c.got, c.want) {
			t.Errorf("%s:\n got %q\nwant %q", c.name, c.got, c.want)
		}
	}
}

func TestResolveFishermanNativeIsTheHostPath(t *testing.T) {
	called := false
	got, err := resolveFishermanFor(false, "", "/nonexistent", func(string) (string, error) {
		called = true
		return "", nil
	})
	if err != nil || got != (Fisherman{Path: "/usr/local/bin/fisherman"}) {
		t.Fatalf("got %+v, %v", got, err)
	}
	if called {
		t.Error("a native run staged or verified something")
	}
}

// In a Flatpak the bundled binary is copied to
// $XDG_CACHE_HOME/bootc-installer/fisherman, and the host's checksum of that
// path must be the bundled binary's.
func TestResolveFishermanStagesAndVerifiesInAFlatpak(t *testing.T) {
	cache := filepath.Join(t.TempDir(), "cache")
	if err := os.Mkdir(cache, 0o700); err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(t.TempDir(), "fisherman")
	if err := os.WriteFile(source, []byte("#!/bin/sh\necho bundled\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	var asked []string
	onHost := func(path string) (string, error) {
		asked = append(asked, path)
		return sha256File(path)
	}
	got, err := resolveFishermanFor(true, cache, source, onHost)
	if err != nil {
		t.Fatal(err)
	}
	staged := filepath.Join(cache, "bootc-installer", "fisherman")
	if got != (Fisherman{Flatpak: true, Path: staged}) {
		t.Errorf("resolved %+v, want the staged path %s", got, staged)
	}
	if !reflect.DeepEqual(asked, []string{staged}) {
		t.Errorf("the host was asked about %v, want the staged path once", asked)
	}
	data, _ := os.ReadFile(staged)
	if string(data) != "#!/bin/sh\necho bundled\n" {
		t.Errorf("staged bytes = %q", data)
	}
	if info, _ := os.Stat(staged); info.Mode().Perm() != 0o700 {
		t.Errorf("staged mode = %v, want 0700", info.Mode().Perm())
	}
	if info, _ := os.Stat(filepath.Dir(staged)); info.Mode().Perm() != 0o700 {
		t.Errorf("staging directory mode = %v, want 0700", info.Mode().Perm())
	}

	// A second run with the same binary copies nothing but verifies again.
	before, _ := os.Stat(staged)
	if _, err := resolveFishermanFor(true, cache, source, onHost); err != nil {
		t.Fatal(err)
	}
	after, _ := os.Stat(staged)
	if !os.SameFile(before, after) || len(asked) != 2 {
		t.Errorf("second run: same file = %v, host checks = %d", os.SameFile(before, after), len(asked))
	}

	// A new bundled binary replaces the staged one.
	if err := os.WriteFile(source, []byte("#!/bin/sh\necho newer\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := resolveFishermanFor(true, cache, source, onHost); err != nil {
		t.Fatal(err)
	}
	if data, _ := os.ReadFile(staged); string(data) != "#!/bin/sh\necho newer\n" {
		t.Errorf("staged bytes after an update = %q", data)
	}
}

// What the host reads is what runs as root. A different checksum there, or
// no answer, means nothing may run.
func TestResolveFishermanRefusesWhatTheHostDoesNotConfirm(t *testing.T) {
	source := filepath.Join(t.TempDir(), "fisherman")
	if err := os.WriteFile(source, []byte("bundled"), 0o755); err != nil {
		t.Fatal(err)
	}
	for name, onHost := range map[string]hostSHA256{
		"different bytes": func(string) (string, error) { return strings.Repeat("0", 64), nil },
		"no answer":       func(string) (string, error) { return "", errors.New("portal is down") },
	} {
		cache := t.TempDir()
		if _, err := resolveFishermanFor(true, cache, source, onHost); err == nil {
			t.Errorf("%s: resolved a fisherman the host did not confirm", name)
		}
	}
}

// Never HOME/.cache: the path comes from XDG_CACHE_HOME, and a Flatpak with
// none (or a relative one) has no safe place to stage to.
func TestResolveFishermanNeedsAnAbsoluteCacheHome(t *testing.T) {
	source := filepath.Join(t.TempDir(), "fisherman")
	if err := os.WriteFile(source, []byte("bundled"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", t.TempDir())
	for _, cache := range []string{"", "relative/cache"} {
		if _, err := resolveFishermanFor(true, cache, source, sha256File); err == nil {
			t.Errorf("XDG_CACHE_HOME=%q: staged somewhere", cache)
		}
	}
	if entries, _ := os.ReadDir(os.Getenv("HOME")); len(entries) != 0 {
		t.Errorf("something was written below HOME: %v", entries)
	}
}

// A staging path somebody else could have prepared is refused: a symlink, or
// a directory that others can write.
func TestResolveFishermanRefusesAnUnsafeStagingPath(t *testing.T) {
	source := filepath.Join(t.TempDir(), "fisherman")
	if err := os.WriteFile(source, []byte("bundled"), 0o755); err != nil {
		t.Fatal(err)
	}

	cache := t.TempDir()
	elsewhere := t.TempDir()
	if err := os.Symlink(elsewhere, filepath.Join(cache, "bootc-installer")); err != nil {
		t.Fatal(err)
	}
	if _, err := resolveFishermanFor(true, cache, source, sha256File); err == nil {
		t.Error("staged through a symlinked directory")
	}
	if entries, _ := os.ReadDir(elsewhere); len(entries) != 0 {
		t.Errorf("wrote through the symlink: %v", entries)
	}

	cache = t.TempDir()
	dir := filepath.Join(cache, "bootc-installer")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, 0o777); err != nil {
		t.Fatal(err)
	}
	if _, err := resolveFishermanFor(true, cache, source, sha256File); err == nil {
		t.Error("staged into a world-writable directory")
	}

	cache = t.TempDir()
	dir = filepath.Join(cache, "bootc-installer")
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("/bin/true", filepath.Join(dir, "fisherman")); err != nil {
		t.Fatal(err)
	}
	if _, err := resolveFishermanFor(true, cache, source, sha256File); err == nil {
		t.Error("staged over a symlink")
	}
}

// The one resolver: nothing else in the backend names the fisherman path or
// builds an escalation.
func TestOnlyTheResolverNamesFisherman(t *testing.T) {
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	for _, file := range files {
		if file == "offline.go" || strings.HasSuffix(file, "_test.go") {
			continue
		}
		data, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		for n, line := range strings.Split(string(data), "\n") {
			code, _, _ := strings.Cut(line, "//")
			for _, banned := range []string{`"/usr/local/bin/fisherman"`, `"/app/bin/fisherman"`, `"pkexec"`, `"sudo"`} {
				if strings.Contains(code, banned) {
					t.Errorf("%s:%d names %s outside the resolver", file, n+1, banned)
				}
			}
		}
	}
}

// The wrapper's bash for real (everything after `flatpak-spawn --host`),
// pkexec stubbed on PATH: the recipe written to the wrapper's stdin is what
// fisherman reads, the staged path and `-` are its only arguments, and
// output and status pass through.
func TestFlatpakWrapperPassesStdinOutputAndStatusThrough(t *testing.T) {
	dir := t.TempDir()
	got := filepath.Join(dir, "stdin")
	writeStub(t, dir, "pkexec", "#!/bin/sh\nprintf '%s|%s\\n' \"$1\" \"$2\"\ncat > \""+got+"\"\necho to-stderr >&2\nexit 7\n")
	staged := filepath.Join(dir, "a dir with spaces", "fisherman")
	argv := Fisherman{Flatpak: true, Path: staged}.InstallArgv(false)[2:]

	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Env = append(os.Environ(), pathWith(dir))
	cmd.Dir = dir
	cmd.Stdin = strings.NewReader(`{"hostname":"h","encryption":{"type":"luks-passphrase","passphrase":"s3cret"}}`)
	var stdout, stderr strings.Builder
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 7 {
		t.Fatalf("exit = %v, want status 7", err)
	}
	if got, want := stdout.String(), staged+"|-\n"; got != want {
		t.Errorf("stdout = %q, want %q", got, want)
	}
	if stderr.String() != "to-stderr\n" {
		t.Errorf("stderr = %q", stderr.String())
	}
	read, _ := os.ReadFile(got)
	if !strings.Contains(string(read), "s3cret") {
		t.Errorf("fisherman read %q on stdin, want the recipe", read)
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
	// 128 + the signal: what `install` exits with for a killed wrapper.
	if code := exitCodeOf(err); code != 128+int(syscall.SIGTERM) {
		t.Errorf("exitCodeOf = %d, want 143", code)
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
