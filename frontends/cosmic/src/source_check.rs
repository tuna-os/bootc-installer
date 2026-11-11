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
        let source = str_of(recipe.get("image")).to_string();
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
pub fn rows(check: Option<&Value>, store: Option<&Value>) -> Vec<(String, String)> {
    let text = crate::branding::text;
    let value_line = |key: &str, value: &str| crate::branding::get().text_with(key, &[("value", value)]);
    let mut out = Vec::new();
    let Some(view) = check else {
        out.push((text(&format!("{}{}", "source_check_", "checking")), String::new()));
        return out;
    };
    for (key, field) in [
        ("source_install_from", "install_from"),
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
        let rows = rows(Some(&check(None, &req)), None);
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
