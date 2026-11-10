package main

// The Recipe struct against the shared schema (#297). The struct used to
// list some of the recipe's keys, and encoding/json drops what a struct does
// not list: a key the QML sent never reached fisherman, and nothing said so.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"testing"
)

var recipeSchemaFile = filepath.Join("..", "..", "..", "shared", "recipe", "fisherman-recipe.schema.json")

func schemaProperties(t *testing.T) map[string]map[string]any {
	t.Helper()
	data, err := os.ReadFile(recipeSchemaFile)
	if err != nil {
		t.Fatalf("read the recipe schema: %v", err)
	}
	var schema struct {
		Properties map[string]map[string]any `json:"properties"`
	}
	if err := json.Unmarshal(data, &schema); err != nil {
		t.Fatal(err)
	}
	if len(schema.Properties) < 20 {
		t.Fatalf("the schema has %d properties: wrong file?", len(schema.Properties))
	}
	return schema.Properties
}

func jsonKeys(v any) []string {
	keys := []string{}
	typ := reflect.TypeOf(v)
	for i := 0; i < typ.NumField(); i++ {
		name, _, _ := strings.Cut(typ.Field(i).Tag.Get("json"), ",")
		keys = append(keys, name)
	}
	sort.Strings(keys)
	return keys
}

// Every property of the schema is a field of the struct, and the struct has
// no field the schema does not: a new recipe key fails here until it is
// added, and cannot be dropped silently.
func TestRecipeStructListsEverySchemaProperty(t *testing.T) {
	properties := schemaProperties(t)
	want := []string{}
	for key := range properties {
		want = append(want, key)
	}
	sort.Strings(want)
	if got := jsonKeys(Recipe{}); !reflect.DeepEqual(got, want) {
		t.Errorf("Recipe keys\n got %v\nwant %v", got, want)
	}
	for field, sample := range map[string]any{"user": User{}, "encryption": Encryption{}} {
		sub, _ := properties[field]["properties"].(map[string]any)
		want := []string{}
		for key := range sub {
			want = append(want, key)
		}
		sort.Strings(want)
		if got := jsonKeys(sample); !reflect.DeepEqual(got, want) {
			t.Errorf("%s keys\n got %v\nwant %v", field, got, want)
		}
	}
}

// A recipe with a value for every key comes out as it went in.
func TestRecipeRoundTripKeepsEveryKey(t *testing.T) {
	full := `{
		"disk": "/dev/vda", "filesystem": "btrfs", "btrfsSubvolumes": true,
		"encryption": {"type": "luks-passphrase", "passphrase": "p"},
		"image": "registry.example/os/boreal-nvidia:latest",
		"targetImgref": "registry.example/os/boreal:latest",
		"bootloader": "systemd", "composeFsBackend": true,
		"flatpaks": ["org.example.Files"],
		"additionalImageStores": ["/run/store"],
		"distroID": "example", "selinuxDisabled": true, "hostname": "box",
		"unifiedStorage": true, "genericImage": true, "zfsPoolName": "tank",
		"imageType": "ostree", "flatpakVarPath": "state/os/default/var",
		"user": {"username": "jo", "fullname": "Jo", "password": "pw", "groups": ["wheel"]},
		"customMounts": [{"partition": "/dev/vda2", "target": "/", "fstype": "xfs"}],
		"varDisk": {"disk": "/dev/vdb", "keepExisting": true},
		"slurpWallpapers": true,
		"slurp": {"sourcePartition": "/dev/vda3", "users": ["jo"]},
		"targetMount": "/mnt/t", "luksMapperName": "m", "brewTap": "owner/tap",
		"override": ["too_small"]
	}`
	var want map[string]any
	if err := json.Unmarshal([]byte(full), &want); err != nil {
		t.Fatal(err)
	}
	for key := range schemaProperties(t) {
		if _, ok := want[key]; !ok {
			t.Errorf("the sample recipe has no %q: add it, so the round trip covers it", key)
		}
	}
	recipe, err := decodeRecipe([]byte(full))
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	normalizeRecipe(&recipe, "other", []string{"sudo"})
	data, err := json.Marshal(recipe)
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("round trip\n got %v\nwant %v", got, want)
	}
}

// `flatpaks: []` tells fisherman to copy no Flatpak; no key tells it to apply
// its default. The two must not become one on the way through.
func TestRecipeKeepsAnEmptyFlatpakListApartFromNone(t *testing.T) {
	encode := func(in string) map[string]any {
		recipe, err := decodeRecipe([]byte(in))
		if err != nil {
			t.Fatal(err)
		}
		data, _ := json.Marshal(recipe)
		var out map[string]any
		_ = json.Unmarshal(data, &out)
		return out
	}
	empty := encode(`{"disk":"/dev/vda","hostname":"h","flatpaks":[]}`)
	if list, ok := empty["flatpaks"].([]any); !ok || len(list) != 0 {
		t.Errorf("flatpaks: [] came out as %#v", empty["flatpaks"])
	}
	none := encode(`{"disk":"/dev/vda","hostname":"h"}`)
	if _, ok := none["flatpaks"]; ok {
		t.Errorf("a recipe with no flatpaks gained %#v", none["flatpaks"])
	}
}

// A key the struct does not list is an error, at the top and in the blocks
// this backend types.
func TestDecodeRecipeFailsOnAnUnknownKey(t *testing.T) {
	for _, in := range []string{
		`{"disk":"/dev/vda","hostname":"h","notARecipeKey":"x"}`,
		`{"disk":"/dev/vda","hostname":"h","user":{"username":"jo","shell":"/bin/zsh"}}`,
		`{"disk":"/dev/vda","hostname":"h","encryption":{"type":"none","cipher":"x"}}`,
		`{"disk":"/dev/vda","hostname":"h"} {"disk":"/dev/vdb"}`,
	} {
		if _, err := decodeRecipe([]byte(in)); err == nil {
			t.Errorf("decodeRecipe accepted %s", in)
		}
	}
	if _, err := decodeRecipe([]byte(`{"disk":"/dev/vda","hostname":"h"}`)); err != nil {
		t.Errorf("a plain recipe was refused: %v", err)
	}
}
