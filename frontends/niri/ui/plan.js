.pragma library

// The install plan of the confirm page (tuna-os/fisherman#371).
//
// The backend's `plan` runs `fisherman plan --json -` and prints a view
// (installer/plan.go): the rows as kinds with their values, the target disk,
// the recipe's `diskIdentity` and its `planBinding`. rows() gives each kind
// its copy keys; bind() copies the identity and the binding into the install
// recipe. The rules are those of
// shared/python/bootc_shared/plan.py; installer/plan_test.go sends
// fisherman's golden plans through the backend and this file (under node,
// tests/plan-rows.mjs) and checks the lines of the Python reader.

// kind -> [title key, detail key]. A kind not here is a device that the
// install destroys with an effect this build has no line for: its data is
// still lost, so it reads as a format.
var KEYS = {
    target: ["confirm_plan_target", "confirm_plan_target_detail"],
    bound: ["confirm_plan_bound", ""],
    unbound: ["confirm_plan_unbound", ""],
    wipe_disk: ["confirm_plan_wipe_disk", ""],
    format: ["confirm_plan_format", ""],
    mkswap: ["confirm_plan_mkswap", ""]
}

// [{title, subtitle}] of a view, in the words of `text(key, values)`. A
// value that the plan does not know is confirm_plan_unknown. A row whose
// title the branding hides ("") is left out.
function rows(view, text) {
    var out = []
    if (!view || !view.valid || !Array.isArray(view.rows))
        return out
    var unknown = text("confirm_plan_unknown", {}) || "unknown"
    for (var i = 0; i < view.rows.length; i++) {
        var row = view.rows[i] || {}
        var keys = KEYS[row.kind] || KEYS.format
        var values = {}
        var given = row.values || {}
        for (var k in given)
            values[k] = given[k] !== "" ? given[k] : unknown
        var title = text(keys[0], values)
        if (title === "")
            continue
        out.push({ title: title, subtitle: keys[1] !== "" ? text(keys[1], values) : "" })
    }
    return out
}

// `recipe` with `diskIdentity` and `planBinding` from the view, or `recipe`
// itself when the plan cannot bind it. `diskIdentity` needs a known identity
// of the recipe's `disk` (not a manual layout or a plan for another disk);
// `planBinding` needs a binding (installer/plan.go copies only a well-formed
// one) and a plan that is not for another disk than the recipe's `disk`: a
// manual layout, which has no target disk, is still bound to its plan.
function bind(recipe, view) {
    if (!view || !view.valid || !recipe)
        return recipe
    var fields = {}
    var any = false
    if (view.diskIdentity && view.disk && view.disk === recipe.disk) {
        var identity = {}
        var known = false
        for (var k in view.diskIdentity) {
            identity[k] = view.diskIdentity[k]
            known = true
        }
        if (known) {
            fields.diskIdentity = identity
            any = true
        }
    }
    var saved = view.planBinding
    if (saved && typeof saved.digest === "string" && /^sha256:[0-9a-f]{64}$/.test(saved.digest)
            && (!view.disk || view.disk === recipe.disk)) {
        var binding = { digest: saved.digest }
        if (typeof saved.readImage === "boolean")
            binding.readImage = saved.readImage
        fields.planBinding = binding
        any = true
    }
    if (!any)
        return recipe
    var bound = {}
    for (var key in recipe)
        bound[key] = recipe[key]
    for (var f in fields)
        bound[f] = fields[f]
    return bound
}
