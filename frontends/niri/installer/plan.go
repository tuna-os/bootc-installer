package main

// `fisherman plan --json -` for the confirm page (fisherman/docs/PLAN.md,
// tuna-os/fisherman#371): a port of the canonical Python reader in
// shared/python/bootc_shared/plan.py.
//
// A plan says what an install of a recipe would do, before anything is
// written: the target disk and what it reports about itself, and every
// device whose data the install destroys. `plan` needs no root, so it runs
// as `validate` does: unprivileged, through resolveFisherman, with the
// recipe on stdin and never on argv (the recipe can hold the LUKS
// passphrase). The plan itself holds no secret.
//
// This backend prints a view for the QML: the rows of the page as kinds
// with their values, the recipe's `diskIdentity` and its `planBinding`.
// ui/plan.js turns the kinds into the confirm_plan_* copy keys and binds
// the install recipe.
// plan_test.go reads fisherman's golden plans and must give the rows and
// the binding of the Python reader.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// planProtocolVersion is the schema version this reader understands.
const planProtocolVersion = 1

// planTimeout bounds one plan. It reads the target disk's facts (one lsblk
// call) and the TPM; this bounds a hung flatpak-spawn or a slow udev.
const planTimeout = 20 * time.Second

// planUnknown is the value of a field that only the install can resolve.
const planUnknown = "unknown"

// planArgs is what fisherman is asked: the whole recipe on stdin.
var planArgs = []string{"plan", "--json", "-"}

// planEffects are the effects that have a copy key (confirm_plan_<effect>).
// Another effect is shown as "format": the device's data is still lost.
var planEffects = map[string]bool{"wipe_disk": true, "format": true, "mkswap": true}

// DiskIdentity is the recipe's `diskIdentity`: only what the plan knows.
type DiskIdentity struct {
	Serial    string `json:"serial,omitempty"`
	WWN       string `json:"wwn,omitempty"`
	SizeBytes int64  `json:"sizeBytes,omitempty"`
}

func (d DiskIdentity) empty() bool { return d == DiskIdentity{} }

// planDigestPattern is the only digest a binding is copied with:
// `sha256:` and 64 lowercase hex digits (PLAN.md, "plan.binding").
var planDigestPattern = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)

// PlanBinding is the recipe's `planBinding`: plan.binding.digest, and
// read_image as readImage when it is a boolean. fisherman refuses an
// install whose plan is no longer this one (plan_stale).
type PlanBinding struct {
	Digest    string `json:"digest"`
	ReadImage *bool  `json:"readImage,omitempty"`
}

// PlanRow is one line of the confirm page. Kind is "target" (title and
// detail), "bound", "unbound", or the effect of a destroyed device. A value
// that is "" is unknown: the page shows confirm_plan_unknown.
type PlanRow struct {
	Kind   string            `json:"kind"`
	Values map[string]string `json:"values"`
}

// PlanView is what `plan` prints. Disk is the plan's target disk, for the
// binding ("" for a manual layout); DiskIdentity is nil when the plan knows
// no identity of the disk, PlanBinding when the plan has no binding (a
// fisherman before it) or a malformed one.
type PlanView struct {
	Valid        bool          `json:"valid"`
	Errors       []string      `json:"errors"`
	Disk         string        `json:"disk"`
	Rows         []PlanRow     `json:"rows"`
	DiskIdentity *DiskIdentity `json:"diskIdentity,omitempty"`
	PlanBinding  *PlanBinding  `json:"planBinding,omitempty"`
}

// errPlan is "fisherman could not be asked, or its answer was unreadable".
// It is not "the recipe is invalid": the page then shows no plan and binds
// nothing, and the install runs its own checks before it touches a disk.
var errPlan = errors.New("no install plan")

// parsePlan reads fisherman's answer into the view. An older fisherman has
// no `plan` command; whatever it prints instead has no protocol_version.
func parsePlan(text []byte) (PlanView, error) {
	dec := json.NewDecoder(bytes.NewReader(text))
	dec.UseNumber()
	var result map[string]any
	if err := dec.Decode(&result); err != nil {
		return PlanView{}, fmt.Errorf("%w: fisherman plan printed invalid JSON", errPlan)
	}
	if v, ok := result["protocol_version"].(json.Number); !ok || v.String() != strconv.Itoa(planProtocolVersion) {
		return PlanView{}, fmt.Errorf("%w: fisherman plan protocol_version is not %d", errPlan, planProtocolVersion)
	}
	valid, okValid := result["valid"].(bool)
	errs, okErrs := result["errors"].([]any)
	if !okValid || !okErrs {
		return PlanView{}, fmt.Errorf("%w: fisherman plan printed no valid flag or errors list", errPlan)
	}
	plan, isPlan := result["plan"].(map[string]any)
	if valid && !isPlan {
		return PlanView{}, fmt.Errorf("%w: fisherman plan is valid but printed no plan", errPlan)
	}
	view := PlanView{Valid: valid, Errors: []string{}, Rows: []PlanRow{}}
	for _, e := range errs {
		if m, ok := e.(map[string]any); ok {
			if code, ok := m["code"].(string); ok {
				view.Errors = append(view.Errors, code)
			}
		}
	}
	if !valid {
		return view, nil
	}
	target, _ := plan["target"].(map[string]any)
	view.Disk, _ = target["disk"].(string)
	view.Rows = append(planTargetRows(target), planDestroyRows(plan)...)
	if ident := planDiskIdentity(target); !ident.empty() {
		view.DiskIdentity = &ident
	}
	view.PlanBinding = planBindingOf(plan)
	return view, nil
}

// planBindingOf is the recipe's `planBinding` for the plan, or nil when
// the plan has no binding or its digest is not `sha256:` and 64 lowercase
// hex digits.
func planBindingOf(plan map[string]any) *PlanBinding {
	binding, ok := plan["binding"].(map[string]any)
	if !ok {
		return nil
	}
	digest, ok := binding["digest"].(string)
	if !ok || !planDigestPattern.MatchString(digest) {
		return nil
	}
	out := &PlanBinding{Digest: digest}
	if readImage, ok := binding["read_image"].(bool); ok {
		out.ReadImage = &readImage
	}
	return out
}

// planKnown: a string the plan knows, not "unknown" and not empty; else "".
func planKnown(v any) (string, bool) {
	if s, ok := v.(string); ok && s != "" && s != planUnknown {
		return s, true
	}
	return "", false
}

// planSize is a positive whole number of bytes.
func planSize(v any) (int64, bool) {
	n, ok := v.(json.Number)
	if !ok {
		return 0, false
	}
	i, err := n.Int64()
	return i, err == nil && i > 0
}

func planIdentity(target map[string]any) map[string]any {
	ident, _ := target["identity"].(map[string]any)
	return ident
}

// planDiskIdentity is the recipe's `diskIdentity`: serial, wwn and
// sizeBytes of plan.target.identity, each only when the plan knows it.
func planDiskIdentity(target map[string]any) DiskIdentity {
	ident := planIdentity(target)
	var out DiskIdentity
	out.Serial, _ = planKnown(ident["serial"])
	out.WWN, _ = planKnown(ident["wwn"])
	out.SizeBytes, _ = planSize(ident["size_bytes"])
	return out
}

// planTargetRows: the target disk (model, size, serial; "" when unknown)
// and whether the install is bound to it. None for a manual layout.
func planTargetRows(target map[string]any) []PlanRow {
	ident := planIdentity(target)
	if len(ident) == 0 {
		return nil
	}
	values := map[string]string{"disk": "", "model": "", "size": "", "serial": ""}
	values["disk"], _ = target["disk"].(string)
	values["model"], _ = planKnown(ident["model"])
	values["serial"], _ = planKnown(ident["serial"])
	if size, ok := planSize(ident["size_bytes"]); ok {
		values["size"] = formatSize(size)
	}
	bound := planDiskIdentity(target)
	kind := "unbound"
	if bound.Serial != "" || bound.WWN != "" {
		kind = "bound"
	}
	return []PlanRow{{Kind: "target", Values: values}, {Kind: kind, Values: values}}
}

// planDestroyRows: one row per device the install destroys, in fisherman's
// order.
func planDestroyRows(plan map[string]any) []PlanRow {
	entries, _ := plan["destroys"].([]any)
	rows := []PlanRow{}
	for _, e := range entries {
		m, ok := e.(map[string]any)
		if !ok {
			continue
		}
		device, ok := m["device"].(string)
		if !ok || device == "" {
			continue
		}
		effect, _ := m["effect"].(string)
		if !planEffects[effect] {
			effect = "format"
		}
		rows = append(rows, PlanRow{Kind: effect, Values: map[string]string{"disk": device}})
	}
	return rows
}

// formatSize is fisherman's size rule (binary units), as
// bootc_shared.probe.format_size: for the plan's byte count, which has no
// size_label. A disk's size on the disk page is always its size_label.
func formatSize(n int64) string {
	units := []string{"B", "KiB", "MiB", "GiB", "TiB", "PiB"}
	value := float64(n)
	i := 0
	for value >= 1024 && i < len(units)-1 {
		value /= 1024
		i++
	}
	if i == 0 {
		return fmt.Sprintf("%d B", n)
	}
	text := strconv.FormatFloat(value, 'f', 1, 64)
	return strings.TrimSuffix(text, ".0") + " " + units[i]
}

// runPlanWith sends the recipe on stdin to argv and returns the view. Exit
// 0 is a plan, 1 an invalid recipe; anything else, or no answer within the
// timeout, is errPlan. The error names no part of the recipe.
func runPlanWith(argv []string, recipe []byte, timeout time.Duration) (PlanView, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Stdin = bytes.NewReader(recipe)
	var out, errOut bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errOut
	err := cmd.Run()
	if ctx.Err() != nil {
		return PlanView{}, fmt.Errorf("%w: fisherman plan gave no answer in %s", errPlan, timeout)
	}
	code := 0
	if err != nil {
		var exitErr *exec.ExitError
		if !errors.As(err, &exitErr) {
			return PlanView{}, fmt.Errorf("%w: cannot run %s", errPlan, argv[0])
		}
		code = exitErr.ExitCode()
	}
	if code != 0 && code != 1 {
		detail := firstLine(errOut.String())
		if detail == "" {
			detail = "no message"
		}
		return PlanView{}, fmt.Errorf("%w: fisherman plan failed (exit %d): %s", errPlan, code, detail)
	}
	return parsePlan(out.Bytes())
}

func firstLine(s string) string {
	line, _, _ := strings.Cut(strings.TrimSpace(s), "\n")
	return line
}

// runPlanCmd reads the recipe on stdin and prints the view: exit 0. When
// no plan can be had it exits 2 with the reason on stderr, and the QML
// shows no plan.
func runPlanCmd(argv []string, stdin io.Reader, stdout, stderr io.Writer) int {
	recipe, err := io.ReadAll(io.LimitReader(stdin, 1<<20))
	if err != nil {
		fmt.Fprintf(stderr, "read recipe: %v\n", err)
		return 2
	}
	view, err := runPlanWith(argv, recipe, planTimeout)
	if err != nil {
		fmt.Fprintf(stderr, "%v\n", err)
		return 2
	}
	data, _ := json.Marshal(view)
	_, _ = stdout.Write(append(data, '\n'))
	return 0
}

func planMain() {
	fisherman, err := resolveFisherman()
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(2)
	}
	os.Exit(runPlanCmd(fisherman.Argv(planArgs...), os.Stdin, os.Stdout, os.Stderr))
}
