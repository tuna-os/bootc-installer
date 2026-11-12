package main

// The source check (#266), the live host's bootc storage (#267) and the
// boot verification result (#269): a port of the canonical Python readers
// in shared/python/bootc_shared/source_check.py and completion.py.
//
// fisherman owns the facts (fisherman/docs/PROBE.md, docs/RECEIPT.md).
// These readers only turn its answer into a state and the copy keys that
// shared/probe/README.md and shared/completion/README.md name. They decide
// no compatibility rule. sourcecheck_test.go reads the shared case files
// (shared/probe/capabilities-cases.json, bootc-store-cases.json and
// shared/completion/verification-cases.json) and must give the same views
// as the Python reader.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
)

const (
	capabilitiesVersion = 1
	bootcStoreVersion   = 1
	verificationSchema  = "fisherman.boot-verification"
	verificationVersion = 1
)

var knownFeatures = map[string]bool{
	"bootc_image_storage": true, "deployment_mount": true, "finalization": true,
	"install_configuration": true, "native_inspection": true, "unified_storage": true,
}

var codeToken = regexp.MustCompile(`^[a-z0-9_]{1,64}$`)

// SourceRequest is the selection a probe ran for.
type SourceRequest struct {
	Source   string   `json:"source"`
	LiveRoot bool     `json:"live_root"`
	Target   string   `json:"target"`
	Features []string `json:"features"`
}

// DefaultLine is one install default that the source's bootc reported.
type DefaultLine struct {
	Key   string `json:"key"`
	Value string `json:"value"`
}

// SourceCheck is what a frontend shows for the source check.
type SourceCheck struct {
	State         string        `json:"state"`
	Reason        string        `json:"reason"`
	ReasonKey     string        `json:"reason_key"`
	InstallFrom   string        `json:"install_from"`
	UpdateRef     string        `json:"update_ref"`
	LiveHostImage string        `json:"live_host_image"`
	SourceDigest  string        `json:"source_digest"`
	Defaults      []DefaultLine `json:"defaults"`
	Blockers      []string      `json:"blockers"`
}

// BlocksInstall: only a blocked source holds Install.
func (v SourceCheck) BlocksInstall() bool { return v.State == "blocked" }

// StoreItem is one image of the live host's bootc storage. Never
// installable: no fisherman install path reads bootc-owned storage yet.
type StoreItem struct {
	Ref            string `json:"ref"`
	Kind           string `json:"kind"`
	Availability   string `json:"availability"`
	Storage        string `json:"storage"`
	Digest         string `json:"digest"`
	Platform       string `json:"platform"`
	MatchesMachine bool   `json:"matches_machine"`
	Installable    bool   `json:"installable"`
}

// BootcStore is what a frontend shows for the live host's bootc storage.
type BootcStore struct {
	State  string      `json:"state"`
	Reason string      `json:"reason"`
	Items  []StoreItem `json:"items"`
	Hidden int         `json:"hidden"`
}

// Verification is the view of one `fisherman verify --json` result.
type Verification struct {
	State  string `json:"state"`
	Reason string `json:"reason"`
}

func decodeAny(data []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return v, nil
}

func jObj(v any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}

func jStr(v any) string {
	s, _ := v.(string)
	return s
}

func jTrue(v any) bool {
	b, ok := v.(bool)
	return ok && b
}

// jInt is an integer number (not 1.0, not a bool).
func jInt(v any) (int64, bool) {
	n, ok := v.(json.Number)
	if !ok {
		return 0, false
	}
	i, err := strconv.ParseInt(string(n), 10, 64)
	return i, err == nil
}

func jToken(v any) string {
	s := jStr(v)
	if codeToken.MatchString(s) {
		return s
	}
	return "unknown"
}

// reasonKey is the copy key that explains reason, or the unknown line.
func reasonKey(reason string) string {
	key := "source_check_reason_" + jToken(reason)
	if _, ok := copyDefaults()[key]; ok {
		return key
	}
	return "source_check_reason_unknown"
}

func newCheck(state, reason string) SourceCheck {
	return SourceCheck{State: state, Reason: reason, ReasonKey: reasonKey(reason),
		Defaults: []DefaultLine{}, Blockers: []string{}}
}

func checkIsStale(caps map[string]any, req SourceRequest) bool {
	source := jObj(caps["source"])
	target := jObj(caps["target"])
	switch {
	case req.LiveRoot:
		if jStr(source["transport"]) != "live-root" {
			return true
		}
	case req.Source != "":
		if jStr(source["ref"]) != req.Source || jStr(source["transport"]) == "live-root" {
			return true
		}
	default:
		if jTrue(source["selected"]) {
			return true
		}
	}
	fromTarget := jStr(target["update_ref_from"]) == "target_imgref"
	if req.Target != "" {
		return !fromTarget || jStr(target["update_ref"]) != req.Target
	}
	return fromTarget
}

// readSourceCheck reads the probe output in data (nil: the probe failed).
func readSourceCheck(data []byte, req SourceRequest) SourceCheck {
	if data == nil {
		return newCheck("unavailable", "probe_failed")
	}
	v, err := decodeAny(data)
	result, ok := v.(map[string]any)
	if err != nil || !ok {
		return newCheck("unavailable", "probe_failed")
	}
	capsAny, present := result["capabilities"]
	if !present {
		return newCheck("unsupported", "backend_too_old")
	}
	caps, ok := capsAny.(map[string]any)
	if !ok {
		return newCheck("unavailable", "malformed")
	}
	version, ok := jInt(caps["version"])
	if !ok {
		return newCheck("unavailable", "malformed")
	}
	if version != capabilitiesVersion {
		return newCheck("unsupported", "version_unsupported")
	}
	if checkIsStale(caps, req) {
		return newCheck("stale", "reply_for_other_source")
	}
	source := jObj(caps["source"])
	root := jObj(caps["execution_root"])
	features := jObj(caps["features"])
	blockers := []string{}
	for _, name := range req.Features {
		if knownFeatures[name] && jStr(jObj(features[name])["status"]) == "unsupported" {
			blockers = append(blockers, name)
		}
	}
	var state, reason string
	switch {
	case len(blockers) > 0:
		state, reason = "blocked", "feature_unsupported"
	case !jTrue(source["selected"]):
		state, reason = "unavailable", "no_source_selected"
	case !jTrue(root["established"]):
		state, reason = "unavailable", jToken(root["reason"])
		if dr := jStr(source["digest_reason"]); reason == "source_digest_unknown" && dr != "" {
			reason = jToken(dr)
		}
	default:
		state, reason = "ready", jToken(root["reason"])
	}
	view := newCheck(state, reason)
	view.InstallFrom = jStr(source["ref"])
	view.UpdateRef = jStr(jObj(caps["target"])["update_ref"])
	view.LiveHostImage = jStr(jObj(caps["live_host"])["image"])
	view.SourceDigest = jStr(source["digest"])
	view.Blockers = blockers
	defaults := jObj(caps["install_defaults"])
	if state == "ready" && jTrue(defaults["observed"]) {
		if fs := jStr(defaults["root_filesystem"]); fs != "" {
			view.Defaults = append(view.Defaults, DefaultLine{"source_check_default_filesystem", fs})
		}
		if list, ok := defaults["block_setups"].([]any); ok {
			setups := []string{}
			for _, s := range list {
				if str := jStr(s); str != "" {
					setups = append(setups, str)
				}
			}
			if len(setups) > 0 {
				view.Defaults = append(view.Defaults,
					DefaultLine{"source_check_default_block_setups", strings.Join(setups, ", ")})
			}
		}
		if loader := jStr(defaults["bootloader"]); loader != "" {
			view.Defaults = append(view.Defaults, DefaultLine{"source_check_default_bootloader", loader})
		}
	}
	return view
}

// readBootcStore reads the probe output in data (nil: the probe failed).
func readBootcStore(data []byte) BootcStore {
	view := func(state, reason string) BootcStore {
		return BootcStore{State: state, Reason: reason, Items: []StoreItem{}}
	}
	if data == nil {
		return view("unavailable", "probe_failed")
	}
	v, err := decodeAny(data)
	result, ok := v.(map[string]any)
	if err != nil || !ok {
		return view("unavailable", "probe_failed")
	}
	storeAny, present := result["bootc_store"]
	if !present {
		return view("unsupported", "backend_too_old")
	}
	store, ok := storeAny.(map[string]any)
	if !ok {
		return view("unavailable", "malformed")
	}
	version, ok := jInt(store["version"])
	if !ok {
		return view("unavailable", "malformed")
	}
	if version != bootcStoreVersion {
		return view("unsupported", "version_unsupported")
	}
	if !jTrue(store["available"]) {
		return view("unavailable", jToken(store["reason"]))
	}
	raw, ok := store["items"].([]any)
	if !ok {
		return view("unavailable", "malformed")
	}
	out := view("empty", "observed")
	for _, entry := range raw {
		item := jObj(entry)
		ref := jStr(item["ref"])
		if ref == "" || jStr(item["owner"]) != "bootc" || jStr(item["context"]) != "live-host" {
			out.Hidden++
			continue
		}
		booted := false
		if roles, ok := item["roles"].([]any); ok {
			for _, r := range roles {
				if jStr(r) == "booted" {
					booted = true
				}
			}
		}
		availability := jStr(item["availability"])
		switch availability {
		case "deployed", "stored", "listed":
		default:
			availability = "listed"
		}
		kind := availability
		if booted {
			kind = "booted"
		}
		storage := jStr(item["storage"])
		if storage == "" {
			storage = "unknown"
		}
		out.Items = append(out.Items, StoreItem{
			Ref: ref, Kind: kind, Availability: availability, Storage: storage,
			Digest: jStr(item["digest"]), Platform: jStr(item["platform"]),
			MatchesMachine: jTrue(item["matches_machine"]),
		})
	}
	if len(out.Items) > 0 {
		out.State = "listed"
	}
	return out
}

var verificationOutcomes = map[string]string{
	"verified": "verified", "mismatch": "mismatch", "unsupported": "unsupported",
	"unavailable": "unavailable", "not-yet-run": "pending",
}

// readVerification reads one `fisherman verify --json` result.
// expectedInstallID binds it to an install the caller knows of ("" none).
func readVerification(data []byte, expectedInstallID string) Verification {
	v, err := decodeAny(data)
	result, ok := v.(map[string]any)
	if err != nil || !ok || jStr(result["schema"]) != verificationSchema {
		return Verification{"unavailable", "result_malformed"}
	}
	version, ok := jInt(result["version"])
	if !ok {
		return Verification{"unavailable", "result_malformed"}
	}
	if version != verificationVersion {
		return Verification{"unsupported", "result_version_unsupported"}
	}
	if expectedInstallID != "" && jStr(result["install_id"]) != expectedInstallID {
		return Verification{"unavailable", "other_install"}
	}
	reason := jToken(result["reason"])
	state, known := verificationOutcomes[jStr(result["outcome"])]
	if _, isString := result["outcome"].(string); !known || !isString {
		return Verification{"unavailable", "outcome_unknown"}
	}
	if state == "verified" {
		evidence := jStr(result["evidence"])
		if evidence != "live_status" && evidence != "collected_status" {
			return Verification{"unavailable", "wrong_execution_context"}
		}
		checks, ok := result["checks"].(map[string]any)
		if !ok {
			return Verification{"unavailable", "result_inconsistent"}
		}
		for _, c := range checks {
			if jStr(c) == "mismatch" {
				return Verification{"unavailable", "result_inconsistent"}
			}
		}
	}
	return Verification{state, reason}
}

// probeSourceArgs are the arguments after `probe --json` that select req.
func probeSourceArgs(req SourceRequest) []string {
	var args []string
	switch {
	case req.LiveRoot:
		args = append(args, "--live-root")
	case req.Source != "":
		args = append(args, "--source", req.Source)
	default:
		return []string{}
	}
	if req.Target != "" {
		args = append(args, "--target-imgref", req.Target)
	}
	return args
}

// runSourceProbe runs `fisherman probe --json` for req, unprivileged, or
// reads BOOTC_INSTALLER_FAKE_PROBE. nil when it failed.
func runSourceProbe(req SourceRequest) []byte {
	if fake := os.Getenv(fakeProbeEnv); fake != "" {
		data, err := os.ReadFile(fake)
		if err != nil {
			return nil
		}
		return data
	}
	fisherman, err := resolveFisherman()
	if err != nil {
		return nil
	}
	argv := fisherman.Argv(append([]string{"probe", "--json"}, probeSourceArgs(req)...)...)
	ctx, cancel := context.WithTimeout(context.Background(), probeTimeout)
	defer cancel()
	out, err := exec.CommandContext(ctx, argv[0], argv[1:]...).Output()
	if err != nil || ctx.Err() != nil {
		return nil
	}
	return out
}

// sourceCheckMain is the `source-check` command: the request as JSON on
// stdin ({"source", "live_root", "target", "features"}), the views on
// stdout ({"check": SourceCheck, "store": BootcStore, "blocks_install"}).
// The QML drops a reply whose request is not its current one.
func sourceCheckMain() {
	var req SourceRequest
	if err := json.NewDecoder(os.Stdin).Decode(&req); err != nil {
		fmt.Fprintf(os.Stderr, "source-check: read request: %v\n", err)
		os.Exit(2)
	}
	if req.Features == nil {
		req.Features = []string{}
	}
	var data []byte
	if len(probeSourceArgs(req)) > 0 {
		data = runSourceProbe(req)
	}
	check := readSourceCheck(data, req)
	out, _ := json.Marshal(map[string]any{
		"request":        req,
		"check":          check,
		"store":          readBootcStore(data),
		"blocks_install": check.BlocksInstall(),
	})
	fmt.Println(string(out))
}

// ReuseSource is the item of this computer's bootc storage that the install
// may copy instead of a download (#267, shared/probe/source-reuse-cases.json).
type ReuseSource struct {
	Ref      string `json:"ref"`
	Digest   string `json:"digest"`
	Platform string `json:"platform"`
}

var (
	reuseDigest   = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	reusePlatform = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$`)
)

// plainRef is a registry reference without its docker:// transport.
func plainRef(ref string) string {
	return strings.TrimPrefix(strings.TrimSpace(ref), "docker://")
}

func jRoles(item map[string]any) []string {
	raw, _ := item["roles"].([]any)
	out := []string{}
	for _, r := range raw {
		if s, ok := r.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func hasRole(item map[string]any, role string) bool {
	for _, r := range jRoles(item) {
		if r == role {
			return true
		}
	}
	return false
}

// readReuseSource is bootc_shared.source_check.reuse_source: the item that
// qualifies for updateRef (the recipe's targetImgref), or nil. data is the
// plain probe's output. Never on live media.
func readReuseSource(data []byte, updateRef string) *ReuseSource {
	if data == nil {
		return nil
	}
	v, err := decodeAny(data)
	if err != nil {
		return nil
	}
	root, ok := v.(map[string]any)
	if !ok {
		return nil
	}
	live, ok := root["live"].(map[string]any)
	if !ok {
		return nil
	}
	if isLive, ok := live["is_live"].(bool); !ok || isLive {
		return nil
	}
	store, ok := root["bootc_store"].(map[string]any)
	if !ok {
		return nil
	}
	if n, ok := jInt(store["version"]); !ok || n != 1 || !jTrue(store["available"]) {
		return nil
	}
	items, ok := store["items"].([]any)
	if !ok {
		return nil
	}
	want := plainRef(updateRef)
	if want == "" {
		return nil
	}
	for _, it := range items {
		item := jObj(it)
		if jStr(item["ref"]) == want && hasRole(item, "staged") {
			return nil
		}
	}
	for _, it := range items {
		item := jObj(it)
		digest, platform := jStr(item["digest"]), jStr(item["platform"])
		if jStr(item["ref"]) == want && hasRole(item, "booted") &&
			jStr(item["owner"]) == "bootc" && jStr(item["context"]) == "live-host" &&
			jStr(item["storage"]) == "ostree" && jStr(item["availability"]) == "deployed" &&
			jTrue(item["matches_machine"]) &&
			reuseDigest.MatchString(digest) && reusePlatform.MatchString(platform) {
			return &ReuseSource{Ref: want, Digest: digest, Platform: platform}
		}
	}
	return nil
}

// bootedReuse is the item that the probe offers for the reference of the
// system that this computer runs (bootc_shared.source_check.offers_reuse).
// `detect` gives it to the QML: the image page, which comes before the
// confirm page, then lets a computer without a network go on to the choice.
func bootedReuse(data []byte) *ReuseSource {
	v, err := decodeAny(data)
	if err != nil {
		return nil
	}
	items, _ := jObj(jObj(v)["bootc_store"])["items"].([]any)
	for _, it := range items {
		item := jObj(it)
		if hasRole(item, "booted") {
			if src := readReuseSource(data, jStr(item["ref"])); src != nil {
				return src
			}
		}
	}
	return nil
}
