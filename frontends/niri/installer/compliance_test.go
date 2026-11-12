package main

// The cross-frontend recipe contract: the Niri half (#226, #186).
//
// shared/recipe/fixtures/compliance.json holds one set of choices per case
// and the one recipe that every frontend must write for it. On a real
// machine the Niri recipe is made in two halves: installer.qml calls
// ui/recipe.js with the page values and the leaf of the backend's `catalog`
// answer, and `install` decodes that JSON, adds the account's groups and
// encodes it for fisherman. This test runs both halves: the catalog answer
// for the shared catalog fixture, ui/recipe.js under node
// (tests/recipe-build.mjs), then decodeRecipe and normalizeRecipe. The
// result is normalised with the fixture's table and its bytes must be the
// expected recipe's (shared/recipe/compliance.py is the reference).

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

var sharedComplianceFixture = filepath.Join("..", "..", "..", "shared", "recipe", "fixtures", "compliance.json")

type complianceKeyRule struct {
	Key   []string `json:"key"`
	Value any      `json:"value"`
	Needs string   `json:"needs"`
}

type complianceFixture struct {
	Catalog   string         `json:"catalog"`
	Branding  map[string]any `json:"branding"`
	Normalise struct {
		AbsentEquals  []complianceKeyRule `json:"absent_equals"`
		AbsentWithout []complianceKeyRule `json:"absent_without"`
	} `json:"normalise"`
	Cases []struct {
		Name    string `json:"name"`
		Choices struct {
			Image      string  `json:"image"`
			Machine    Machine `json:"machine"`
			Disk       string  `json:"disk"`
			Filesystem string  `json:"filesystem"`
			Encryption struct {
				Type       string `json:"type"`
				Passphrase string `json:"passphrase"`
			} `json:"encryption"`
			Hostname string `json:"hostname"`
			Account  *struct {
				Username string `json:"username"`
				Fullname string `json:"fullname"`
				Password string `json:"password"`
			} `json:"account"`
			Locale   string            `json:"locale"`
			Keyboard map[string]string `json:"keyboard"`
			Timezone string            `json:"timezone"`
		} `json:"choices"`
		Recipe map[string]any `json:"recipe"`
	} `json:"cases"`
}

// complianceParent is the object that holds the last key of path, or nil.
func complianceParent(recipe map[string]any, path []string) map[string]any {
	node := recipe
	for _, key := range path[:len(path)-1] {
		next, ok := node[key].(map[string]any)
		if !ok {
			return nil
		}
		node = next
	}
	return node
}

// complianceNormalise applies the fixture's two rules: a key whose value is
// the listed one is absent, and so is an object without its `needs` key.
func complianceNormalise(fx complianceFixture, recipe map[string]any) map[string]any {
	for _, rule := range fx.Normalise.AbsentEquals {
		parent := complianceParent(recipe, rule.Key)
		last := rule.Key[len(rule.Key)-1]
		if parent == nil {
			continue
		}
		if value, ok := parent[last]; ok && reflect.DeepEqual(value, rule.Value) {
			delete(parent, last)
		}
	}
	for _, rule := range fx.Normalise.AbsentWithout {
		parent := complianceParent(recipe, rule.Key)
		last := rule.Key[len(rule.Key)-1]
		if parent == nil {
			continue
		}
		if object, ok := parent[last].(map[string]any); ok {
			if _, has := object[rule.Needs]; !has {
				delete(parent, last)
			}
		}
	}
	return recipe
}

// complianceCanonical is the byte form the frontends compare: keys sorted,
// no spaces, UTF-8 (encoding/json sorts the keys of a map).
func complianceCanonical(t *testing.T, fx complianceFixture, v any) string {
	t.Helper()
	data, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var generic map[string]any
	if err := json.Unmarshal(data, &generic); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	enc := json.NewEncoder(&out)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(complianceNormalise(fx, generic)); err != nil {
		t.Fatal(err)
	}
	return strings.TrimSuffix(out.String(), "\n")
}

func loadCompliance(t *testing.T) complianceFixture {
	t.Helper()
	data, err := os.ReadFile(sharedComplianceFixture)
	if err != nil {
		t.Fatalf("read the compliance fixture: %v", err)
	}
	var fx complianceFixture
	if err := json.Unmarshal(data, &fx); err != nil {
		t.Fatal(err)
	}
	if len(fx.Cases) < 2 || len(fx.Normalise.AbsentEquals) == 0 {
		t.Fatalf("compliance.json is smaller than this test understands")
	}
	return fx
}

// node runs ui/recipe.js. It is on every CI runner; without it the test
// skips locally and fails in CI, so the half in QML is never left out.
func complianceNode(t *testing.T) string {
	t.Helper()
	node, err := exec.LookPath("node")
	if err != nil {
		if os.Getenv("CI") != "" {
			t.Fatal("node is not installed, and CI must run ui/recipe.js")
		}
		t.Skip("node is not installed")
	}
	return node
}

func TestRecipeCompliance(t *testing.T) {
	fx := loadCompliance(t)
	node := complianceNode(t)

	dir := t.TempDir()
	brandingFile := filepath.Join(dir, "branding.json")
	data, _ := json.Marshal(fx.Branding)
	if err := os.WriteFile(brandingFile, data, 0o600); err != nil {
		t.Fatal(err)
	}
	branding := resolveBrandingFrom([]string{brandingFile}, nil, "")
	groups, _ := sharedGroups()

	catalogData, err := os.ReadFile(filepath.Join("..", "..", "..", filepath.FromSlash(fx.Catalog)))
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range fx.Cases {
		t.Run(c.Name, func(t *testing.T) {
			ch := c.Choices
			catalog, err := parseCatalog(catalogData)
			if err != nil {
				t.Fatal(err)
			}
			// The Source step's data: the `catalog` answer for this machine.
			answer := catalogAnswer(catalog, "", nil, "", ch.Machine, "")
			var leaf *CatalogLeaf
			for i, l := range answer["leaves"].([]CatalogLeaf) {
				if l.Imgref == ch.Image {
					leaf = &answer["leaves"].([]CatalogLeaf)[i]
				}
			}
			if leaf == nil {
				t.Fatalf("the catalog has no leaf %s", ch.Image)
			}
			offered := filesystemChoices(leaf.Filesystem, leaf.Filesystems)
			if len(offered) > 0 && !contains(offered, ch.Filesystem) {
				t.Fatalf("the disk page does not offer %s: %v", ch.Filesystem, offered)
			}
			needsPassphrase := false
			for _, choice := range encryptionChoices() {
				if choice.Type == ch.Encryption.Type {
					needsPassphrase = choice.NeedsPassphrase
				}
			}
			choices := map[string]any{
				"disk": ch.Disk, "filesystem": ch.Filesystem, "btrfsSubvolumes": false,
				"encType": ch.Encryption.Type, "passphraseNeeded": needsPassphrase,
				"passphrase": ch.Encryption.Passphrase, "hostname": ch.Hostname,
				"distroID":          branding.ID,
				"region":            map[string]any{"locale": ch.Locale, "keyboard": ch.Keyboard["layout"], "timezone": ch.Timezone},
				"needsUserCreation": leaf.NeedsUserCreation,
			}
			if ch.Account != nil {
				choices["username"] = ch.Account.Username
				choices["fullname"] = ch.Account.Fullname
				choices["password"] = ch.Account.Password
			}
			input, _ := json.Marshal(map[string]any{"leaf": leaf, "choices": choices})
			cmd := exec.Command(node, filepath.Join("..", "tests", "recipe-build.mjs"))
			cmd.Stdin = bytes.NewReader(input)
			var stderr bytes.Buffer
			cmd.Stderr = &stderr
			qml, err := cmd.Output()
			if err != nil {
				t.Fatalf("ui/recipe.js: %v\n%s", err, stderr.String())
			}

			// The backend's half: what `install` sends to fisherman.
			recipe, err := decodeRecipe(bytes.TrimSpace(qml))
			if err != nil {
				t.Fatalf("the backend refuses the wizard's recipe: %v\n%s", err, qml)
			}
			normalizeRecipe(&recipe, branding.ID, groups)

			got := complianceCanonical(t, fx, recipe)
			want := complianceCanonical(t, fx, c.Recipe)
			if got != want {
				t.Errorf("the recipe differs from shared/recipe/fixtures/compliance.json\n got %s\nwant %s", got, want)
			}
		})
	}
}

// The normaliser is the fixture's, not a looser one: a value that is not
// the default stays, and so does a value of another type.
func TestRecipeComplianceNormaliser(t *testing.T) {
	fx := loadCompliance(t)
	recipe := map[string]any{
		"disk": "/dev/vda", "composeFsBackend": false, "imageType": "bootc", "bootloader": "",
		"selinuxDisabled": false, "btrfsSubvolumes": false,
		"encryption": map[string]any{"type": "none", "passphrase": ""},
		"user":       map[string]any{"username": "", "fullname": "", "password": "", "groups": []any{}},
	}
	if got := complianceCanonical(t, fx, recipe); got != `{"disk":"/dev/vda","encryption":{"type":"none"}}` {
		t.Errorf("normalised to %s", got)
	}
	kept := map[string]any{"composeFsBackend": true, "btrfsSubvolumes": 0.0, "bootloader": "grub2",
		"user": map[string]any{"username": "jo"}}
	if got := complianceCanonical(t, fx, kept); got != `{"bootloader":"grub2","btrfsSubvolumes":0,"composeFsBackend":true,"user":{"username":"jo"}}` {
		t.Errorf("normalised to %s", got)
	}
}
