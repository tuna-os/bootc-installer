package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// The shared case files: every frontend's reader gives the views that the
// canonical Python reader gives (shared/probe/README.md, "Source check";
// shared/completion/README.md).
var (
	sharedProbe      = filepath.Join("..", "..", "..", "shared", "probe")
	sharedCompletion = filepath.Join("..", "..", "..", "shared", "completion")
)

func loadCases(t *testing.T, path string) []map[string]json.RawMessage {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Skipf("%s is absent; this tree is checked out alone", path)
	}
	var doc struct {
		Cases []map[string]json.RawMessage `json:"cases"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc.Cases) == 0 {
		t.Fatalf("%s has no cases", path)
	}
	return doc.Cases
}

// sameJSON compares a view with the expected JSON as generic values.
func sameJSON(t *testing.T, name string, got any, want json.RawMessage) {
	t.Helper()
	gotRaw, _ := json.Marshal(got)
	var a, b any
	_ = json.Unmarshal(gotRaw, &a)
	_ = json.Unmarshal(want, &b)
	if !reflect.DeepEqual(a, b) {
		t.Errorf("%s:\n got %s\nwant %s", name, gotRaw, want)
	}
}

// probeInput is the probe output a case describes: nil when the probe
// failed, {protocol_version: 1} for an older fisherman, else the fixture
// under key.
func probeInput(t *testing.T, c map[string]json.RawMessage, dir, key string) []byte {
	var failed bool
	_ = json.Unmarshal(c["probe_failed"], &failed)
	if failed {
		return nil
	}
	var fixture *string
	_ = json.Unmarshal(c["fixture"], &fixture)
	if fixture == nil {
		return []byte(`{"protocol_version": 1}`)
	}
	data, err := os.ReadFile(filepath.Join(sharedProbe, "fixtures", dir, *fixture))
	if err != nil {
		t.Fatal(err)
	}
	return []byte(`{"protocol_version": 1, "` + key + `": ` + string(data) + `}`)
}

func TestSourceCheckSharedCases(t *testing.T) {
	for _, c := range loadCases(t, filepath.Join(sharedProbe, "capabilities-cases.json")) {
		var name string
		_ = json.Unmarshal(c["name"], &name)
		var req SourceRequest
		if err := json.Unmarshal(c["request"], &req); err != nil {
			t.Fatal(err)
		}
		view := readSourceCheck(probeInput(t, c, "capabilities", "capabilities"), req)
		sameJSON(t, name, view, c["expected"])
		var blocks bool
		_ = json.Unmarshal(c["blocks_install"], &blocks)
		if view.BlocksInstall() != blocks {
			t.Errorf("%s: blocks install = %v, want %v", name, view.BlocksInstall(), blocks)
		}
		sameJSON(t, name+" probe args", probeSourceArgs(req), c["probe_args"])
	}
}

func TestBootcStoreSharedCases(t *testing.T) {
	for _, c := range loadCases(t, filepath.Join(sharedProbe, "bootc-store-cases.json")) {
		var name string
		_ = json.Unmarshal(c["name"], &name)
		sameJSON(t, name, readBootcStore(probeInput(t, c, "bootc-store", "bootc_store")), c["expected"])
	}
}

func TestVerificationSharedCases(t *testing.T) {
	for _, c := range loadCases(t, filepath.Join(sharedCompletion, "verification-cases.json")) {
		var name, fixture, id string
		_ = json.Unmarshal(c["name"], &name)
		_ = json.Unmarshal(c["fixture"], &fixture)
		_ = json.Unmarshal(c["expected_install_id"], &id)
		data, err := os.ReadFile(filepath.Join(sharedCompletion, "fixtures", fixture))
		if err != nil {
			t.Fatal(err)
		}
		sameJSON(t, name, readVerification(data, id), c["expected"])
	}
}

// The command reads the request on stdin and probes nothing when no
// source is selected.
func TestSourceCheckNoSourceProbesNothing(t *testing.T) {
	if got := probeSourceArgs(SourceRequest{}); len(got) != 0 {
		t.Fatalf("args = %v", got)
	}
}

// shared/probe/source-reuse-cases.json (#267): the item offered as the
// second install source, never on live media.
func TestSourceReuseSharedCases(t *testing.T) {
	cases := loadCases(t, filepath.Join(sharedProbe, "source-reuse-cases.json"))
	if len(cases) < 20 {
		t.Fatalf("only %d cases", len(cases))
	}
	for _, c := range cases {
		var name, updateRef string
		var failed bool
		var fixture *string
		var live *bool
		_ = json.Unmarshal(c["name"], &name)
		_ = json.Unmarshal(c["update_ref"], &updateRef)
		_ = json.Unmarshal(c["probe_failed"], &failed)
		_ = json.Unmarshal(c["fixture"], &fixture)
		_ = json.Unmarshal(c["live"], &live)
		var data []byte
		if !failed {
			probe := map[string]any{"protocol_version": 1}
			if fixture != nil {
				raw, err := os.ReadFile(filepath.Join(sharedProbe, "fixtures", "bootc-store", *fixture))
				if err != nil {
					t.Fatal(err)
				}
				probe["bootc_store"] = json.RawMessage(raw)
			}
			if live != nil {
				probe["live"] = map[string]any{"is_live": *live}
			}
			data, _ = json.Marshal(probe)
		}
		got := readReuseSource(data, updateRef)
		if got == nil {
			if string(c["expected"]) != "null" {
				t.Errorf("%s: no item, want %s", name, c["expected"])
			}
			continue
		}
		sameJSON(t, name, got, c["expected"])
	}
}

// bootedReuse offers the system that this computer runs, and nothing on
// live media.
func TestBootedReuse(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(sharedProbe, "fixtures", "bootc-store", "store-inaccessible.json"))
	if err != nil {
		t.Skip("shared/probe is absent")
	}
	probe := func(live bool) []byte {
		data, _ := json.Marshal(map[string]any{"protocol_version": 1, "live": map[string]any{"is_live": live},
			"bootc_store": json.RawMessage(raw)})
		return data
	}
	got := bootedReuse(probe(false))
	if got == nil || got.Ref != "ghcr.io/example/os:stable" {
		t.Fatalf("got %+v", got)
	}
	if bootedReuse(probe(true)) != nil {
		t.Fatal("offered on live media")
	}
	if bootedReuse(nil) != nil {
		t.Fatal("offered without a probe")
	}
}
