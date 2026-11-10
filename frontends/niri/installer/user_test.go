package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// The account step writes the recipe's `user` block. The groups are the
// shared list (shared/account/groups.json) or the operator's (#302).

// sharedGroupsFile is the canonical file this module embeds a copy of.
var sharedGroupsFile = filepath.Join("..", "..", "..", "shared", "account", "groups.json")

// installedJSON is what runInstall hands fisherman for this QML recipe.
func installedJSON(t *testing.T, qml string) map[string]any {
	t.Helper()
	r, err := decodeRecipe([]byte(qml))
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	defaults, _ := sharedGroups()
	normalizeRecipe(&r, "neutral", defaults)
	data, err := json.Marshal(r)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		t.Fatalf("re-read: %v", err)
	}
	return out
}

func anyList(items ...string) []any {
	out := make([]any, len(items))
	for i, item := range items {
		out[i] = item
	}
	return out
}

// The embedded list is the shared file, byte for byte: a change to
// shared/account/groups.json that is not copied here fails.
func TestEmbeddedGroupsAreTheSharedFile(t *testing.T) {
	shared, err := os.ReadFile(sharedGroupsFile)
	if err != nil {
		t.Fatalf("read the shared groups file: %v", err)
	}
	if string(shared) != string(groupsJSON) {
		t.Fatal("installer/groups.json has drifted from shared/account/groups.json: run `go generate ./...` in installer/")
	}
	defaults, file := sharedGroups()
	if len(defaults) == 0 || !contains(defaults, "wheel") || !contains(defaults, "sudo") {
		t.Errorf("default groups = %v, want the admin groups of both families", defaults)
	}
	if file != "bootc-installer/recipe.json" {
		t.Errorf("override file = %q", file)
	}
}

// Every case of the shared file: an operator recipe in, the groups out.
func TestGroupsFollowTheSharedCases(t *testing.T) {
	var doc struct {
		DefaultGroups []string `json:"default_groups"`
		Cases         []struct {
			Name           string          `json:"name"`
			OperatorRecipe json.RawMessage `json:"operator_recipe"`
			Groups         []string        `json:"groups"`
		} `json:"cases"`
	}
	shared, err := os.ReadFile(sharedGroupsFile)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(shared, &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc.Cases) < 5 {
		t.Fatalf("only %d cases in the shared file", len(doc.Cases))
	}
	for _, c := range doc.Cases {
		var operator []byte
		if string(c.OperatorRecipe) != "null" {
			operator = c.OperatorRecipe
		}
		got := groupsFrom(operator, doc.DefaultGroups)
		if !reflect.DeepEqual(got, c.Groups) {
			t.Errorf("%s: groups = %v, want %v", c.Name, got, c.Groups)
		}
	}
	if got := groupsFrom([]byte(`{not json`), doc.DefaultGroups); !reflect.DeepEqual(got, doc.DefaultGroups) {
		t.Errorf("a file that does not parse: groups = %v, want the default", got)
	}
}

func TestUserBlockReachesFisherman(t *testing.T) {
	out := installedJSON(t, `{"disk":"/dev/vda","hostname":"box",
		"encryption":{"type":"none"},
		"user":{"username":"jo","fullname":"Jo Doe","password":"pw","groups":["wheel"]}}`)
	want := map[string]any{
		"username": "jo", "fullname": "Jo Doe", "password": "pw",
		"groups": []any{"wheel"},
	}
	if !reflect.DeepEqual(out["user"], want) {
		t.Fatalf("user block = %#v, want %#v", out["user"], want)
	}
}

// The QML names no groups: the backend writes the shared list. This was
// ["wheel"] alone, which is no admin group at all on an image whose admin
// group is `sudo`.
func TestUserGroupsDefaultToTheSharedList(t *testing.T) {
	out := installedJSON(t, `{"disk":"/dev/vda","user":{"username":"jo","password":"pw"}}`)
	user, _ := out["user"].(map[string]any)
	defaults, _ := sharedGroups()
	if !reflect.DeepEqual(user["groups"], anyList(defaults...)) {
		t.Fatalf("groups = %#v, want %v", user["groups"], defaults)
	}
	if user["fullname"] != "" {
		t.Errorf("fullname = %#v, want the key present and empty", user["fullname"])
	}
}

// The operator's list replaces the default, the empty list included.
func TestUserGroupsFollowTheOperator(t *testing.T) {
	for _, groups := range [][]string{{"wheel", "video"}, {}} {
		r, err := decodeRecipe([]byte(`{"disk":"/dev/vda","user":{"username":"jo","password":"pw"}}`))
		if err != nil {
			t.Fatal(err)
		}
		normalizeRecipe(&r, "x", groups)
		data, _ := json.Marshal(r)
		var out map[string]map[string]any
		_ = json.Unmarshal(data, &out)
		got, ok := out["user"]["groups"].([]any)
		if !ok || !reflect.DeepEqual(got, anyList(groups...)) {
			t.Errorf("operator %v: recipe groups = %#v (%s)", groups, out["user"]["groups"], data)
		}
	}
}

func TestUserGroupsAreKeptWhenGiven(t *testing.T) {
	out := installedJSON(t, `{"disk":"/dev/vda","user":{"username":"jo","password":"pw","groups":["wheel","audio"]}}`)
	user, _ := out["user"].(map[string]any)
	if !reflect.DeepEqual(user["groups"], []any{"wheel", "audio"}) {
		t.Fatalf("groups = %#v", user["groups"])
	}
}

func TestUserBlockOmittedWhenAbsent(t *testing.T) {
	out := installedJSON(t, `{"disk":"/dev/vda","hostname":"box"}`)
	if _, ok := out["user"]; ok {
		t.Fatalf("a recipe with no account gained a user block: %#v", out["user"])
	}
}

func TestUserBlockWithoutUsernameIsDropped(t *testing.T) {
	// The schema's "an empty username skips the step": a password with no
	// account is not passed on.
	out := installedJSON(t, `{"disk":"/dev/vda","user":{"username":"","password":"pw"}}`)
	if _, ok := out["user"]; ok {
		t.Fatalf("an empty username still sent a user block: %#v", out["user"])
	}
}

func TestDefaultGroupsAreNotShared(t *testing.T) {
	var a, b Recipe
	a.User = &User{Username: "a"}
	b.User = &User{Username: "b"}
	groups := []string{"wheel", "sudo"}
	normalizeRecipe(&a, "x", groups)
	normalizeRecipe(&b, "x", groups)
	(*a.User.Groups)[0] = "changed"
	if (*b.User.Groups)[0] != "wheel" || groups[0] != "wheel" {
		t.Fatal("normalizeRecipe aliased the group list between recipes")
	}
}

func TestNormalizeRecipeDistroID(t *testing.T) {
	r := Recipe{}
	normalizeRecipe(&r, "fallback", nil)
	if r.DistroID != "fallback" {
		t.Fatalf("distroID = %q, want the branding's", r.DistroID)
	}
	r = Recipe{DistroID: "given"}
	normalizeRecipe(&r, "fallback", nil)
	if r.DistroID != "given" {
		t.Fatalf("distroID = %q, want the recipe's own", r.DistroID)
	}
}

func TestQMLHoldsTheAccountStep(t *testing.T) {
	// The QML half of the contract, read as text: the recipe carries the
	// user block when the image needs one, with no groups of its own (the
	// backend writes the shared list); the partial recipe asks fisherman
	// about user.username, and the problem is shown through the copy keys
	// validate_username_* (via validate_<code>). An image that makes its own
	// first user gets no block at all.
	qml := readQML(t)
	for _, want := range []string{
		`recipe.user = { username: root.username }`,
		`root.needsUserCreation && root.username !== ""`,
		`if (root.needsUserCreation)`,
		`problemText("user.username")`,
		`qsTr("Account")`,
		`objectName: "accountRevealButton"`,
		`echoMode: root.showPassword ? TextInput.Normal : TextInput.Password`,
	} {
		if !strings.Contains(qml, want) {
			t.Errorf("ui/installer.qml lacks %q", want)
		}
	}
	for _, banned := range []string{`groups: ["wheel"]`, `"wheel"`} {
		if strings.Contains(qml, banned) {
			t.Errorf("ui/installer.qml still names its own groups: %q", banned)
		}
	}
}

func readQML(t *testing.T) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("..", "ui", "installer.qml"))
	if err != nil {
		t.Fatalf("read installer.qml: %v", err)
	}
	return string(data)
}
