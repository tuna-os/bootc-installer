//! `fisherman plan --json -` for the confirm page (fisherman/docs/PLAN.md,
//! tuna-os/fisherman#371): a port of the canonical Python reader in
//! `shared/python/bootc_shared/plan.py`.
//!
//! A plan says what an install of a recipe would do, before anything is
//! written: the target disk and what it reports about itself, and every
//! device whose data the install destroys. `plan` needs no root, so it runs
//! as `validate` does: unprivileged, through the one resolver
//! (`offline::fisherman`), with the recipe on stdin and never on argv. The
//! recipe can hold the LUKS passphrase, and argv is world-readable in
//! /proc. The plan itself holds no secret.
//!
//! A plan is not a permission. The install checks the device again. To make
//! it refuse a disk that is not the one the user confirmed, the install
//! recipe gets the plan's identity as `diskIdentity` ([`bind`]). Without a
//! plan (an older fisherman, a timeout, an invalid recipe) the confirm page
//! and the recipe are as before.

use std::time::Duration;

use serde_json::{Map, Value};

/// The schema version this reader understands (PLAN.md, "Output").
pub const PROTOCOL_VERSION: i64 = 1;

/// One plan reads the target disk's facts (one lsblk call) and the TPM;
/// this bounds a hung flatpak-spawn or a slow udev.
pub const TIMEOUT: Duration = Duration::from_secs(20);

/// The value of a field that only the install can resolve.
pub const UNKNOWN: &str = "unknown";

/// The effects that have a copy key. Another effect is shown with
/// `confirm_plan_format`: the device's data is still lost.
const EFFECTS: [(&str, &str); 3] = [
    ("wipe_disk", "confirm_plan_wipe_disk"),
    ("format", "confirm_plan_format"),
    ("mkswap", "confirm_plan_mkswap"),
];

/// A copy line: the branding text of a key with its `{placeholders}`
/// filled (`branding::Branding::text_with`).
pub type Text = dyn Fn(&str, &[(&str, &str)]) -> String;

/// fisherman's answer: whether the recipe is valid, the codes of its
/// problems, and the plan (`None` when it is not valid).
#[derive(Debug, Clone, PartialEq)]
pub struct Answer {
    pub valid: bool,
    pub codes: Vec<String>,
    pub plan: Option<Value>,
}

/// Reads `plan --json` output. An error is "fisherman could not be asked,
/// or its answer was unreadable", never "the recipe is invalid". An older
/// fisherman has no `plan` command; what it prints instead has no
/// protocol_version and is refused here.
pub fn parse(text: &str) -> Result<Answer, String> {
    let result: Value = serde_json::from_str(text)
        .map_err(|e| format!("fisherman plan printed invalid JSON: {e}"))?;
    let Some(result) = result.as_object() else {
        return Err("fisherman plan did not print a JSON object".to_string());
    };
    let version = result.get("protocol_version").and_then(Value::as_i64);
    if version != Some(PROTOCOL_VERSION) {
        return Err(format!(
            "fisherman plan protocol_version {version:?} is not {PROTOCOL_VERSION}"
        ));
    }
    let (Some(valid), Some(errors)) = (
        result.get("valid").and_then(Value::as_bool),
        result.get("errors").and_then(Value::as_array),
    ) else {
        return Err("fisherman plan printed no valid flag or errors list".to_string());
    };
    let plan = result.get("plan").filter(|p| p.is_object()).cloned();
    if valid && plan.is_none() {
        return Err("fisherman plan is valid but printed no plan".to_string());
    }
    let codes = errors
        .iter()
        .filter_map(|e| e.get("code").and_then(Value::as_str).map(String::from))
        .collect();
    Ok(Answer {
        valid,
        codes,
        plan: plan.filter(|_| valid),
    })
}

/// Asks fisherman for the plan of `recipe`. Blocking: call it off the UI
/// thread.
pub fn request(recipe: &Value) -> Result<Answer, String> {
    // The one resolver (offline.rs): unprivileged, never pkexec or sudo.
    run_with(
        &crate::offline::fisherman(crate::offline::Use::Plan, false)?,
        recipe,
        TIMEOUT,
    )
}

/// `request` with the command and the timeout given (tests). Exit 0 is a
/// plan, 1 an invalid recipe; anything else, or no answer in time, is an
/// error. The error names no part of the recipe.
pub fn run_with(argv: &[String], recipe: &Value, timeout: Duration) -> Result<Answer, String> {
    let (code, stdout, stderr) = crate::validate::run_on_stdin(
        argv,
        recipe.to_string().as_bytes(),
        timeout,
        "fisherman plan",
    )?;
    match code {
        Some(0) | Some(1) => parse(&stdout),
        code => {
            let detail = stderr
                .lines()
                .map(str::trim)
                .find(|l| !l.is_empty())
                .unwrap_or("no message");
            Err(format!("fisherman plan failed (exit {code:?}): {detail}"))
        }
    }
}

/// `value` is something the plan knows: a string that is not "unknown"
/// and not empty.
fn known(value: Option<&Value>) -> Option<&str> {
    value
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty() && *s != UNKNOWN)
}

fn target(plan: Option<&Value>) -> Option<&Map<String, Value>> {
    plan.and_then(|p| p.get("target"))
        .and_then(Value::as_object)
}

/// `plan.target.identity`, or `None` for a manual layout or no plan.
fn identity(plan: Option<&Value>) -> Option<&Map<String, Value>> {
    target(plan)
        .and_then(|t| t.get("identity"))
        .and_then(Value::as_object)
}

fn size_bytes(ident: &Map<String, Value>) -> Option<u64> {
    ident
        .get("size_bytes")
        .and_then(Value::as_u64)
        .filter(|n| *n > 0)
}

/// The recipe's `diskIdentity` for `plan`: `serial`, `wwn` and `sizeBytes`
/// of `plan.target.identity`, each only when the plan knows it. Empty when
/// it knows none (PLAN.md, "Binding the install").
pub fn disk_identity(plan: Option<&Value>) -> Map<String, Value> {
    let mut out = Map::new();
    let Some(ident) = identity(plan) else {
        return out;
    };
    for key in ["serial", "wwn"] {
        if let Some(v) = known(ident.get(key)) {
            out.insert(key.to_string(), Value::from(v));
        }
    }
    if let Some(size) = size_bytes(ident) {
        out.insert("sizeBytes".to_string(), Value::from(size));
    }
    out
}

/// `recipe` with `diskIdentity` from `plan`, or `recipe` unchanged when the
/// plan cannot bind it: no plan, a manual layout, no known identity, or a
/// plan for another disk than the recipe's `disk`.
pub fn bind(recipe: &Value, plan: Option<&Value>) -> Value {
    let binding = disk_identity(plan);
    let disk = target(plan)
        .and_then(|t| t.get("disk"))
        .and_then(Value::as_str)
        .unwrap_or("");
    let mut bound = recipe.clone();
    if binding.is_empty()
        || disk.is_empty()
        || recipe.get("disk").and_then(Value::as_str) != Some(disk)
    {
        return bound;
    }
    if let Some(obj) = bound.as_object_mut() {
        obj.insert("diskIdentity".to_string(), Value::Object(binding));
    }
    bound
}

/// `(device, effect)` of `plan.destroys`, in fisherman's order. An effect
/// this reader does not know is kept: the device is still lost.
pub fn destroys(plan: Option<&Value>) -> Vec<(String, String)> {
    let entries = plan
        .and_then(|p| p.get("destroys"))
        .and_then(Value::as_array);
    entries
        .into_iter()
        .flatten()
        .filter_map(|e| {
            let device = e
                .get("device")
                .and_then(Value::as_str)
                .filter(|d| !d.is_empty())?;
            let effect = e.get("effect").and_then(Value::as_str).unwrap_or("");
            Some((device.to_string(), effect.to_string()))
        })
        .collect()
}

/// fisherman's size rule (binary units), as `bootc_shared.probe.format_size`:
/// for the plan's byte count, which has no `size_label`. A disk's size on
/// the disk page is always its `size_label`.
pub fn format_size(n: u64) -> String {
    const UNITS: [&str; 6] = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
    let mut value = n as f64;
    let mut i = 0;
    while value >= 1024.0 && i < UNITS.len() - 1 {
        value /= 1024.0;
        i += 1;
    }
    if i == 0 {
        return format!("{n} B");
    }
    let text = format!("{value:.1}");
    format!("{} {}", text.strip_suffix(".0").unwrap_or(&text), UNITS[i])
}

/// The target disk's rows `(title, detail)`, in the words of the copy keys
/// read through `text(key, values)`: the model, size and serial, each
/// "unknown" when the disk does not report it, and whether the install is
/// bound to it. None for a manual layout.
pub fn target_rows(plan: Option<&Value>, text: &Text) -> Vec<(String, String)> {
    let Some(ident) = identity(plan) else {
        return Vec::new();
    };
    if ident.is_empty() {
        return Vec::new();
    }
    let unknown = Some(text("confirm_plan_unknown", &[]))
        .filter(|s| !s.is_empty())
        .unwrap_or(UNKNOWN.into());
    let disk = target(plan)
        .and_then(|t| t.get("disk"))
        .and_then(Value::as_str)
        .filter(|d| !d.is_empty());
    let size = size_bytes(ident).map(format_size);
    let values = [
        ("disk", disk.unwrap_or(&unknown)),
        ("model", known(ident.get("model")).unwrap_or(&unknown)),
        ("size", size.as_deref().unwrap_or(&unknown)),
        ("serial", known(ident.get("serial")).unwrap_or(&unknown)),
    ];
    let binding = disk_identity(plan);
    let bound_key = if binding.contains_key("serial") || binding.contains_key("wwn") {
        "confirm_plan_bound"
    } else {
        "confirm_plan_unbound"
    };
    [
        (
            text("confirm_plan_target", &values),
            text("confirm_plan_target_detail", &values),
        ),
        (text(bound_key, &values), String::new()),
    ]
    .into_iter()
    .filter(|(title, _)| !title.is_empty())
    .collect()
}

/// One row `(title, "")` per device the install destroys: the copy key
/// `confirm_plan_<effect>` with `{disk}` filled, or `confirm_plan_format`
/// for an effect this build has no line for.
pub fn destroy_rows(plan: Option<&Value>, text: &Text) -> Vec<(String, String)> {
    destroys(plan)
        .into_iter()
        .filter_map(|(device, effect)| {
            let key = EFFECTS
                .iter()
                .find(|(e, _)| *e == effect)
                .map_or("confirm_plan_format", |(_, k)| k);
            Some((text(key, &[("disk", &device)]), String::new()))
                .filter(|(line, _)| !line.is_empty())
        })
        .collect()
}

/// Every row of a plan, target first.
pub fn rows(plan: Option<&Value>, text: &Text) -> Vec<(String, String)> {
    let mut out = target_rows(plan, text);
    out.extend(destroy_rows(plan, text));
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::os::unix::fs::PermissionsExt;
    use std::path::PathBuf;

    const SECRET: &str = "correct-horse-battery-staple";

    fn goldens() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../fisherman/fisherman/cmd/fisherman/testdata/plan")
    }

    /// A golden plan, with the fixture directory as /dev; None without the
    /// fisherman submodule.
    fn golden(name: &str) -> Option<String> {
        let text = std::fs::read_to_string(goldens().join(format!("{name}.golden"))).ok()?;
        Some(text.replace("@DIR@", "/dev"))
    }

    fn plan_of(name: &str) -> Option<Value> {
        parse(&golden(name)?).unwrap().plan
    }

    /// The neutral copy, not the host's branding: the expected lines are
    /// those of tests/unit/test_shared_plan.py.
    fn defaults() -> HashMap<String, String> {
        let raw: Value = serde_json::from_str(include_str!(concat!(
            env!("OUT_DIR"),
            "/copy-defaults.json"
        )))
        .unwrap();
        raw.as_object()
            .unwrap()
            .iter()
            .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
            .collect()
    }

    fn text(key: &str, values: &[(&str, &str)]) -> String {
        let mut line = defaults().get(key).cloned().unwrap_or_default();
        for (k, v) in values {
            line = line.replace(&format!("{{{k}}}"), v);
        }
        line
    }

    fn recipe(disk: &str) -> Value {
        serde_json::json!({
            "disk": disk,
            "image": "ghcr.io/example/os:stable",
            "encryption": {"type": "luks-passphrase", "passphrase": SECRET},
        })
    }

    fn row(title: &str) -> (String, String) {
        (title.to_string(), String::new())
    }

    #[test]
    fn the_command_is_unprivileged_and_reads_stdin() {
        use crate::offline::{fisherman, fisherman_argv, Use};
        let argv = fisherman(Use::Plan, false).unwrap();
        assert_eq!(argv[1..], ["plan", "--json", "-"]);
        for (flatpak, live) in [(false, false), (false, true), (true, false), (true, true)] {
            let argv = fisherman_argv(Use::Plan, flatpak, live, "/c/f");
            assert!(
                !argv
                    .iter()
                    .any(|a| a.contains("pkexec") || a.contains("sudo")),
                "{argv:?}"
            );
            assert_eq!(argv[argv.len() - 3..], ["plan", "--json", "-"]);
        }
        assert_eq!(
            fisherman_argv(Use::Plan, true, false, "/c/f")[..3],
            ["flatpak-spawn", "--host", "/c/f"]
        );
    }

    /// A fake fisherman in a fresh directory that saves its stdin and argv,
    /// prints `stdout` and exits with `code`.
    fn fake(tag: &str, stdout: &str, code: i32, sleep: u32) -> (PathBuf, Vec<String>) {
        let dir = std::env::temp_dir().join(format!("cosmic-plan-{tag}-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("answer"), stdout).unwrap();
        let script = dir.join("fisherman");
        std::fs::write(
            &script,
            format!(
                "#!/bin/sh\ncat > '{d}/stdin'\necho \"$@\" > '{d}/args'\nsleep {sleep}\ncat '{d}/answer'\necho 'a reason' >&2\nexit {code}\n",
                d = dir.display()
            ),
        )
        .unwrap();
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
        let mut argv = vec![script.display().to_string()];
        argv.extend(["plan", "--json", "-"].map(String::from));
        (dir, argv)
    }

    #[test]
    fn the_recipe_goes_on_stdin_never_on_argv() {
        let Some(answer) = golden("grub2-plain") else {
            return;
        };
        let (dir, argv) = fake("stdin", &answer, 0, 0);
        let out = run_with(&argv, &recipe("/dev/sda"), TIMEOUT).unwrap();
        assert!(out.valid && out.plan.is_some());
        let seen: Value =
            serde_json::from_str(&std::fs::read_to_string(dir.join("stdin")).unwrap()).unwrap();
        assert_eq!(seen["encryption"]["passphrase"], SECRET);
        let args = std::fs::read_to_string(dir.join("args")).unwrap();
        assert_eq!(args.trim(), "plan --json -");
        assert!(!argv.join(" ").contains(SECRET));
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn exit_one_is_an_invalid_recipe_not_an_error() {
        let Some(answer) = golden("identity-serial-changed") else {
            return;
        };
        let (dir, argv) = fake("invalid", &answer, 1, 0);
        let out = run_with(&argv, &recipe("/dev/sda"), TIMEOUT).unwrap();
        assert!(!out.valid && out.plan.is_none());
        assert_eq!(out.codes[0], "disk_identity_mismatch");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn an_unreadable_answer_is_an_error() {
        let cases: [(&str, i32); 5] = [
            // An older fisherman: no plan command, a usage line, exit 2.
            ("", 2),
            // An older fisherman that took "plan" for a recipe path.
            (
                r#"{"type": "error", "message": "open plan: no such file"}"#,
                1,
            ),
            ("", 1),
            (
                r#"{"protocol_version": 2, "valid": true, "errors": [], "plan": {}}"#,
                0,
            ),
            (
                r#"{"protocol_version": 1, "valid": true, "errors": [], "plan": null}"#,
                0,
            ),
        ];
        for (i, (stdout, code)) in cases.into_iter().enumerate() {
            let (dir, argv) = fake(&format!("bad{i}"), stdout, code, 0);
            let err = run_with(&argv, &recipe("/dev/sda"), TIMEOUT).unwrap_err();
            assert!(!err.contains(SECRET), "{err}");
            std::fs::remove_dir_all(&dir).ok();
        }
        assert!(parse("[]").is_err());
    }

    #[test]
    fn a_command_that_cannot_run_or_hangs_is_an_error_without_the_recipe() {
        let err = run_with(
            &["/nonexistent/fisherman".to_string()],
            &recipe("/dev/sda"),
            TIMEOUT,
        )
        .unwrap_err();
        assert!(!err.contains(SECRET), "{err}");
        let (dir, argv) = fake("hang", "{}", 0, 5);
        let start = std::time::Instant::now();
        let err = run_with(&argv, &recipe("/dev/sda"), Duration::from_millis(300)).unwrap_err();
        assert!(
            start.elapsed() < Duration::from_secs(4),
            "the timeout did not stop it"
        );
        assert!(!err.contains(SECRET), "{err}");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn every_golden_parses_and_holds_no_secret() {
        let Ok(entries) = std::fs::read_dir(goldens()) else {
            eprintln!("fisherman submodule absent; skipping");
            return;
        };
        let mut seen = 0;
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("golden") {
                continue;
            }
            let out = parse(&std::fs::read_to_string(&path).unwrap()).unwrap();
            assert_eq!(out.plan.is_none(), !out.valid, "{}", path.display());
            for (title, detail) in rows(out.plan.as_ref(), &text) {
                assert!(
                    !title.is_empty() && !title.contains('{') && !detail.contains('{'),
                    "{title} {detail}"
                );
            }
            for (_, effect) in destroys(out.plan.as_ref()) {
                assert!(
                    EFFECTS.iter().any(|(e, _)| *e == effect),
                    "{effect} has no copy key"
                );
            }
            seen += 1;
        }
        assert!(seen > 10);
    }

    #[test]
    fn the_binding_copies_what_the_disk_reports() {
        let Some(plan) = plan_of("grub2-plain") else {
            return;
        };
        let expected = serde_json::json!({
            "serial": "FIXTURE-SDA-SERIAL", "wwn": "0x5000c500a1b2c3d4", "sizeBytes": 500107862016u64});
        assert_eq!(Value::Object(disk_identity(Some(&plan))), expected);
        let original = recipe("/dev/sda");
        assert_eq!(bind(&original, Some(&plan))["diskIdentity"], expected);
        assert!(original.get("diskIdentity").is_none());
    }

    #[test]
    fn an_unknown_value_is_left_out_of_the_binding() {
        let Some(plan) = plan_of("loop-image") else {
            return;
        };
        let expected = serde_json::json!({"sizeBytes": 8589934592u64});
        assert_eq!(Value::Object(disk_identity(Some(&plan))), expected);
        assert_eq!(
            bind(&recipe("/dev/loop0"), Some(&plan))["diskIdentity"],
            expected
        );
    }

    #[test]
    fn no_binding_without_a_plan_for_this_disk() {
        let Some(plan) = plan_of("grub2-plain") else {
            return;
        };
        for case in [recipe("/dev/sdb"), recipe("")] {
            assert_eq!(bind(&case, Some(&plan)), case);
        }
        assert_eq!(bind(&recipe("/dev/sda"), None), recipe("/dev/sda"));
        let manual = plan_of("manual").unwrap();
        assert!(disk_identity(Some(&manual)).is_empty());
        assert!(bind(&recipe("/dev/sda"), Some(&manual))
            .get("diskIdentity")
            .is_none());
    }

    #[test]
    fn the_target_rows_mark_unknown_values() {
        let Some(plan) = plan_of("grub2-plain") else {
            return;
        };
        let got = target_rows(Some(&plan), &text);
        assert_eq!(
            got[0],
            (
                "Installs to Fixture Disk".to_string(),
                "/dev/sda, 465.8 GiB, serial number FIXTURE-SDA-SERIAL".to_string()
            )
        );
        assert_eq!(got[1].0, text("confirm_plan_bound", &[]));
        let lp = target_rows(plan_of("loop-image").as_ref(), &text);
        assert_eq!(
            lp[0],
            (
                "Installs to unknown".to_string(),
                "/dev/loop0, 8 GiB, serial number unknown".to_string()
            )
        );
        assert_eq!(lp[1].0, text("confirm_plan_unbound", &[]));
        assert!(target_rows(plan_of("manual").as_ref(), &text).is_empty());
    }

    #[test]
    fn each_destroyed_device_has_a_line() {
        let Some(plan) = plan_of("grub2-plain") else {
            return;
        };
        assert_eq!(
            destroy_rows(Some(&plan), &text),
            [row("Everything on /dev/sda is erased.")]
        );
        assert_eq!(
            destroy_rows(plan_of("manual").as_ref(), &text),
            [
                row("/dev/sda3 is formatted. Its data is erased."),
                row("/dev/sda4 becomes swap space. Its data is erased."),
                row("/dev/sda2 is formatted. Its data is erased."),
            ]
        );
        // An effect this build has no line for still says the data is lost.
        let other = serde_json::json!({"destroys": [{"device": "/dev/sdz", "effect": "trim"}]});
        assert_eq!(
            destroy_rows(Some(&other), &text),
            [row("/dev/sdz is formatted. Its data is erased.")]
        );
    }

    #[test]
    fn every_effect_has_a_copy_key() {
        for (_, key) in EFFECTS {
            assert!(!text(key, &[]).is_empty(), "{key}");
        }
    }

    #[test]
    fn sizes_follow_fishermans_rule() {
        assert_eq!(format_size(512), "512 B");
        assert_eq!(format_size(8589934592), "8 GiB");
        assert_eq!(format_size(500107862016), "465.8 GiB");
    }
}
