package main

// Tests for the host-command paths in offline.go — the functions that shell
// out to podman and bootc. They are driven with stub executables placed on
// PATH rather than the real tools, so they run anywhere.

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// stubBin writes an executable script into a directory that is prepended to
// PATH for the duration of the test, and returns that directory.
func stubBin(t *testing.T, name, script string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	return dir
}

// podmanStub answers `podman images --root <store> --format json` with the
// contents of <store>/images.json, and fails when that file is absent — which
// is how a store root that podman cannot read behaves.
const podmanStub = `#!/bin/sh
root=""
while [ $# -gt 0 ]; do
	case "$1" in
		--root) root="$2"; shift 2 ;;
		*) shift ;;
	esac
done
if [ -n "$PODMAN_CALL_LOG" ]; then
	echo "$root" >> "$PODMAN_CALL_LOG"
fi
[ -f "$root/images.json" ] || exit 1
cat "$root/images.json"
`

// store creates a store directory holding the podman output the stub replays.
func store(t *testing.T, base, name, imagesJSON string) string {
	t.Helper()
	dir := filepath.Join(base, name)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if imagesJSON != "" {
		if err := os.WriteFile(filepath.Join(dir, "images.json"), []byte(imagesJSON), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return dir
}

func TestOfflineImagesCollectsEveryNameAcrossStores(t *testing.T) {
	stubBin(t, "podman", podmanStub)
	base := t.TempDir()
	a := store(t, base, "a", `[{"Names":["localhost/skipjack:latest","localhost/skipjack:41"]}]`)
	b := store(t, base, "b", `[{"Names":["localhost/bonito:latest"]}]`)

	got := offlineImages([]string{a, b})

	want := []string{"localhost/skipjack:latest", "localhost/skipjack:41", "localhost/bonito:latest"}
	if len(got) != len(want) {
		t.Fatalf("offlineImages() = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("offlineImages() = %v, want %v", got, want)
		}
	}
}

// The same image is commonly present in more than one embedded store; the UI
// must not offer it twice.
func TestOfflineImagesDeduplicatesAcrossStores(t *testing.T) {
	stubBin(t, "podman", podmanStub)
	base := t.TempDir()
	a := store(t, base, "a", `[{"Names":["localhost/skipjack:latest"]}]`)
	b := store(t, base, "b", `[{"Names":["localhost/skipjack:latest"]},{"Names":["localhost/bonito:latest"]}]`)

	got := offlineImages([]string{a, b})

	if len(got) != 2 || got[0] != "localhost/skipjack:latest" || got[1] != "localhost/bonito:latest" {
		t.Fatalf("offlineImages() = %v, want each ref exactly once", got)
	}
}

func TestOfflineImagesQueriesEveryStoreRoot(t *testing.T) {
	stubBin(t, "podman", podmanStub)
	base := t.TempDir()
	log := filepath.Join(base, "calls.log")
	t.Setenv("PODMAN_CALL_LOG", log)
	a := store(t, base, "a", `[]`)
	b := store(t, base, "b", `[]`)

	offlineImages([]string{a, b})

	data, err := os.ReadFile(log)
	if err != nil {
		t.Fatalf("podman was never invoked: %v", err)
	}
	called := strings.Fields(string(data))
	if len(called) != 2 || called[0] != a || called[1] != b {
		t.Errorf("podman --root calls = %v, want [%s %s]", called, a, b)
	}
}

// One unreadable store must not hide the images in the others: an offline
// install still has to be offerable when a second medium is missing.
func TestOfflineImagesSkipsAStoreThatPodmanCannotRead(t *testing.T) {
	stubBin(t, "podman", podmanStub)
	base := t.TempDir()
	broken := store(t, base, "broken", "")
	good := store(t, base, "good", `[{"Names":["localhost/skipjack:latest"]}]`)

	got := offlineImages([]string{broken, good})

	if len(got) != 1 || got[0] != "localhost/skipjack:latest" {
		t.Fatalf("offlineImages() = %v, want the readable store's image", got)
	}
}

func TestOfflineImagesSkipsAStoreWithUnparseableOutput(t *testing.T) {
	stubBin(t, "podman", podmanStub)
	base := t.TempDir()
	garbage := store(t, base, "garbage", `not json at all`)
	good := store(t, base, "good", `[{"Names":["localhost/bonito:latest"]}]`)

	got := offlineImages([]string{garbage, good})

	if len(got) != 1 || got[0] != "localhost/bonito:latest" {
		t.Fatalf("offlineImages() = %v, want only the parseable store's image", got)
	}
}

func TestOfflineImagesIgnoresImagesWithoutNames(t *testing.T) {
	stubBin(t, "podman", podmanStub)
	base := t.TempDir()
	// A dangling <none>:<none> layer has no Names at all.
	only := store(t, base, "only", `[{"Names":null},{"Names":["localhost/skipjack:latest"]}]`)

	got := offlineImages([]string{only})

	if len(got) != 1 || got[0] != "localhost/skipjack:latest" {
		t.Fatalf("offlineImages() = %v, want the one named image", got)
	}
}

// bootcStub replays $BOOTC_JSON, or fails when $BOOTC_FAIL is set.
const bootcStub = `#!/bin/sh
[ -n "$BOOTC_FAIL" ] && exit 1
printf '%s' "$BOOTC_JSON"
`

// liveISOImage's answer decides whether a recipe is allowed to omit `image`.
// Claiming live-ISO mode off live media would let an install proceed with no
// image to install, so every uncertain input must resolve to "".
func requireNotLiveMedia(t *testing.T) {
	t.Helper()
	if _, err := os.Stat("/run/ostree-live"); err == nil {
		t.Skip("running from live media")
	}
	if cmdline, err := os.ReadFile("/proc/cmdline"); err == nil &&
		strings.Contains(string(cmdline), "rd.live.image") {
		t.Skip("running from live media")
	}
}

func TestLiveISOImageEmptyWhenBootcFails(t *testing.T) {
	stubBin(t, "bootc", bootcStub)
	t.Setenv("BOOTC_FAIL", "1")

	if got := liveISOImage(); got != "" {
		t.Errorf("liveISOImage() = %q, want empty when bootc fails", got)
	}
}

func TestLiveISOImageEmptyOnUnparseableStatus(t *testing.T) {
	stubBin(t, "bootc", bootcStub)
	t.Setenv("BOOTC_JSON", "not json")

	if got := liveISOImage(); got != "" {
		t.Errorf("liveISOImage() = %q, want empty on unparseable status", got)
	}
}

func TestLiveISOImageEmptyWhenNothingIsBooted(t *testing.T) {
	stubBin(t, "bootc", bootcStub)
	t.Setenv("BOOTC_JSON", `{"status":{"booted":null}}`)

	if got := liveISOImage(); got != "" {
		t.Errorf("liveISOImage() = %q, want empty with no booted image", got)
	}
}

// The decisive case: bootc reports a booted image, but the machine is an
// installed system rather than live media. The ref must still be withheld.
func TestLiveISOImageWithholdsTheRefOffLiveMedia(t *testing.T) {
	requireNotLiveMedia(t)
	stubBin(t, "bootc", bootcStub)
	t.Setenv("BOOTC_JSON",
		`{"status":{"booted":{"image":{"image":{"image":"ghcr.io/tuna-os/skipjack:latest"}}}}}`)

	if got := liveISOImage(); got != "" {
		t.Errorf("liveISOImage() = %q off live media, want empty", got)
	}
}
