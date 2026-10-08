.pragma library

// The install bar, from fisherman's progress protocol.
//
// Same semantics as shared/progress/progress_parser.py, the canonical
// parser; the numbers are pinned by shared/progress/fraction-cases.json,
// which tests/progress-fraction-test.mjs feeds through this file. Kept out
// of installer.qml so it can be tested without a QML engine.
//
// The bar is driven by cumulative_pct, never step / total_steps. Inside a
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

// Applies one parsed event to `state` and returns the bar fraction (0-1).
function advance(state, event) {
    if (event.type === "step") {
        var step = event.step || 0
        // A repeated or earlier step is ignored: it must not reset the bar.
        if (state.step > 0 && step <= state.step)
            return state.fraction
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
    return state.fraction
}
