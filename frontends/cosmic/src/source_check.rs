//! The source check (#266), the live host's bootc storage (#267) and the
//! boot verification result (#269): a port of the canonical Python
//! readers, `shared/python/bootc_shared/source_check.py` and
//! `completion.py`.
//!
//! fisherman owns the facts (fisherman/docs/PROBE.md, docs/RECEIPT.md).
//! These readers only turn its answer into a state and the copy keys that
//! shared/probe/README.md ("Source check") and shared/completion/README.md
//! name. They decide no compatibility rule. The tests below read the
//! shared case files and must give the same views as the Python reader.
//! Each view is a `serde_json::Value` with the keys of the case files.

use serde_json::{json, Map, Value};

const FEATURES: [&str; 6] = [
    "bootc_image_storage",
    "deployment_mount",
    "finalization",
    "install_configuration",
    "native_inspection",
    "unified_storage",
];

/// The selection a probe ran for.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Request {
    /// The recipe's `image`.
    pub source: String,
    /// The recipe leaves `image` empty on live media.
    pub live_root: bool,
    /// The recipe's `targetImgref`.
    pub target: String,
    /// `unified_storage` when the recipe sets `unifiedStorage`.
    pub features: Vec<String>,
}

impl Request {
    /// The request for a recipe as this frontend sends it.
    pub fn from_recipe(recipe: &Value, is_live: bool) -> Self {
        let mut source = str_of(recipe.get("image")).to_string();
        let mut is_live = is_live;
        if recipe.get("sourceReuse").is_some_and(Value::is_object) {
            // A copy of this computer's system: reuse_source() offers only
            // the item whose ref is the update reference.
            source = plain_ref(str_of(recipe.get("targetImgref")));
            is_live = false;
        }
        Request {
            live_root: source.is_empty() && is_live,
            source,
            target: str_of(recipe.get("targetImgref")).to_string(),
            features: if recipe.get("unifiedStorage") == Some(&Value::Bool(true)) {
                vec!["unified_storage".into()]
            } else {
                vec![]
            },
        }
    }

    /// The arguments after `probe --json` that select it; empty when it
    /// names no source.
    pub fn probe_args(&self) -> Vec<String> {
        let mut args: Vec<String> = Vec::new();
        if self.live_root {
            args.push("--live-root".into());
        } else if !self.source.is_empty() {
            args.extend(["--source".to_string(), self.source.clone()]);
        } else {
            return args;
        }
        if !self.target.is_empty() {
            args.extend(["--target-imgref".to_string(), self.target.clone()]);
        }
        args
    }
}

fn str_of(v: Option<&Value>) -> &str {
    v.and_then(Value::as_str).unwrap_or("")
}

fn is_true(v: Option<&Value>) -> bool {
    v == Some(&Value::Bool(true))
}

fn obj(v: Option<&Value>) -> Map<String, Value> {
    v.and_then(Value::as_object).cloned().unwrap_or_default()
}

fn token(v: Option<&Value>) -> String {
    let s = str_of(v);
    let ok = !s.is_empty()
        && s.len() <= 64
        && s.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_');
    if ok { s.to_string() } else { "unknown".to_string() }
}

/// The copy key that explains `reason`, or the unknown line.
pub fn reason_key(reason: &str) -> String {
    let key = format!("source_check_reason_{}", token(Some(&Value::String(reason.into()))));
    if crate::branding::is_contract_key(&key) {
        key
    } else {
        "source_check_reason_unknown".to_string()
    }
}

fn new_check(state: &str, reason: &str) -> Value {
    json!({
        "state": state,
        "reason": reason,
        "reason_key": reason_key(reason),
        "install_from": "",
        "update_ref": "",
        "live_host_image": "",
        "source_digest": "",
        "defaults": [],
        "blockers": [],
    })
}

fn is_stale(caps: &Map<String, Value>, req: &Request) -> bool {
    let source = obj(caps.get("source"));
    let target = obj(caps.get("target"));
    if req.live_root {
        if str_of(source.get("transport")) != "live-root" {
            return true;
        }
    } else if !req.source.is_empty() {
        if str_of(source.get("ref")) != req.source || str_of(source.get("transport")) == "live-root" {
            return true;
        }
    } else if is_true(source.get("selected")) {
        return true;
    }
    let from_target = str_of(target.get("update_ref_from")) == "target_imgref";
    if !req.target.is_empty() {
        return !from_target || str_of(target.get("update_ref")) != req.target;
    }
    from_target
}

fn parse_object(output: Option<&str>) -> Option<Map<String, Value>> {
    serde_json::from_str::<Value>(output?).ok()?.as_object().cloned()
}

/// The view of the source check. `output` is the probe's stdout, or None
/// when the probe failed.
pub fn check(output: Option<&str>, req: &Request) -> Value {
    let Some(result) = parse_object(output) else {
        return new_check("unavailable", "probe_failed");
    };
    let Some(caps_value) = result.get("capabilities") else {
        return new_check("unsupported", "backend_too_old");
    };
    let Some(caps) = caps_value.as_object() else {
        return new_check("unavailable", "malformed");
    };
    let Some(version) = caps.get("version").and_then(Value::as_i64) else {
        return new_check("unavailable", "malformed");
    };
    if caps.get("version").and_then(Value::as_bool).is_some() {
        return new_check("unavailable", "malformed");
    }
    if version != 1 {
        return new_check("unsupported", "version_unsupported");
    }
    if is_stale(caps, req) {
        return new_check("stale", "reply_for_other_source");
    }
    let source = obj(caps.get("source"));
    let root = obj(caps.get("execution_root"));
    let features = obj(caps.get("features"));
    let blockers: Vec<String> = req
        .features
        .iter()
        .filter(|name| {
            FEATURES.contains(&name.as_str())
                && str_of(obj(features.get(name.as_str())).get("status")) == "unsupported"
        })
        .cloned()
        .collect();
    let (state, reason) = if !blockers.is_empty() {
        ("blocked", "feature_unsupported".to_string())
    } else if !is_true(source.get("selected")) {
        ("unavailable", "no_source_selected".to_string())
    } else if !is_true(root.get("established")) {
        let mut reason = token(root.get("reason"));
        let digest_reason = str_of(source.get("digest_reason"));
        if reason == "source_digest_unknown" && !digest_reason.is_empty() {
            reason = token(source.get("digest_reason"));
        }
        ("unavailable", reason)
    } else {
        ("ready", token(root.get("reason")))
    };
    let mut view = new_check(state, &reason);
    view["install_from"] = json!(str_of(source.get("ref")));
    view["update_ref"] = json!(str_of(obj(caps.get("target")).get("update_ref")));
    view["live_host_image"] = json!(str_of(obj(caps.get("live_host")).get("image")));
    view["source_digest"] = json!(str_of(source.get("digest")));
    view["blockers"] = json!(blockers);
    let defaults = obj(caps.get("install_defaults"));
    if state == "ready" && is_true(defaults.get("observed")) {
        let mut lines: Vec<Value> = Vec::new();
        let fs = str_of(defaults.get("root_filesystem"));
        if !fs.is_empty() {
            lines.push(json!({"key": "source_check_default_filesystem", "value": fs}));
        }
        if let Some(list) = defaults.get("block_setups").and_then(Value::as_array) {
            let setups: Vec<&str> = list.iter().filter_map(Value::as_str).filter(|s| !s.is_empty()).collect();
            if !setups.is_empty() {
                lines.push(json!({"key": "source_check_default_block_setups", "value": setups.join(", ")}));
            }
        }
        let loader = str_of(defaults.get("bootloader"));
        if !loader.is_empty() {
            lines.push(json!({"key": "source_check_default_bootloader", "value": loader}));
        }
        view["defaults"] = Value::Array(lines);
    }
    view
}

/// Only a blocked source holds Install.
pub fn blocks_install(view: &Value) -> bool {
    view.get("state").and_then(Value::as_str) == Some("blocked")
}

/// The view of the live host's bootc storage. No item is installable: no
/// fisherman install path reads bootc-owned storage yet.
pub fn bootc_store(output: Option<&str>) -> Value {
    let view = |state: &str, reason: &str| json!({"state": state, "reason": reason, "items": [], "hidden": 0});
    let Some(result) = parse_object(output) else {
        return view("unavailable", "probe_failed");
    };
    let Some(store_value) = result.get("bootc_store") else {
        return view("unsupported", "backend_too_old");
    };
    let Some(store) = store_value.as_object() else {
        return view("unavailable", "malformed");
    };
    let Some(version) = store.get("version").and_then(Value::as_i64) else {
        return view("unavailable", "malformed");
    };
    if version != 1 {
        return view("unsupported", "version_unsupported");
    }
    if !is_true(store.get("available")) {
        return view("unavailable", &token(store.get("reason")));
    }
    let Some(raw) = store.get("items").and_then(Value::as_array) else {
        return view("unavailable", "malformed");
    };
    let mut items: Vec<Value> = Vec::new();
    let mut hidden = 0;
    for entry in raw {
        let item = obj(Some(entry));
        let reference = str_of(item.get("ref"));
        if reference.is_empty()
            || str_of(item.get("owner")) != "bootc"
            || str_of(item.get("context")) != "live-host"
        {
            hidden += 1;
            continue;
        }
        let booted = item
            .get("roles")
            .and_then(Value::as_array)
            .is_some_and(|roles| roles.iter().any(|r| r.as_str() == Some("booted")));
        let availability = match str_of(item.get("availability")) {
            a @ ("deployed" | "stored" | "listed") => a,
            _ => "listed",
        };
        let storage = match str_of(item.get("storage")) {
            "" => "unknown",
            s => s,
        };
        items.push(json!({
            "ref": reference,
            "kind": if booted { "booted" } else { availability },
            "availability": availability,
            "storage": storage,
            "digest": str_of(item.get("digest")),
            "platform": str_of(item.get("platform")),
            "matches_machine": is_true(item.get("matches_machine")),
            "installable": false,
        }));
    }
    let mut out = view(if items.is_empty() { "empty" } else { "listed" }, "observed");
    out["items"] = Value::Array(items);
    out["hidden"] = json!(hidden);
    out
}

/// The view of one `fisherman verify --json` result. `expected_install_id`
/// binds it to an install the caller knows of ("" for none).
///
/// No page reads it: the result is made on the installed system after its
/// first start, where this installer does not run. The tests hold it to the
/// shared cases, so a viewer there has a tested reader.
#[allow(dead_code)]
pub fn verification(text: &str, expected_install_id: &str) -> Value {
    let view = |state: &str, reason: &str| json!({"state": state, "reason": reason});
    let Some(result) = parse_object(Some(text)) else {
        return view("unavailable", "result_malformed");
    };
    if str_of(result.get("schema")) != "fisherman.boot-verification" {
        return view("unavailable", "result_malformed");
    }
    let Some(version) = result.get("version").and_then(Value::as_i64) else {
        return view("unavailable", "result_malformed");
    };
    if version != 1 {
        return view("unsupported", "result_version_unsupported");
    }
    if !expected_install_id.is_empty() && str_of(result.get("install_id")) != expected_install_id {
        return view("unavailable", "other_install");
    }
    let reason = token(result.get("reason"));
    let state = match str_of(result.get("outcome")) {
        "verified" => "verified",
        "mismatch" => "mismatch",
        "unsupported" => "unsupported",
        "unavailable" => "unavailable",
        "not-yet-run" => "pending",
        _ => return view("unavailable", "outcome_unknown"),
    };
    if state == "verified" {
        if !matches!(str_of(result.get("evidence")), "live_status" | "collected_status") {
            return view("unavailable", "wrong_execution_context");
        }
        let Some(checks) = result.get("checks").and_then(Value::as_object) else {
            return view("unavailable", "result_inconsistent");
        };
        if checks.values().any(|c| c.as_str() == Some("mismatch")) {
            return view("unavailable", "result_inconsistent");
        }
    }
    view(state, &reason)
}

/// The rows of the confirm page's Selected image section: (title,
/// subtitle). `check` None means the reply has not come yet.
pub fn rows(check: Option<&Value>, store: Option<&Value>, reuse: bool) -> Vec<(String, String)> {
    let text = crate::branding::text;
    let value_line = |key: &str, value: &str| crate::branding::get().text_with(key, &[("value", value)]);
    let mut out = Vec::new();
    let Some(view) = check else {
        out.push((text(&format!("{}{}", "source_check_", "checking")), String::new()));
        return out;
    };
    let install_from = if reuse { "source_reuse_install_from" } else { "source_install_from" };
    for (key, field) in [
        (install_from, "install_from"),
        ("source_update_ref", "update_ref"),
        ("source_live_host", "live_host_image"),
    ] {
        let value = str_of(view.get(field));
        if !value.is_empty() {
            out.push((value_line(key, value), String::new()));
        }
    }
    out.push((
        text(&format!("{}{}", "source_check_", str_of(view.get("state")))),
        text(str_of(view.get("reason_key"))),
    ));
    for line in view.get("defaults").and_then(Value::as_array).into_iter().flatten() {
        out.push((value_line(str_of(line.get("key")), str_of(line.get("value"))), String::new()));
    }
    if let Some(store) = store.filter(|s| str_of(s.get("state")) == "listed") {
        out.push((text("bootc_store_listed"), String::new()));
        for item in store.get("items").and_then(Value::as_array).into_iter().flatten() {
            out.push((
                str_of(item.get("ref")).to_string(),
                text(&format!("{}{}", "bootc_store_kind_", str_of(item.get("kind")))),
            ));
        }
    }
    out
}

/// A registry reference without its `docker://` transport.
pub fn plain_ref(reference: &str) -> String {
    let r = reference.trim();
    r.strip_prefix("docker://").unwrap_or(r).to_string()
}

fn matches(s: &str, ok: impl Fn(u8) -> bool, max: usize) -> bool {
    !s.is_empty() && s.len() <= max && s.bytes().all(ok)
}

/// fisherman's `receipt` progress event (#269) as {state, install_id,
/// reason}: `bootc_shared.progress.receipt_of()`.
pub fn receipt_of(event: &Value) -> Value {
    let view = |state: &str, id: &str, reason: &str| json!({"state": state, "install_id": id, "reason": reason});
    if event.get("version").and_then(Value::as_i64) != Some(1) || event.get("version").is_some_and(Value::is_f64) {
        return view("unreadable", "", "");
    }
    let Some(written) = event.get("written").and_then(Value::as_bool) else {
        return view("unreadable", "", "");
    };
    let raw = str_of(event.get("reason"));
    let reason = if matches(raw, |b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_', 64) { raw } else { "" };
    if !written {
        return view("not_written", "", reason);
    }
    let id = str_of(event.get("install_id"));
    if !(id.len() == 32 && id.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))) {
        return view("unreadable", "", "");
    }
    if is_true(event.get("first_boot_check")) {
        return view("check_set_up", id, "");
    }
    view("written_no_check", id, reason)
}

/// The done page's copy keys, with the `{value}` of each:
/// `bootc_shared.completion.receipt_lines()`. `receipt` None means no
/// event came.
pub fn receipt_lines(receipt: Option<&Value>) -> Vec<(String, String)> {
    let mut lines = vec![("done_verification".to_string(), String::new())];
    let Some(r) = receipt.filter(|r| r.is_object()) else {
        lines.push(("done_receipt_none".to_string(), String::new()));
        return lines;
    };
    let state = str_of(r.get("state"));
    if !matches!(state, "check_set_up" | "written_no_check" | "not_written") {
        lines.push(("done_receipt_unreadable".to_string(), String::new()));
        return lines;
    }
    lines.push((format!("{}{}", "done_receipt_", state), str_of(r.get("install_id")).to_string()));
    if state != "check_set_up" {
        let reason = str_of(r.get("reason"));
        let key = format!("{}{}", "done_receipt_reason_", if reason.is_empty() { "unknown" } else { reason });
        let key = if crate::branding::is_contract_key(&key) { key } else { "done_receipt_reason_unknown".to_string() };
        lines.push((key, String::new()));
    }
    lines
}

/// A byte count or a time in ms: a whole number >= 0, else null.
fn count(v: Option<&Value>) -> Value {
    v.and_then(Value::as_u64).map_or(Value::Null, Value::from)
}

fn gib(bytes: u64) -> String {
    format!("{:.1}", bytes as f64 / (1u64 << 30) as f64)
}

fn is_code(s: &str) -> bool {
    matches(s, |b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_', 64)
}

/// fisherman's `source_reuse` events (#267): the copy of this computer's
/// system before the first step, as `bootc_shared.progress.source_reuse_of()`
/// keeps it. `view` is the one before this event, None before the first.
pub fn source_reuse_of(event: &Value, view: Option<&Value>) -> Option<Value> {
    let mut out = match view {
        Some(v) if v.is_object() => v.clone(),
        _ => json!({"phase": "", "required_bytes": null, "destination_digest": "", "copy_ms": null,
                    "used_bytes": null, "code": "", "released": "", "destination": ""}),
    };
    if event.get("version").and_then(Value::as_i64) != Some(1) || event.get("version").is_some_and(Value::is_f64) {
        out["phase"] = json!("unreadable");
        return Some(out);
    }
    let phase = str_of(event.get("phase"));
    if !matches!(phase, "planned" | "copying" | "verified" | "failed" | "released") {
        return view.cloned();
    }
    let destination = str_of(event.get("destination"));
    if !destination.is_empty() {
        out["destination"] = json!(destination);
    }
    if phase == "released" {
        let reason = str_of(event.get("reason"));
        out["released"] = json!(if matches!(reason, "removed" | "remove_failed") { reason } else { "unknown" });
        return Some(out);
    }
    out["phase"] = json!(phase);
    let estimate = obj(event.get("estimate"));
    if estimate.contains_key("required_bytes") {
        out["required_bytes"] = count(estimate.get("required_bytes"));
    }
    if phase == "verified" {
        let digest = str_of(event.get("destination_digest"));
        let ok = digest.strip_prefix("sha256:").is_some_and(|h| {
            h.len() == 64 && h.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        });
        out["destination_digest"] = json!(if ok { digest } else { "" });
        let measured = obj(event.get("measured"));
        out["copy_ms"] = count(measured.get("copy_ms"));
        let scratch = measured.get("scratch_peak_bytes").and_then(Value::as_u64);
        let store = measured.get("store_peak_bytes").and_then(Value::as_u64);
        out["used_bytes"] = match (scratch, store) {
            (Some(a), Some(b)) if estimate.get("same_filesystem") == Some(&Value::Bool(false)) => json!(a + b),
            (Some(a), Some(b)) => json!(a.max(b)),
            _ => Value::Null,
        };
    }
    if phase == "failed" {
        let code = str_of(event.get("code"));
        out["code"] = json!(if is_code(code) { code } else { "" });
    }
    Some(out)
}

/// The progress page's copy keys for the copy, with the `{value}` of each:
/// `bootc_shared.progress.source_reuse_lines()`.
pub fn source_reuse_lines(view: Option<&Value>) -> Vec<(String, String)> {
    let mut lines = Vec::new();
    let Some(v) = view.filter(|v| v.is_object()) else {
        return lines;
    };
    let key = |k: &str| format!("{}{k}", "progress_reuse_");
    let phase = str_of(v.get("phase"));
    let space = v.get("required_bytes").and_then(Value::as_u64).map(|b| (key("planned"), gib(b)));
    match phase {
        "unreadable" => lines.push((key("unreadable"), String::new())),
        "planned" | "copying" => {
            lines.push(space.clone().unwrap_or((key("planned_unknown"), String::new())));
            if phase == "copying" {
                lines.push((key("copying"), String::new()));
            }
        }
        "verified" => {
            lines.push((key("verified"), String::new()));
            let digest = str_of(v.get("destination_digest"));
            if !digest.is_empty() {
                lines.push((key("verified_digest"), digest.to_string()));
            }
            if let Some(ms) = v.get("copy_ms").and_then(Value::as_u64) {
                lines.push((key("measured_time"), ((ms + 500) / 1000).to_string()));
            }
            if let Some(b) = v.get("used_bytes").and_then(Value::as_u64) {
                lines.push((key("measured_space"), gib(b)));
            }
        }
        "failed" => {
            if let Some(space) = space {
                lines.push(space);
            }
            let failed = str_of(v.get("code"))
                .strip_prefix("source_reuse_")
                .map(|c| key(&format!("failed_{c}")))
                .filter(|k| crate::branding::is_contract_key(k));
            lines.push((failed.unwrap_or_else(|| key("failed_unknown")), String::new()));
        }
        _ => {}
    }
    let released = str_of(v.get("released"));
    if !released.is_empty() {
        let destination = str_of(v.get("destination"));
        let destination = destination.strip_prefix("containers-storage:").unwrap_or(destination);
        let value = if released == "remove_failed" { destination.to_string() } else { String::new() };
        lines.push((key(&format!("released_{released}")), value));
    }
    lines
}

/// Whether a cancel now stops only the copy and leaves the disk as it was:
/// `bootc_shared.progress.copy_cancel()`. `step` is the current step, 0
/// before the first.
pub fn copy_cancel(view: Option<&Value>, step: u64) -> bool {
    let Some(v) = view.filter(|v| v.is_object()) else {
        return false;
    };
    step == 0
        && matches!(str_of(v.get("phase")), "planned" | "copying" | "verified")
        && str_of(v.get("released")).is_empty()
}

/// The item of this computer's bootc storage that the install may copy
/// instead of a download (#267): `bootc_shared.source_check.reuse_source()`.
/// `output` is the plain probe's stdout, `update_ref` the recipe's
/// targetImgref. Never on live media.
pub fn reuse_source(output: Option<&str>, update_ref: &str) -> Option<Value> {
    let root = parse_object(output)?;
    if obj(root.get("live")).get("is_live") != Some(&Value::Bool(false)) {
        return None;
    }
    let store = root.get("bootc_store")?.as_object()?;
    if store.get("version").and_then(Value::as_i64) != Some(1) || !is_true(store.get("available")) {
        return None;
    }
    let items = store.get("items")?.as_array()?;
    let want = plain_ref(update_ref);
    if want.is_empty() {
        return None;
    }
    let roles = |item: &Value| -> Vec<String> {
        item.get("roles")
            .and_then(Value::as_array)
            .map(|r| r.iter().filter_map(Value::as_str).map(String::from).collect())
            .unwrap_or_default()
    };
    if items.iter().any(|i| str_of(i.get("ref")) == want && roles(i).iter().any(|r| r == "staged")) {
        return None;
    }
    items.iter().find_map(|item| {
        let digest = str_of(item.get("digest"));
        let platform = str_of(item.get("platform"));
        let digest_ok = digest.len() == 71
            && digest.starts_with("sha256:")
            && digest[7..].bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b));
        let platform_ok = platform.len() <= 32
            && platform.bytes().next().is_some_and(|b| b.is_ascii_alphanumeric())
            && platform.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'_' || b == b'-');
        (str_of(item.get("ref")) == want
            && roles(item).iter().any(|r| r == "booted")
            && str_of(item.get("owner")) == "bootc"
            && str_of(item.get("context")) == "live-host"
            && str_of(item.get("storage")) == "ostree"
            && str_of(item.get("availability")) == "deployed"
            && is_true(item.get("matches_machine"))
            && digest_ok
            && platform_ok)
            .then(|| json!({"ref": want, "digest": digest, "platform": platform}))
    })
}

/// Whether the probe offers the system that this computer runs for its own
/// reference (`bootc_shared.source_check.offers_reuse`): the network page,
/// which comes before the image is chosen, then lets a computer without a
/// network go on to that choice.
pub fn offers_reuse(output: Option<&str>) -> bool {
    let Some(root) = parse_object(output) else {
        return false;
    };
    let items = obj(root.get("bootc_store")).get("items").and_then(Value::as_array).cloned().unwrap_or_default();
    items.iter().any(|item| {
        item.get("roles")
            .and_then(Value::as_array)
            .is_some_and(|r| r.iter().any(|x| x == "booted"))
            && reuse_source(output, str_of(item.get("ref"))).is_some()
    })
}

/// `recipe` with `source` as its install source: an empty `image`, the
/// update reference kept as `targetImgref`, `sourceReuse` and the
/// `bootc_store_reuse` opt-in.
pub fn apply_reuse(recipe: &Value, source: &Value) -> Value {
    let mut out = recipe.clone();
    let Some(map) = out.as_object_mut() else {
        return out;
    };
    let mut target = str_of(recipe.get("targetImgref")).to_string();
    if target.is_empty() {
        target = str_of(recipe.get("image")).to_string();
    }
    map.insert("targetImgref".into(), Value::String(target));
    map.insert("image".into(), Value::String(String::new()));
    map.insert(
        "sourceReuse".into(),
        json!({"store": "bootc", "digest": source["digest"], "platform": source["platform"]}),
    );
    let mut experimental: Vec<Value> = recipe
        .get("experimental")
        .and_then(Value::as_array)
        .map(|a| a.iter().filter(|e| e.is_string()).cloned().collect())
        .unwrap_or_default();
    if !experimental.iter().any(|e| e == "bootc_store_reuse") {
        experimental.push(Value::String("bootc_store_reuse".into()));
    }
    map.insert("experimental".into(), Value::Array(experimental));
    out
}

/// The `validate --json --partial` fragment that checks a recipe with
/// `sourceReuse`: no passphrase, no account.
pub fn reuse_fragment(recipe: &Value) -> Value {
    let mut out = Map::new();
    for key in ["image", "targetImgref", "experimental", "sourceReuse", "composeFsBackend", "filesystem"] {
        if let Some(v) = recipe.get(key) {
            out.insert(key.into(), v.clone());
        }
    }
    Value::Object(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn shared() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../shared")
    }

    fn cases(path: PathBuf) -> Vec<Value> {
        let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
        let doc: Value = serde_json::from_str(&text).unwrap();
        let cases = doc["cases"].as_array().cloned().unwrap_or_default();
        assert!(!cases.is_empty(), "{} has no cases", path.display());
        cases
    }

    /// The probe output a case describes: None when the probe failed,
    /// {protocol_version: 1} for an older fisherman, else the fixture
    /// under `key`.
    fn probe_input(case: &Value, dir: &str, key: &str) -> Option<String> {
        if case["probe_failed"] == Value::Bool(true) {
            return None;
        }
        let Some(fixture) = case["fixture"].as_str() else {
            return Some(r#"{"protocol_version": 1}"#.to_string());
        };
        let path = shared().join("probe/fixtures").join(dir).join(fixture);
        let text = std::fs::read_to_string(&path).unwrap();
        Some(format!(r#"{{"protocol_version": 1, "{key}": {text}}}"#))
    }

    fn request(v: &Value) -> Request {
        Request {
            source: str_of(v.get("source")).to_string(),
            live_root: is_true(v.get("live_root")),
            target: str_of(v.get("target")).to_string(),
            features: v["features"]
                .as_array()
                .map(|a| a.iter().filter_map(|f| f.as_str().map(String::from)).collect())
                .unwrap_or_default(),
        }
    }

    #[test]
    fn the_shared_capability_cases() {
        for case in cases(shared().join("probe/capabilities-cases.json")) {
            let req = request(&case["request"]);
            let view = check(probe_input(&case, "capabilities", "capabilities").as_deref(), &req);
            assert_eq!(view, case["expected"], "{}", case["name"]);
            assert_eq!(blocks_install(&view), case["blocks_install"] == Value::Bool(true), "{}", case["name"]);
            assert_eq!(json!(req.probe_args()), case["probe_args"], "{}", case["name"]);
        }
    }

    /// shared/probe/source-reuse-cases.json (#267).
    #[test]
    fn the_shared_source_reuse_cases() {
        let all = cases(shared().join("probe/source-reuse-cases.json"));
        assert!(all.len() >= 20);
        for case in all {
            let name = case["name"].as_str().unwrap();
            let input = if case["probe_failed"] == Value::Bool(true) {
                None
            } else {
                let mut probe = json!({"protocol_version": 1});
                if let Some(fixture) = case["fixture"].as_str() {
                    let text = std::fs::read_to_string(shared().join("probe/fixtures/bootc-store").join(fixture)).unwrap();
                    probe["bootc_store"] = serde_json::from_str(&text).unwrap();
                }
                if !case["live"].is_null() {
                    probe["live"] = json!({"is_live": case["live"]});
                }
                Some(probe.to_string())
            };
            let source = reuse_source(input.as_deref(), case["update_ref"].as_str().unwrap());
            assert_eq!(source.clone().unwrap_or(Value::Null), case["expected"], "{name}");
            let Some(source) = source else { continue };
            let reference = case["update_ref"].as_str().unwrap();
            let base = json!({
                "disk": "/dev/vda", "filesystem": "xfs",
                "encryption": {"type": "none", "passphrase": ""},
                "image": reference, "targetImgref": reference,
                "composeFsBackend": false, "hostname": "workstation",
            });
            let recipe = apply_reuse(&base, &source);
            assert_eq!(recipe, case["recipe"], "{name}");
            assert_eq!(reuse_fragment(&recipe), case["fragment"], "{name}");
            assert_eq!(json!(Request::from_recipe(&recipe, false).probe_args()), case["probe_args"], "{name}");
        }
    }

    /// shared/progress/receipt-cases.json (#269): the receipt and the done
    /// page's keys, through the progress parser.
    #[test]
    fn the_shared_receipt_cases() {
        let all = cases(shared().join("progress/receipt-cases.json"));
        assert!(all.len() >= 15);
        for case in all {
            let name = case["name"].as_str().unwrap();
            let mut p = crate::progress::Progress::new("ExampleOS");
            for (i, (event, want)) in case["events"].as_array().unwrap().iter().zip(case["bar"].as_array().unwrap()).enumerate() {
                p.consume(&event.to_string());
                assert!((p.fraction - want.as_f64().unwrap() as f32).abs() < 1e-5, "{name} event {i}");
            }
            assert_eq!(p.receipt.clone().unwrap_or(Value::Null), case["receipt"], "{name}");
            let lines: Vec<Value> = receipt_lines(p.receipt.as_ref())
                .into_iter()
                .map(|(key, value)| json!({"key": key, "value": value}))
                .collect();
            assert_eq!(Value::Array(lines), case["done_lines"], "{name}");
        }
    }

    /// shared/progress/source-reuse-cases.json (#267): the copy before the
    /// first step, its lines and the cancel question, through the progress
    /// parser. The copy never moves the bar.
    #[test]
    fn the_shared_source_reuse_progress_cases() {
        let all = cases(shared().join("progress/source-reuse-cases.json"));
        assert!(all.len() >= 15);
        for case in all {
            let name = case["name"].as_str().unwrap();
            let mut p = crate::progress::Progress::new("ExampleOS");
            for (i, (event, want)) in case["events"].as_array().unwrap().iter().zip(case["bar"].as_array().unwrap()).enumerate() {
                p.consume(&event.to_string());
                assert!((p.fraction - want.as_f64().unwrap() as f32).abs() < 1e-5, "{name} event {i}");
            }
            assert_eq!(p.source_reuse.clone().unwrap_or(Value::Null), case["source_reuse"], "{name}");
            let lines: Vec<Value> = source_reuse_lines(p.source_reuse.as_ref())
                .into_iter()
                .map(|(key, value)| json!({"key": key, "value": value}))
                .collect();
            assert_eq!(Value::Array(lines), case["lines"], "{name}");
            assert_eq!(copy_cancel(p.source_reuse.as_ref(), p.step), case["copy_cancel"].as_bool().unwrap(), "{name}");
        }
    }

    #[test]
    fn the_shared_bootc_store_cases() {
        for case in cases(shared().join("probe/bootc-store-cases.json")) {
            let view = bootc_store(probe_input(&case, "bootc-store", "bootc_store").as_deref());
            assert_eq!(view, case["expected"], "{}", case["name"]);
        }
    }

    #[test]
    fn the_shared_verification_cases() {
        for case in cases(shared().join("completion/verification-cases.json")) {
            let path = shared().join("completion/fixtures").join(case["fixture"].as_str().unwrap());
            let text = std::fs::read_to_string(&path).unwrap();
            let view = verification(&text, str_of(case.get("expected_install_id")));
            assert_eq!(view, case["expected"], "{}", case["name"]);
        }
    }

    #[test]
    fn a_failed_probe_is_not_a_green_check() {
        let req = Request { source: "registry.example/os:1".into(), ..Default::default() };
        let rows = rows(Some(&check(None, &req)), None, false);
        let titles: Vec<&str> = rows.iter().map(|(t, _)| t.as_str()).collect();
        assert!(titles.contains(&crate::branding::text("source_check_unavailable").as_str()));
        assert!(!titles.contains(&crate::branding::text("source_check_ready").as_str()));
    }

    #[test]
    fn the_recipe_gives_the_request() {
        let r = Request::from_recipe(&json!({"image": "", "targetImgref": "t/x:1"}), true);
        assert!(r.live_root);
        assert_eq!(r.probe_args(), vec!["--live-root", "--target-imgref", "t/x:1"]);
        let r = Request::from_recipe(&json!({"image": "a/b:1", "unifiedStorage": true}), false);
        assert_eq!(r.features, vec!["unified_storage"]);
        assert_eq!(r.probe_args(), vec!["--source", "a/b:1"]);
    }
}
