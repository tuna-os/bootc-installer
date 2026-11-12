.pragma library

// The install plan of the confirm page (tuna-os/fisherman#371).
//
// The backend's `plan` runs `fisherman plan --json -` and prints a view
// (installer/plan.go): the rows as kinds with their values, the target disk
// and the recipe's `diskIdentity`. rows() gives each kind its copy keys;
// bind() copies the identity into the install recipe. The rules are those of
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

// `recipe` with `diskIdentity` from the view, or `recipe` itself when the
// plan cannot bind it: no plan, a manual layout, no known identity, or a
// plan for another disk than the recipe's `disk`.
function bind(recipe, view) {
    if (!view || !view.valid || !view.diskIdentity || !view.disk || !recipe || view.disk !== recipe.disk)
        return recipe
    var identity = {}
    var any = false
    for (var k in view.diskIdentity) {
        identity[k] = view.diskIdentity[k]
        any = true
    }
    if (!any)
        return recipe
    var bound = {}
    for (var key in recipe)
        bound[key] = recipe[key]
    bound.diskIdentity = identity
    return bound
}
