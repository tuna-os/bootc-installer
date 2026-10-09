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
    return { step: 0, cumulativePct: 0, weightPct: 0, stepFrac: 0, postPullBase: -1, fraction: 0 }
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
