package main

// The plan reader against the golden plans of the pinned fisherman
// (fisherman/fisherman/cmd/fisherman/testdata/plan/), the cases that
// tests/unit/test_shared_plan.py holds bootc_shared.plan to. The rows go
// through ui/plan.js under node, as the confirm page renders them. No test
// runs fisherman.

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

const planSecret = "correct-horse-battery-staple"

// planDigest stands for the digest that a fisherman with `plan.binding`
// writes where its goldens say @PLAN_DIGEST@.
var planDigest = "sha256:" + strings.Repeat("ab", 32)

var planGoldenDir = filepath.Join("..", "..", "..", "fisherman", "fisherman", "cmd", "fisherman", "testdata", "plan")

func planGolden(t *testing.T, name string) []byte {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(planGoldenDir, name+".golden"))
	if err != nil {
		planNoGoldens(t)
	}
	data = bytes.ReplaceAll(data, []byte("@DIR@"), []byte("/dev"))
	return bytes.ReplaceAll(data, []byte("@PLAN_DIGEST@"), []byte(planDigest))
}

// planNoGoldens skips locally without the submodule; CI checks it out, so
// there the goldens must be read.
func planNoGoldens(t *testing.T) {
	t.Helper()
	if os.Getenv("CI") != "" {
		t.Fatal("no fisherman submodule, and CI must read the golden plans")
	}
	t.Skip("no fisherman submodule")
}

func planOf(t *testing.T, name string) PlanView {
	t.Helper()
	view, err := parsePlan(planGolden(t, name))
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	return view
}

type planRendered struct {
	Rows []struct {
		Title    string `json:"title"`
		Subtitle string `json:"subtitle"`
	} `json:"rows"`
	Recipe map[string]any `json:"recipe"`
}

// planJS runs ui/plan.js (tests/plan-rows.mjs) on a view and a recipe.
func planJS(t *testing.T, view PlanView, recipe map[string]any) planRendered {
	t.Helper()
	node := complianceNode(t)
	input, _ := json.Marshal(map[string]any{"view": view, "recipe": recipe, "copy": copyDefaults()})
	cmd := exec.Command(node, filepath.Join("..", "tests", "plan-rows.mjs"))
	cmd.Stdin = bytes.NewReader(input)
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("plan-rows.mjs: %v", err)
	}
	var got planRendered
	if err := json.Unmarshal(out, &got); err != nil {
		t.Fatalf("plan-rows.mjs printed %q: %v", out, err)
	}
	return got
}

func planRecipe(disk string) map[string]any {
	return map[string]any{"disk": disk, "image": "ghcr.io/example/os:stable",
		"encryption": map[string]any{"type": "luks-passphrase", "passphrase": planSecret}}
}

func rowLines(r planRendered) [][2]string {
	out := [][2]string{}
	for _, row := range r.Rows {
		out = append(out, [2]string{row.Title, row.Subtitle})
	}
	return out
}

func TestPlanEveryGoldenParses(t *testing.T) {
	paths, _ := filepath.Glob(filepath.Join(planGoldenDir, "*.golden"))
	if len(paths) == 0 {
		planNoGoldens(t)
	}
	for _, path := range paths {
		name := strings.TrimSuffix(filepath.Base(path), ".golden")
		view := planOf(t, name)
		if !view.Valid && (len(view.Rows) != 0 || view.DiskIdentity != nil || view.PlanBinding != nil) {
			t.Errorf("%s: an invalid plan has rows or a binding", name)
		}
		for _, row := range view.Rows {
			if row.Kind != "target" && row.Kind != "bound" && row.Kind != "unbound" && !planEffects[row.Kind] {
				t.Errorf("%s: row kind %q has no copy key", name, row.Kind)
			}
		}
		data, _ := json.Marshal(view)
		if strings.Contains(string(data), planSecret) {
			t.Errorf("%s: the view holds the passphrase", name)
		}
		for _, line := range rowLines(planJS(t, view, planRecipe("/dev/sda"))) {
			if line[0] == "" || strings.Contains(line[0]+line[1], "{") {
				t.Errorf("%s: row %q", name, line)
			}
		}
	}
}

func TestPlanBindsWhatTheDiskReports(t *testing.T) {
	view := planOf(t, "grub2-plain")
	want := &DiskIdentity{Serial: "FIXTURE-SDA-SERIAL", WWN: "0x5000c500a1b2c3d4", SizeBytes: 500107862016}
	if !reflect.DeepEqual(view.DiskIdentity, want) || view.Disk != "/dev/sda" {
		t.Fatalf("identity = %+v on %q", view.DiskIdentity, view.Disk)
	}
	got := planJS(t, view, planRecipe("/dev/sda"))
	bound, _ := json.Marshal(got.Recipe["diskIdentity"])
	if string(bound) != `{"serial":"FIXTURE-SDA-SERIAL","sizeBytes":500107862016,"wwn":"0x5000c500a1b2c3d4"}` {
		t.Errorf("bound diskIdentity = %s", bound)
	}
	if got.Recipe["encryption"].(map[string]any)["passphrase"] != planSecret {
		t.Errorf("bind dropped the rest of the recipe: %v", got.Recipe)
	}
	wantRows := [][2]string{
		{"Installs to Fixture Disk", "/dev/sda, 465.8 GiB, serial number FIXTURE-SDA-SERIAL"},
		{copyDefaults()["confirm_plan_bound"], ""},
		{"Everything on /dev/sda is erased.", ""},
	}
	if lines := rowLines(got); !reflect.DeepEqual(lines, wantRows) {
		t.Errorf("rows = %q, want %q", lines, wantRows)
	}
}

func TestPlanLeavesUnknownValuesOutOfTheBinding(t *testing.T) {
	view := planOf(t, "loop-image")
	if !reflect.DeepEqual(view.DiskIdentity, &DiskIdentity{SizeBytes: 8589934592}) {
		t.Fatalf("identity = %+v", view.DiskIdentity)
	}
	got := planJS(t, view, planRecipe("/dev/loop0"))
	if ident, _ := json.Marshal(got.Recipe["diskIdentity"]); string(ident) != `{"sizeBytes":8589934592}` {
		t.Errorf("bound diskIdentity = %s", ident)
	}
	lines := rowLines(got)
	if lines[0] != [2]string{"Installs to unknown", "/dev/loop0, 8 GiB, serial number unknown"} ||
		lines[1][0] != copyDefaults()["confirm_plan_unbound"] {
		t.Errorf("rows = %q", lines)
	}
}

func TestPlanBindsNothingWithoutAPlanForThisDisk(t *testing.T) {
	view := planOf(t, "grub2-plain")
	for _, disk := range []string{"/dev/sdb", ""} {
		if _, ok := planJS(t, view, planRecipe(disk)).Recipe["diskIdentity"]; ok {
			t.Errorf("a plan for /dev/sda bound a recipe for %q", disk)
		}
	}
	manual := planOf(t, "manual")
	if manual.DiskIdentity != nil {
		t.Errorf("manual layout identity = %+v", manual.DiskIdentity)
	}
	got := planJS(t, manual, planRecipe("/dev/sda"))
	if _, ok := got.Recipe["diskIdentity"]; ok {
		t.Error("a manual layout bound the recipe")
	}
	want := [][2]string{
		{"/dev/sda3 is formatted. Its data is erased.", ""},
		{"/dev/sda4 becomes swap space. Its data is erased.", ""},
		{"/dev/sda2 is formatted. Its data is erased.", ""},
	}
	if lines := rowLines(got); !reflect.DeepEqual(lines, want) {
		t.Errorf("manual rows = %q", lines)
	}
	invalid := planOf(t, "identity-serial-changed")
	if invalid.Valid || len(invalid.Errors) == 0 || invalid.Errors[0] != "disk_identity_mismatch" {
		t.Errorf("identity-serial-changed = %+v", invalid)
	}
	if _, ok := planJS(t, invalid, planRecipe("/dev/sda")).Recipe["diskIdentity"]; ok {
		t.Error("an invalid plan bound the recipe")
	}
}

// planWithBinding is a golden plan as a fisherman with `plan.binding`
// prints it, with `binding` in place of the golden's own (nil: none, as an
// older fisherman prints).
func planWithBinding(t *testing.T, name string, binding any) PlanView {
	t.Helper()
	var result map[string]any
	if err := json.Unmarshal(planGolden(t, name), &result); err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	plan := result["plan"].(map[string]any)
	if binding == nil {
		delete(plan, "binding")
	} else {
		plan["binding"] = binding
	}
	data, _ := json.Marshal(result)
	view, err := parsePlan(data)
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	return view
}

func planBindingJSON(r planRendered) (string, bool) {
	b, ok := r.Recipe["planBinding"]
	data, _ := json.Marshal(b)
	return string(data), ok
}

func TestPlanBindingIsCopiedAsPlanBinding(t *testing.T) {
	view := planWithBinding(t, "grub2-plain", map[string]any{"digest": planDigest, "read_image": true})
	yes := true
	if !reflect.DeepEqual(view.PlanBinding, &PlanBinding{Digest: planDigest, ReadImage: &yes}) {
		t.Fatalf("binding = %+v", view.PlanBinding)
	}
	got := planJS(t, view, planRecipe("/dev/sda"))
	if b, _ := planBindingJSON(got); b != `{"digest":"`+planDigest+`","readImage":true}` {
		t.Errorf("planBinding = %s", b)
	}
	if _, ok := got.Recipe["diskIdentity"]; !ok {
		t.Error("the binding dropped diskIdentity")
	}
	if got.Recipe["encryption"].(map[string]any)["passphrase"] != planSecret {
		t.Errorf("bind dropped the rest of the recipe: %v", got.Recipe)
	}
}

func TestPlanGoldensBindingIsCopied(t *testing.T) {
	for name, readImage := range map[string]bool{"grub2-plain": false, "read-image-registry": true} {
		view := planOf(t, name)
		if view.PlanBinding == nil {
			t.Skip("the pinned fisherman has no plan.binding")
		}
		want := `{"digest":"` + planDigest + `","readImage":` + map[bool]string{true: "true", false: "false"}[readImage] + `}`
		if b, _ := planBindingJSON(planJS(t, view, planRecipe("/dev/sda"))); b != want {
			t.Errorf("%s: planBinding = %s, want %s", name, b, want)
		}
	}
}

func TestPlanWithoutABindingBindsTheDiskOnly(t *testing.T) {
	view := planWithBinding(t, "grub2-plain", nil)
	if view.PlanBinding != nil {
		t.Fatalf("binding = %+v", view.PlanBinding)
	}
	got := planJS(t, view, planRecipe("/dev/sda"))
	if _, ok := got.Recipe["planBinding"]; ok {
		t.Error("a plan without a binding set planBinding")
	}
	if _, ok := got.Recipe["diskIdentity"]; !ok {
		t.Error("a plan without a binding dropped diskIdentity")
	}
}

func TestPlanMalformedBindingIsNotCopied(t *testing.T) {
	for _, binding := range []any{
		"sha256:" + strings.Repeat("ab", 32), map[string]any{}, map[string]any{"digest": ""},
		map[string]any{"digest": "sha256:ABC"}, map[string]any{"digest": "sha256:" + strings.Repeat("AB", 32)},
		map[string]any{"digest": "md5:" + strings.Repeat("ab", 16)},
		map[string]any{"digest": "sha256:" + strings.Repeat("ab", 32) + "\n"},
		map[string]any{"digest": 7}, map[string]any{"read_image": true}, []any{}, 3,
	} {
		view := planWithBinding(t, "grub2-plain", binding)
		if view.PlanBinding != nil {
			t.Errorf("%v: binding = %+v", binding, view.PlanBinding)
		}
		if _, ok := planJS(t, view, planRecipe("/dev/sda")).Recipe["planBinding"]; ok {
			t.Errorf("%v: a malformed binding set planBinding", binding)
		}
	}
	// A view that names a malformed digest (not one plan.go prints) is
	// not copied by plan.js either.
	view := planOf(t, "grub2-plain")
	view.PlanBinding = &PlanBinding{Digest: "sha256:ABC"}
	if _, ok := planJS(t, view, planRecipe("/dev/sda")).Recipe["planBinding"]; ok {
		t.Error("plan.js copied a malformed digest")
	}
}

func TestPlanReadImageIsCopiedOnlyAsABoolean(t *testing.T) {
	view := planWithBinding(t, "grub2-plain", map[string]any{"digest": planDigest, "read_image": "yes"})
	if !reflect.DeepEqual(view.PlanBinding, &PlanBinding{Digest: planDigest}) {
		t.Fatalf("binding = %+v", view.PlanBinding)
	}
	if b, _ := planBindingJSON(planJS(t, view, planRecipe("/dev/sda"))); b != `{"digest":"`+planDigest+`"}` {
		t.Errorf("planBinding = %s", b)
	}
}

func TestPlanBindingNotForAnotherDisk(t *testing.T) {
	view := planWithBinding(t, "grub2-plain", map[string]any{"digest": planDigest, "read_image": false})
	for _, disk := range []string{"/dev/sdb", ""} {
		got := planJS(t, view, planRecipe(disk))
		if _, ok := got.Recipe["planBinding"]; ok {
			t.Errorf("a plan for /dev/sda set planBinding on a recipe for %q", disk)
		}
	}
}

func TestPlanManualLayoutIsBoundToItsPlanNotADisk(t *testing.T) {
	view := planWithBinding(t, "manual", map[string]any{"digest": planDigest, "read_image": false})
	got := planJS(t, view, planRecipe("/dev/sda"))
	if b, _ := planBindingJSON(got); b != `{"digest":"`+planDigest+`","readImage":false}` {
		t.Errorf("planBinding = %s", b)
	}
	if _, ok := got.Recipe["diskIdentity"]; ok {
		t.Error("a manual layout set diskIdentity")
	}
}

func TestPlanErrorCodesHaveCopyKeys(t *testing.T) {
	for _, code := range []string{"plan_stale", "plan_binding_invalid", "disk_identity_mismatch", "disk_identity_invalid"} {
		if line := copyDefaults()["validate_"+code]; line == "" || strings.Contains(line, "{") {
			t.Errorf("validate_%s = %q", code, line)
		}
	}
}

func TestPlanUnknownEffectIsAFormat(t *testing.T) {
	view, err := parsePlan([]byte(`{"protocol_version":1,"valid":true,"errors":[],
		"plan":{"target":{"layout":"manual"},"destroys":[{"device":"/dev/sdz","effect":"trim"},{"effect":"format"}]}}`))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(view.Rows, []PlanRow{{Kind: "format", Values: map[string]string{"disk": "/dev/sdz"}}}) {
		t.Errorf("rows = %+v", view.Rows)
	}
}

func TestPlanUnreadableAnswers(t *testing.T) {
	for _, text := range []string{
		``,
		`not json`,
		`{"type":"error","message":"open plan: no such file"}`,
		`{"protocol_version":2,"valid":true,"errors":[],"plan":{}}`,
		`{"protocol_version":1,"valid":true,"errors":[],"plan":null}`,
		`{"protocol_version":1,"errors":[]}`,
	} {
		if _, err := parsePlan([]byte(text)); !errors.Is(err, errPlan) {
			t.Errorf("%q: err = %v", text, err)
		}
	}
}

func TestPlanCommandReadsTheRecipeOnStdin(t *testing.T) {
	golden := filepath.Join(t.TempDir(), "plan.golden")
	if err := os.WriteFile(golden, planGolden(t, "grub2-plain"), 0o600); err != nil {
		t.Fatal(err)
	}
	recipe, _ := json.Marshal(planRecipe("/dev/sda"))
	// The fake fisherman answers only when the passphrase came on stdin.
	argv := []string{"sh", "-c", `grep -q "$1" && cat "$2"`, "sh", planSecret[:7], golden}
	var out, errOut bytes.Buffer
	if code := runPlanCmd(argv, bytes.NewReader(recipe), &out, &errOut); code != 0 {
		t.Fatalf("exit %d: %s", code, errOut.String())
	}
	var view PlanView
	if err := json.Unmarshal(out.Bytes(), &view); err != nil || !view.Valid || view.Disk != "/dev/sda" {
		t.Fatalf("view = %+v, %v", view, err)
	}
	if !reflect.DeepEqual(planArgs, []string{"plan", "--json", "-"}) {
		t.Errorf("planArgs = %v", planArgs)
	}
	argv = Fisherman{Flatpak: true, Path: "/c/f"}.Argv(planArgs...)
	if strings.Contains(strings.Join(argv, " "), "pkexec") || strings.Contains(strings.Join(argv, " "), "sudo") {
		t.Errorf("plan is privileged: %v", argv)
	}
}

func TestPlanCommandFailures(t *testing.T) {
	recipe, _ := json.Marshal(planRecipe("/dev/sda"))
	cases := map[string][]string{
		"old fisherman": {"sh", "-c", `echo "unknown command plan" >&2; exit 2`},
		"no answer":     {"sh", "-c", `exit 1`},
		"not found":     {filepath.Join(t.TempDir(), "missing")},
	}
	for name, argv := range cases {
		var out, errOut bytes.Buffer
		if code := runPlanCmd(argv, bytes.NewReader(recipe), &out, &errOut); code != 2 || out.Len() != 0 {
			t.Errorf("%s: exit %d, stdout %q", name, code, out.String())
		}
		if strings.Contains(errOut.String(), planSecret) {
			t.Errorf("%s: the error names the passphrase", name)
		}
	}
	if _, err := runPlanWith([]string{"sleep", "5"}, recipe, 100*time.Millisecond); !errors.Is(err, errPlan) ||
		!strings.Contains(err.Error(), "no answer") {
		t.Errorf("timeout: %v", err)
	}
}

func TestPlanFormatSize(t *testing.T) {
	for n, want := range map[int64]string{
		512: "512 B", 1024: "1 KiB", 8589934592: "8 GiB", 500107862016: "465.8 GiB", 1536: "1.5 KiB",
	} {
		if got := formatSize(n); got != want {
			t.Errorf("formatSize(%d) = %q, want %q", n, got, want)
		}
	}
}

func TestPlanEveryKindHasACopyKey(t *testing.T) {
	src, err := os.ReadFile(filepath.Join("..", "ui", "plan.js"))
	if err != nil {
		t.Fatal(err)
	}
	copy := copyDefaults()
	kinds := []string{"target", "target_detail", "bound", "unbound", "unknown"}
	for effect := range planEffects {
		kinds = append(kinds, effect)
	}
	for _, kind := range kinds {
		key := "confirm_plan_" + kind
		if !strings.Contains(string(src), `"`+key+`"`) || copy[key] == "" {
			t.Errorf("%s is not in ui/plan.js or has no default", key)
		}
	}
}
