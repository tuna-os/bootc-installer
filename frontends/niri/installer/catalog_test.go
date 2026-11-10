package main

// Tests for the image catalog reader against the shared contract
// (shared/catalog/README.md). The fixture catalog and the expected answers
// are the ones every frontend reads; nothing here imports the reference
// resolver.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

var (
	sharedCatalogFixture  = filepath.Join("..", "..", "..", "shared", "catalog", "fixtures", "catalog.json")
	sharedCatalogExpected = filepath.Join("..", "..", "..", "shared", "catalog", "fixtures", "expected.json")
)

type expectedCatalog struct {
	SearchPaths []struct {
		InFlatpak     bool     `json:"in_flatpak"`
		XDGConfigHome string   `json:"xdg_config_home"`
		Paths         []string `json:"paths"`
	} `json:"search_paths"`
	DefaultSelection []struct {
		Branding string  `json:"branding_default_image"`
		Catalog  string  `json:"catalog_default_image"`
		Selected *string `json:"selected"`
	} `json:"default_selection"`
	UnknownImage struct {
		Imgref            string `json:"imgref"`
		NeedsUserCreation bool   `json:"needs_user_creation"`
	} `json:"unknown_image"`
	Leaves []struct {
		Imgref string         `json:"imgref"`
		Leaf   map[string]any `json:"leaf"`
		Cases  []struct {
			Inputs Machine        `json:"inputs"`
			Recipe map[string]any `json:"recipe"`
			Absent []string       `json:"absent"`
		} `json:"cases"`
	} `json:"leaves"`
}

func loadShared(t *testing.T) (Catalog, expectedCatalog) {
	t.Helper()
	data, err := os.ReadFile(sharedCatalogFixture)
	if err != nil {
		t.Fatalf("read the shared fixture catalog: %v", err)
	}
	catalog, err := parseCatalog(data)
	if err != nil {
		t.Fatalf("parse the shared fixture catalog: %v", err)
	}
	var want expectedCatalog
	data, err = os.ReadFile(sharedCatalogExpected)
	if err != nil {
		t.Fatalf("read expected.json: %v", err)
	}
	if err := json.Unmarshal(data, &want); err != nil {
		t.Fatal(err)
	}
	if len(want.Leaves) < 5 || len(want.SearchPaths) < 2 || len(want.DefaultSelection) < 4 {
		t.Fatalf("expected.json is smaller than this test understands")
	}
	return catalog, want
}

// asJSON is a value as the QML reads it: through encoding/json.
func asJSON(t *testing.T, v any) map[string]any {
	t.Helper()
	data, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestSharedCatalogSearchPaths(t *testing.T) {
	_, want := loadShared(t)
	for _, c := range want.SearchPaths {
		got := catalogSearchPaths(c.InFlatpak, c.XDGConfigHome, "<bundled>")
		if !reflect.DeepEqual(got, c.Paths) {
			t.Errorf("flatpak=%v\n got %v\nwant %v", c.InFlatpak, got, c.Paths)
		}
	}
	// #298: in a Flatpak the system catalog is the HOST's.
	for _, path := range catalogSearchPaths(true, "/cfg")[:2] {
		if !strings.HasPrefix(path, "/run/host/etc/") {
			t.Errorf("%s is not below /run/host in a Flatpak", path)
		}
	}
}

// Every resolved field of every leaf, as the QML receives it.
func TestSharedCatalogLeaves(t *testing.T) {
	catalog, want := loadShared(t)
	if len(catalog.Leaves) != len(want.Leaves) {
		t.Fatalf("%d leaves, want %d", len(catalog.Leaves), len(want.Leaves))
	}
	for i, expected := range want.Leaves {
		got := asJSON(t, catalog.Leaves[i])
		if got["imgref"] != expected.Imgref {
			t.Errorf("leaf %d is %v, want %s (catalog order)", i, got["imgref"], expected.Imgref)
			continue
		}
		for key, value := range expected.Leaf {
			if !reflect.DeepEqual(got[key], value) {
				t.Errorf("%s: %s = %#v, want %#v", expected.Imgref, key, got[key], value)
			}
		}
	}
}

// The recipe keys for every leaf on every machine of the fixture: `recipe`
// keys must match, `absent` keys must not exist. The fragment is run through
// the Recipe struct too, because that is what fisherman receives.
func TestSharedCatalogRecipes(t *testing.T) {
	catalog, want := loadShared(t)
	empty := map[string]any{"bootloader": "", "composeFsBackend": false, "imageType": "bootc"}
	cases := 0
	for i, expected := range want.Leaves {
		for _, c := range expected.Cases {
			cases++
			fragment := recipeFragment(catalog.Leaves[i], c.Inputs)
			if !reflect.DeepEqual(asJSON(t, fragment), c.Recipe) {
				t.Errorf("%s %+v: fragment\n got %v\nwant %v", expected.Imgref, c.Inputs, asJSON(t, fragment), c.Recipe)
			}
			for _, key := range c.Absent {
				if _, ok := fragment[key]; ok {
					t.Errorf("%s: %s must be left out, found %#v", expected.Imgref, key, fragment[key])
				}
			}

			// What reaches fisherman: the wizard's own keys plus the
			// fragment, through decodeRecipe and back out.
			sent := map[string]any{"disk": "/dev/vda", "hostname": "box", "filesystem": "xfs"}
			for key, value := range fragment {
				sent[key] = value
			}
			raw, _ := json.Marshal(sent)
			recipe, err := decodeRecipe(raw)
			if err != nil {
				t.Fatalf("%s: the backend refuses its own fragment: %v", expected.Imgref, err)
			}
			final := asJSON(t, recipe)
			for key, value := range c.Recipe {
				got, ok := final[key]
				if !ok {
					if fallback, isEmpty := empty[key]; isEmpty {
						got = fallback
					}
				}
				if !reflect.DeepEqual(got, value) {
					t.Errorf("%s %+v: recipe %s = %#v, want %#v", expected.Imgref, c.Inputs, key, got, value)
				}
			}
			for _, key := range c.Absent {
				if _, ok := final[key]; ok {
					t.Errorf("%s: recipe has %s = %#v, and it must be left out", expected.Imgref, key, final[key])
				}
			}
		}
	}
	if cases < 10 {
		t.Fatalf("only %d cases ran", cases)
	}
}

func TestSharedCatalogDefaultSelection(t *testing.T) {
	catalog, want := loadShared(t)
	for _, c := range want.DefaultSelection {
		probe := catalog
		// A row with no catalog default applies to the catalog without one.
		probe.DefaultImage = c.Catalog
		got := defaultImgref(probe, c.Branding)
		wantRef := ""
		if c.Selected != nil {
			wantRef = *c.Selected
		}
		if got != wantRef {
			t.Errorf("branding %q, catalog %q: selected %q, want %q", c.Branding, c.Catalog, got, wantRef)
		}
	}
	if catalog.DefaultImage != "registry.example/os/atlas:stable" {
		t.Errorf("the fixture's default_image was read as %q", catalog.DefaultImage)
	}
}

func TestSharedCatalogAccountFlag(t *testing.T) {
	catalog, want := loadShared(t)
	if got := needsUserCreation(catalog.Leaves, want.UnknownImage.Imgref); got != want.UnknownImage.NeedsUserCreation {
		t.Errorf("unknown image: needs_user_creation = %v, want %v", got, want.UnknownImage.NeedsUserCreation)
	}
	for _, expected := range want.Leaves {
		flag, _ := expected.Leaf["needs_user_creation"].(bool)
		if got := needsUserCreation(catalog.Leaves, expected.Imgref); got != flag {
			t.Errorf("%s: needs_user_creation = %v, want %v", expected.Imgref, got, flag)
		}
		// The NVIDIA variant of a leaf is that leaf (the live image can be it).
		if nvidia, _ := expected.Leaf["nvidia_imgref"].(string); nvidia != "" {
			if got := needsUserCreation(catalog.Leaves, nvidia); got != flag {
				t.Errorf("%s: needs_user_creation = %v, want the leaf's %v", nvidia, got, flag)
			}
		}
	}
}

func writeCatalog(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "images.json")
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func runCatalog(t *testing.T, env []string, path string) (map[string]any, string, int) {
	t.Helper()
	env = append([]string{imagesPathEnv + "=" + path, "XDG_CONFIG_HOME=" + t.TempDir(),
		brandingEnvFile + "=/nonexistent/branding.json", writeFakeProbe(t, false)}, env...)
	got := runCLI(t, env, "catalog")
	var doc map[string]any
	if got.code == 0 {
		if err := json.Unmarshal([]byte(got.stdout), &doc); err != nil {
			t.Fatalf("catalog stdout is not JSON: %v\n%s", err, got.stdout)
		}
	}
	return doc, got.stderr, got.code
}

// The `catalog` answer for the shared fixture, end to end: each leaf carries
// the recipe keys for this machine, and the catalog's default_image is the
// selection when the branding names none.
func TestCatalogCommandAnswersForTheSharedFixture(t *testing.T) {
	fixture, _ := filepath.Abs(sharedCatalogFixture)
	doc, stderr, code := runCatalog(t, nil, fixture)
	if code != 0 {
		t.Fatalf("code = %d, stderr = %q", code, stderr)
	}
	if doc["path"] != fixture || doc["selected"] != "registry.example/os/atlas:stable" {
		t.Errorf("path = %v, selected = %v", doc["path"], doc["selected"])
	}
	leaves, _ := doc["leaves"].([]any)
	_, want := loadShared(t)
	if len(leaves) != len(want.Leaves) {
		t.Fatalf("%d leaves, want %d", len(leaves), len(want.Leaves))
	}
	for i, expected := range want.Leaves {
		leaf := leaves[i].(map[string]any)
		recipe, _ := leaf["recipe"].(map[string]any)
		if recipe["targetImgref"] != expected.Imgref {
			t.Errorf("%s: recipe.targetImgref = %v", expected.Imgref, recipe["targetImgref"])
		}
		if leaf["breadcrumb"] != expected.Leaf["breadcrumb"] || leaf["label"] != expected.Leaf["label"] {
			t.Errorf("%s: label %v, breadcrumb %v", expected.Imgref, leaf["label"], leaf["breadcrumb"])
		}
	}
	if doc["live_leaf"] != nil || doc["live_needs_user_creation"] != true {
		t.Errorf("off live media: live_leaf = %v, live_needs_user_creation = %v",
			doc["live_leaf"], doc["live_needs_user_creation"])
	}
}

// The branding's default_image wins over the catalog's; an image neither
// names leaves nothing selected (#289: never the first row).
func TestCatalogCommandSelection(t *testing.T) {
	fixture, _ := filepath.Abs(sharedCatalogFixture)
	branding := filepath.Join(t.TempDir(), "branding.json")
	if err := os.WriteFile(branding, []byte(`{"name":"Atlas","default_image":"registry.example/os/atlas:beta"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	doc, _, _ := runCatalog(t, []string{brandingEnvFile + "=" + branding}, fixture)
	if doc["selected"] != "registry.example/os/atlas:beta" {
		t.Errorf("selected = %v, want the branding's default_image", doc["selected"])
	}

	bare := writeCatalog(t, `{"images": [
		{"name": "A", "imgref": "registry.example/os/a:1"},
		{"name": "B", "imgref": "registry.example/os/b:1"}]}`)
	doc, _, _ = runCatalog(t, nil, bare)
	if doc["selected"] != "" {
		t.Errorf("selected = %v with no default anywhere, want nothing", doc["selected"])
	}
}

// On live media the answer names the leaf of the booted image: its account
// flag is the wizard's, and an image the catalog does not have needs one.
func TestCatalogCommandOnLiveMedia(t *testing.T) {
	fixture, _ := filepath.Abs(sharedCatalogFixture)
	probe := func(image string) string {
		path := filepath.Join(t.TempDir(), "probe.json")
		body := `{"protocol_version":1,"disks":[],"tpm":{"usable":false},"system":{"unmet":[]},` +
			`"live":{"is_live":true,"live_image":"` + image + `"},"offline":{"images":["` + image + `"]}}`
		if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		return fakeProbeEnv + "=" + path
	}
	doc, _, _ := runCatalog(t, []string{probe("registry.example/os/atlas:beta")}, fixture)
	live, _ := doc["live_leaf"].(map[string]any)
	if live["imgref"] != "registry.example/os/atlas:beta" || doc["live_needs_user_creation"] != false {
		t.Errorf("live_leaf = %v, live_needs_user_creation = %v", live["imgref"], doc["live_needs_user_creation"])
	}
	machine, _ := doc["machine"].(map[string]any)
	if machine["is_live"] != true {
		t.Errorf("machine = %v", machine)
	}

	doc, _, _ = runCatalog(t, []string{probe("registry.example/os/elsewhere:1")}, fixture)
	if doc["live_leaf"] != nil || doc["live_needs_user_creation"] != true {
		t.Errorf("unknown live image: live_leaf = %v, live_needs_user_creation = %v",
			doc["live_leaf"], doc["live_needs_user_creation"])
	}
}

// A Flatpak list the backend cannot read offline is null, never []: the
// recipe then has no `flatpaks`, and fisherman applies its own default. A
// string of ids is not a list either.
func TestCatalogFlatpakListsFollowTheOfflineRule(t *testing.T) {
	catalog, err := parseCatalog([]byte(`{
		"aliases": {"apps": ["org.example.A"], "remote": "https://example.invalid/Brewfile"},
		"fallback_flatpaks": ["org.example.NeverSent"],
		"images": [
			{"name": "List", "imgref": "r.example/a:1", "flatpaks": ["org.example.B"]},
			{"name": "Empty", "imgref": "r.example/b:1", "flatpaks": []},
			{"name": "Alias", "imgref": "r.example/c:1", "flatpaks": "@apps"},
			{"name": "Remote", "imgref": "r.example/d:1", "flatpaks": "@remote"},
			{"name": "URL", "imgref": "r.example/e:1", "flatpaks": "https://example.invalid/list"},
			{"name": "Missing", "imgref": "r.example/f:1", "flatpaks": "@nowhere"},
			{"name": "String", "imgref": "r.example/g:1", "flatpaks": "org.example.C org.example.D"},
			{"name": "None", "imgref": "r.example/h:1"}
		]}`))
	if err != nil {
		t.Fatal(err)
	}
	want := map[string][]string{
		"List": {"org.example.B"}, "Empty": {}, "Alias": {"org.example.A"},
		"Remote": nil, "URL": nil, "Missing": nil, "String": nil, "None": nil,
	}
	for _, leaf := range catalog.Leaves {
		expected, known := want[leaf.Name]
		if !known {
			t.Fatalf("unexpected leaf %q", leaf.Name)
		}
		_, inRecipe := recipeFragment(leaf, Machine{})["flatpaks"]
		if expected == nil {
			if leaf.Flatpaks != nil || inRecipe {
				t.Errorf("%s: flatpaks = %v, want none and no recipe key", leaf.Name, leaf.Flatpaks)
			}
			continue
		}
		if leaf.Flatpaks == nil || !reflect.DeepEqual(*leaf.Flatpaks, expected) || !inRecipe {
			t.Errorf("%s: flatpaks = %v, want %v in the recipe", leaf.Name, leaf.Flatpaks, expected)
		}
	}
	raw, _ := json.Marshal(catalog.Leaves)
	if strings.Contains(string(raw), "NeverSent") {
		t.Error("fallback_flatpaks reached a leaf")
	}
}

// The search goes on past a file that is not a catalog (the contract: "a
// file that does not parse does not stop the search"), and the answer names
// what was skipped. It used to fail the whole Source step.
func TestCatalogSearchSkipsAFileThatIsNotACatalog(t *testing.T) {
	broken := writeCatalog(t, `{not json`)
	notCatalog := writeCatalog(t, `{"images": "none"}`)
	good := writeCatalog(t, `{"images": [{"name": "A", "imgref": "r.example/a:1"}]}`)
	catalog, used, skipped := loadCatalog([]string{"/nonexistent/images.json", broken, notCatalog, good})
	if used != good || len(catalog.Leaves) != 1 {
		t.Errorf("used %q with %d leaves, want %s", used, len(catalog.Leaves), good)
	}
	if len(skipped) != 2 || !strings.Contains(skipped[0], broken) || !strings.Contains(skipped[1], notCatalog) {
		t.Errorf("skipped = %v", skipped)
	}

	doc, stderr, code := runCatalog(t, nil, broken)
	if code != 0 {
		t.Fatalf("code = %d: a broken first file must not fail the command (%s)", code, stderr)
	}
	if list, _ := doc["skipped"].([]any); len(list) == 0 || !strings.Contains(stderr, "images.json") {
		t.Errorf("skipped = %v, stderr = %q; want the broken file named", doc["skipped"], stderr)
	}
}

// The system catalog is before the user's: a file in a home directory must
// not replace the one the ISO ships.
func TestCatalogSystemFileWinsOverTheUsers(t *testing.T) {
	paths := catalogSearchPaths(false, "/home/u/.config", bundledCatalogs...)
	index := func(want string) int {
		for i, path := range paths {
			if path == want {
				return i
			}
		}
		t.Fatalf("%s is not in %v", want, paths)
		return -1
	}
	system := index("/etc/bootc-installer/images.json")
	legacy := index("/etc/tuna-installer/images.json")
	user := index("/home/u/.config/bootc-installer/images.json")
	bundled := index("/app/share/fisherman/data/images.json")
	if !(system < legacy && legacy < user && user < bundled) {
		t.Errorf("order = %v", paths)
	}
}

// Carousel slides pass through with title, description and image; junk
// entries are dropped so the QML tour never renders an empty slide.
func TestCatalogPassesCarouselSlidesThrough(t *testing.T) {
	catalog, err := parseCatalog([]byte(`{"images": [
		{"name": "A", "imgref": "ghcr.io/example/a:1",
		 "carousel": [{"title": "Welcome", "description": "Hi", "image": "/a.png"}, {}, 42]}
	]}`))
	if err != nil {
		t.Fatal(err)
	}
	slides := catalog.Leaves[0].Carousel
	if len(slides) != 1 || slides[0].Title != "Welcome" || slides[0].Image != "/a.png" {
		t.Fatalf("carousel = %+v, want the one real slide", slides)
	}
}

// No catalog file is the live-ISO norm, not an error: empty leaves, exit 0,
// and the QML offers the branding default image.
func TestCatalogWithoutAFileIsEmpty(t *testing.T) {
	catalog, used, skipped := loadCatalog([]string{"/nonexistent/images.json"})
	if used != "" || len(catalog.Leaves) != 0 || len(skipped) != 0 {
		t.Errorf("used %q, leaves %v, skipped %v", used, catalog.Leaves, skipped)
	}
	raw, _ := json.Marshal(catalogAnswer(catalog, used, skipped, "", Machine{OfflineImages: []string{}}, ""))
	if !strings.Contains(string(raw), `"leaves":[]`) || !strings.Contains(string(raw), `"skipped":[]`) {
		t.Errorf("the QML needs arrays, never null: %s", raw)
	}
}

// The GPU: a PCI display device whose vendor is 0x10de. A network card of
// that vendor, or a display device of another, is not one.
func TestHasNvidiaGPU(t *testing.T) {
	device := func(root, name, vendor, class string) {
		dir := filepath.Join(root, name)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
		_ = os.WriteFile(filepath.Join(dir, "vendor"), []byte(vendor+"\n"), 0o644)
		_ = os.WriteFile(filepath.Join(dir, "class"), []byte(class+"\n"), 0o644)
	}
	none := t.TempDir()
	device(none, "0000:00:02.0", "0x8086", "0x030000")
	device(none, "0000:03:00.0", "0x10de", "0x020000")
	if hasNvidiaGPU(none) {
		t.Error("found an NVIDIA GPU where there is none")
	}
	with := t.TempDir()
	device(with, "0000:00:02.0", "0x8086", "0x030000")
	device(with, "0000:01:00.0", "0x10DE", "0x030200")
	if !hasNvidiaGPU(with) {
		t.Error("missed the NVIDIA GPU (a 3D controller, class 0x0302)")
	}
	if hasNvidiaGPU(filepath.Join(none, "missing")) {
		t.Error("a missing /sys is not an NVIDIA GPU")
	}
}
