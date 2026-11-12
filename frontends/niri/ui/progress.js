.pragma library

// The install bar, from fisherman's progress protocol.
//
// Same semantics as shared/progress/progress_parser.py, the canonical
// parser; the numbers are pinned by shared/progress/fraction-cases.json,
// which tests/progress-fraction-test.mjs feeds through this file. Kept out
// of installer.qml so it can be tested without a QML engine.
//
// fisherman sends the bar itself as overall_pct on step, substep and
// complete events (tuna-os/fisherman#270), and that is what the bar shows:
// clamped to 0-1 and never below the bar before the event. The rest of this
// file is the fallback for an event without it, from an older fisherman;
// shared/progress/overall-pct-cases.json pins both.
//
// The fallback bar is driven by cumulative_pct, never step / total_steps. Inside a
// step, the layer pull covers the first PULL_SHARE of the step's weight and
// the named phases after it (export, deploy, bootloader) cover the rest.
// Before the phases had positions, an offline install sat at 1% through
// ten minutes of export and deploy (#115).

var PULL_SHARE = 0.6

var PHASE_MILESTONES = [
    ["Exporting image to OCI layout", 0.05],
    ["OCI export complete", 0.30],
    ["Using ", 0.32],
    ["Initializing ostree layout", 0.35],
    ["Writing ", 0.35],
    ["Deploying image", 0.35],
    ["OS deployed, installing bootloader", 0.90],
    ["Detected bootloader", 0.92],
    ["Installing bootloader", 0.92],
    ["Configuring EFI boot entry", 0.95],
    ["Configuring GRUB", 0.95],
    ["Configuring SELinux", 0.95],
    ["Generating initramfs", 0.95],
    ["bootc installation complete", 1.0]
]

function newState() {
    return { step: 0, cumulativePct: 0, weightPct: 0, stepFrac: 0, postPullBase: -1, fraction: 0,
             error: null, receipt: null, sourceReuse: null }
}

// fisherman's `receipt` event (#269) as {state, install_id, reason}:
// bootc_shared.progress.receipt_of (shared/progress/receipt-cases.json).
function receiptOf(event) {
    function view(state, installId, reason) {
        return { state: state, install_id: installId || "", reason: reason || "" }
    }
    if (typeof event.version !== "number" || event.version !== 1)
        return view("unreadable")
    if (typeof event.written !== "boolean")
        return view("unreadable")
    var reason = typeof event.reason === "string" && /^[a-z0-9_]{1,64}$/.test(event.reason)
        ? event.reason : ""
    if (!event.written)
        return view("not_written", "", reason)
    var id = event.install_id
    if (typeof id !== "string" || !/^[0-9a-f]{32}$/.test(id))
        return view("unreadable")
    if (event.first_boot_check === true)
        return view("check_set_up", id)
    return view("written_no_check", id, reason)
}

// The done page's copy keys after an install that exited 0, with the
// {value} of each: bootc_shared.completion.receipt_lines. `hasKey(key)`
// says whether the copy has a line for a key; null receipt: no event came.
function receiptLines(receipt, hasKey) {
    var lines = [{ key: "done_verification", value: "" }]
    var states = ["check_set_up", "written_no_check", "not_written"]
    if (!receipt) {
        lines.push({ key: "done_receipt_none", value: "" })
        return lines
    }
    if (states.indexOf(receipt.state) < 0) {
        lines.push({ key: "done_receipt_unreadable", value: "" })
        return lines
    }
    lines.push({ key: "done_receipt_" + receipt.state, value: receipt.install_id || "" })
    if (receipt.state !== "check_set_up") {
        var key = "done_receipt_reason_" + (receipt.reason || "unknown")
        lines.push({ key: hasKey(key) ? key : "done_receipt_reason_unknown", value: "" })
    }
    return lines
}

// The recipe with this computer's system as its install source (#267):
// bootc_shared.source_check.apply_reuse. `source` is {ref, digest,
// platform} from the backend's `detect`.
function applyReuse(recipe, source) {
    var out = {}
    for (var k in recipe)
        out[k] = recipe[k]
    if (!source)
        return out
    out.targetImgref = recipe.targetImgref || recipe.image || ""
    out.image = ""
    out.sourceReuse = { store: "bootc", digest: source.digest, platform: source.platform }
    var experimental = (recipe.experimental || []).filter(function (e) { return typeof e === "string" })
    if (experimental.indexOf("bootc_store_reuse") < 0)
        experimental.push("bootc_store_reuse")
    out.experimental = experimental
    return out
}

// The `validate --json --partial` fragment for it: no passphrase, no account.
function reuseFragment(recipe) {
    var out = {}
    var keys = ["image", "targetImgref", "experimental", "sourceReuse", "composeFsBackend", "filesystem"]
    for (var i = 0; i < keys.length; i++)
        if (keys[i] in recipe)
            out[keys[i]] = recipe[keys[i]]
    return out
}

// How an install ended: "succeeded", "cancelled" or "failed"
// (shared/progress/outcome-cases.json). `code` is the backend's exit code
// (128 + n for a signal), or null. The exit code decides, never a
// `complete` event. After a confirmed cancel, 130 or a signal is the
// cancel; another exit code is fisherman's own failure.
function installOutcome(code, cancelRequested) {
    if (code === 0)
        return "succeeded"
    if (code === 130)
        return "cancelled"
    if (cancelRequested && (code === null || code === undefined || code > 128))
        return "cancelled"
    return "failed"
}

// A byte count or a time in ms: a whole number >= 0, else null.
function count(v) {
    return typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : null
}

function gib(bytes) {
    return (bytes / 1073741824).toFixed(1)
}

// fisherman's `source_reuse` events (#267): the copy of this computer's
// system before the first step, as bootc_shared.progress.source_reuse_of
// keeps it (shared/progress/source-reuse-cases.json). `view` is the one
// before the event, or null.
function sourceReuseOf(event, view) {
    var out = {}
    if (view) {
        for (var k in view)
            out[k] = view[k]
    } else {
        out = { phase: "", required_bytes: null, destination_digest: "", copy_ms: null,
                used_bytes: null, code: "", released: "", destination: "" }
    }
    if (typeof event.version !== "number" || event.version !== 1) {
        out.phase = "unreadable"
        return out
    }
    var phase = event.phase
    if (["planned", "copying", "verified", "failed", "released"].indexOf(phase) < 0)
        return view
    if (typeof event.destination === "string" && event.destination !== "")
        out.destination = event.destination
    if (phase === "released") {
        out.released = event.reason === "removed" || event.reason === "remove_failed" ? event.reason : "unknown"
        return out
    }
    out.phase = phase
    var estimate = event.estimate !== null && typeof event.estimate === "object" ? event.estimate : {}
    if ("required_bytes" in estimate)
        out.required_bytes = count(estimate.required_bytes)
    if (phase === "verified") {
        var d = event.destination_digest
        out.destination_digest = typeof d === "string" && /^sha256:[0-9a-f]{64}$/.test(d) ? d : ""
        var measured = event.measured !== null && typeof event.measured === "object" ? event.measured : {}
        out.copy_ms = count(measured.copy_ms)
        var scratch = count(measured.scratch_peak_bytes)
        var store = count(measured.store_peak_bytes)
        if (scratch === null || store === null)
            out.used_bytes = null
        else
            out.used_bytes = estimate.same_filesystem === false ? scratch + store : Math.max(scratch, store)
    }
    if (phase === "failed")
        out.code = typeof event.code === "string" && /^[a-z0-9_]{1,64}$/.test(event.code) ? event.code : ""
    return out
}

// The progress page's copy keys for the copy, with the {value} of each:
// bootc_shared.progress.source_reuse_lines. `hasKey(key)` says whether the
// copy has a line for a key.
function sourceReuseLines(view, hasKey) {
    var lines = []
    if (!view)
        return lines
    var prefix = "progress_reuse_"
    var space = view.required_bytes !== null ? { key: prefix + "planned", value: gib(view.required_bytes) } : null
    if (view.phase === "unreadable") {
        lines.push({ key: prefix + "unreadable", value: "" })
    } else if (view.phase === "planned" || view.phase === "copying") {
        lines.push(space || { key: prefix + "planned_unknown", value: "" })
        if (view.phase === "copying")
            lines.push({ key: prefix + "copying", value: "" })
    } else if (view.phase === "verified") {
        lines.push({ key: prefix + "verified", value: "" })
        if (view.destination_digest)
            lines.push({ key: prefix + "verified_digest", value: view.destination_digest })
        if (view.copy_ms !== null)
            lines.push({ key: prefix + "measured_time", value: String(Math.floor((view.copy_ms + 500) / 1000)) })
        if (view.used_bytes !== null)
            lines.push({ key: prefix + "measured_space", value: gib(view.used_bytes) })
    } else if (view.phase === "failed") {
        if (space)
            lines.push(space)
        var code = view.code || ""
        var key = code.indexOf("source_reuse_") === 0 ? prefix + "failed_" + code.slice("source_reuse_".length) : ""
        lines.push({ key: key && hasKey(key) ? key : prefix + "failed_unknown", value: "" })
    }
    if (view.released) {
        var destination = view.destination || ""
        if (destination.indexOf("containers-storage:") === 0)
            destination = destination.slice("containers-storage:".length)
        lines.push({ key: prefix + "released_" + view.released,
                     value: view.released === "remove_failed" ? destination : "" })
    }
    return lines
}

// Whether a cancel now stops only the copy and leaves the disk as it was:
// bootc_shared.progress.copy_cancel.
function copyCancel(state) {
    var view = state.sourceReuse
    return !!view && ["planned", "copying", "verified"].indexOf(view.phase) >= 0
        && !view.released && !(state.step > 0)
}

// A registry reference without its docker:// transport.
function plainRef(ref) {
    ref = (ref || "").trim()
    return ref.indexOf("docker://") === 0 ? ref.slice("docker://".length) : ref
}

// The parts of an `error` event: {message, code, field}, "" for a part that
// is missing or is not a string (shared/progress/error-cases.json).
// fisherman's `error` event as bootc_shared.progress._error_of() keeps it
// (shared/progress/error-cases.json): the strings are "" when missing or not
// a string; disk_changed is the boolean, else null; cleanup is
// {status, message}, else null, and a status other than ok, failed or
// timed_out is "" (tuna-os/fisherman#449).
function errorOf(event) {
    function text(source, key) {
        return typeof source[key] === "string" ? source[key] : ""
    }
    var cleanup = null
    var c = event.cleanup
    if (c !== null && typeof c === "object" && !Array.isArray(c)) {
        var status = text(c, "status")
        cleanup = {
            status: ["ok", "failed", "timed_out"].indexOf(status) >= 0 ? status : "",
            message: text(c, "message")
        }
    }
    return {
        message: text(event, "message"), code: text(event, "code"), field: text(event, "field"),
        step_id: text(event, "step_id"),
        disk_changed: typeof event.disk_changed === "boolean" ? event.disk_changed : null,
        cleanup: cleanup
    }
}

// The failure page's copy keys for the last `error` event, in order:
// whether the disk changed, then a cleanup that failed or timed out
// (bootc_shared.progress.failure_lines). A part fisherman did not send
// adds no line.
function failureLines(error) {
    var lines = []
    if (!error)
        return lines
    if (error.disk_changed === true)
        lines.push("done_failed_disk_changed")
    else if (error.disk_changed === false)
        lines.push("done_failed_disk_unchanged")
    var status = error.cleanup ? error.cleanup.status : ""
    if (status === "failed")
        lines.push("done_failed_cleanup_failed")
    else if (status === "timed_out")
        lines.push("done_failed_cleanup_timed_out")
    return lines
}

function milestone(message) {
    for (var i = 0; i < PHASE_MILESTONES.length; i++) {
        if (message.indexOf(PHASE_MILESTONES[i][0]) === 0)
            return PHASE_MILESTONES[i][1]
    }
    return -1
}

// fisherman's own bar as a fraction, or -1 when the event has none.
function overallFraction(event) {
    if (typeof event.overall_pct !== "number" || !isFinite(event.overall_pct))
        return -1
    return Math.min(Math.max(event.overall_pct / 100, 0), 1)
}

// The label for a step event: lookup(step_id), which installer.qml points at
// the branding copy key "step_" + step_id. An event without a step_id, or an
// id the copy has no line for (lookup returns ""), shows fisherman's
// step_name.
function stepLabel(event, lookup) {
    if (event.step_id) {
        var label = lookup(event.step_id)
        if (label)
            return label
    }
    return event.step_name || ""
}

// Applies one parsed event to `state` and returns the bar fraction (0-1).
function advance(state, event) {
    var before = state.fraction
    // fisherman's reason for a failure: the last one is kept, and it does
    // not move the bar.
    if (event.type === "error")
        state.error = errorOf(event)
    // What the install did with the receipt; it moves no bar.
    if (event.type === "receipt")
        state.receipt = receiptOf(event)
    // The copy before the first step; it moves no bar.
    if (event.type === "source_reuse")
        state.sourceReuse = sourceReuseOf(event, state.sourceReuse)
    derive(state, event)
    var overall = overallFraction(event)
    if (overall >= 0 && (event.type === "step" || event.type === "substep"))
        state.fraction = Math.max(before, overall)
    return state.fraction
}

// The fallback: the bar from cumulative_pct, weight_pct and the substep
// messages, for an event without overall_pct.
function derive(state, event) {
    if (event.type === "step") {
        var step = event.step || 0
        // A repeated or earlier step is ignored: it must not reset the bar.
        if (state.step > 0 && step <= state.step)
            return
        state.step = step
        state.cumulativePct = event.cumulative_pct || 0
        state.weightPct = event.weight_pct || 0
        state.stepFrac = 0
        state.postPullBase = -1
        state.fraction = state.cumulativePct / 100
    } else if (event.type === "substep" && state.weightPct > 0) {
        var message = event.message || ""
        var stepFrac = -1
        var m = /^Pulling image: layer (\d+)\/(\d+)/.exec(message)
        if (m) {
            var total = parseInt(m[2])
            if (total > 0)
                stepFrac = Math.min(parseInt(m[1]) / total, 1) * PULL_SHARE
        } else {
            var share = milestone(message)
            if (share >= 0) {
                if (state.postPullBase < 0)
                    state.postPullBase = state.stepFrac
                stepFrac = state.postPullBase + share * (1 - state.postPullBase)
            }
        }
        if (stepFrac >= 0) {
            // Never move backwards: a retried pull restarts its layer count.
            state.stepFrac = Math.max(state.stepFrac, stepFrac)
            state.fraction = Math.min(
                (state.cumulativePct + state.stepFrac * state.weightPct) / 100, 1)
        }
    } else if (event.type === "complete") {
        // cumulative_pct only ever reaches 99; `complete` fills the bar.
        state.fraction = 1
    }
}
