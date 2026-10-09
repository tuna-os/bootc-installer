// fisherman's progress protocol, for the install page.
//
// fisherman writes newline-delimited JSON to stdout and nothing else
// (shared/progress/README.md). It has never written a "[n/9] " step prefix;
// two sibling frontends shipped parsers for one and their bars sat at zero
// for every real install, which is what `rejects_the_invented_step_prefix`
// below pins.
//
// fisherman sends the bar itself as `overall_pct` on step, substep and
// complete events, and a stable `step_id` on step events
// (tuna-os/fisherman#270). Both are authoritative: the bar shows
// `overall_pct`, and the step label is the branding copy key
// `step_<step_id>` (see `Progress::step_label`).
//
// Without `overall_pct` (an older fisherman) the bar falls back to the
// derivation below. Its semantics match the canonical Python parser in
// shared/progress. It is driven by `cumulative_pct`, never by
// step/total_steps: fisherman computes
// total_steps from the recipe, and "Installing OS" alone carries 87% of a
// cold install while five other steps carry 0%, so a bar advanced one-nth per
// step sits near empty for the whole visible install and then jumps.

use serde_json::Value;

/// Parser state, carried across lines so a substep can interpolate inside its
/// step.
#[derive(Debug, Clone)]
pub struct Progress {
    pub step: u64,
    pub total_steps: u64,
    pub fraction: f32,
    /// The step-name fallback label: the friendly table, else fisherman's
    /// raw step_name. Shown when the step has no copy line; see step_label.
    pub step_name: String,
    /// fisherman's stable id for the current step, "" when the event had
    /// none (an older fisherman, or a step fisherman has no id for).
    pub step_id: String,
    /// The key fisherman emits once, after TPM enrolment (#129). It used to
    /// be formatted into a log line and dropped: the event was rendered but
    /// never stored, so nothing could show it after the install finished.
    pub recovery_key: String,
    cumulative_pct: f32,
    weight_pct: f32,
    /// How far through the current step the bar is, 0-1. Never decreases
    /// inside a step.
    step_frac: f32,
    /// `step_frac` when the first post-pull phase message arrived.
    post_pull_base: Option<f32>,
    product: String,
}

/// Share of a step's weight the layer pull covers; the rest is for the
/// export, deploy and bootloader phases after it, which have no counter.
const PULL_SHARE: f32 = 0.6;

/// Bar positions for the silent phases after the pull, as a share of what is
/// left of the step. Matched as message prefixes. Without these an offline
/// install sat at 1% through ten minutes of export and deploy (#115).
/// Same table and semantics as shared/progress/progress_parser.py; the
/// numbers are pinned by shared/progress/fraction-cases.json.
const PHASE_MILESTONES: &[(&str, f32)] = &[
    ("Exporting image to OCI layout", 0.05),
    ("OCI export complete", 0.30),
    ("Using ", 0.32),
    ("Initializing ostree layout", 0.35),
    ("Writing ", 0.35),
    ("Deploying image", 0.35),
    ("OS deployed, installing bootloader", 0.90),
    ("Detected bootloader", 0.92),
    ("Installing bootloader", 0.92),
    ("Configuring EFI boot entry", 0.95),
    ("Configuring GRUB", 0.95),
    ("Configuring SELinux", 0.95),
    ("Generating initramfs", 0.95),
    ("bootc installation complete", 1.0),
];

/// fisherman's own bar position as a fraction, if the event carries it.
/// Clamped to 0-1 and never below `before`, the bar before this event.
fn overall_fraction(event: &Value, before: f32) -> Option<f32> {
    let pct = event.get("overall_pct").and_then(Value::as_f64)? as f32;
    Some(before.max((pct / 100.0).clamp(0.0, 1.0)))
}

fn milestone(message: &str) -> Option<f32> {
    PHASE_MILESTONES
        .iter()
        .find(|(prefix, _)| message.starts_with(prefix))
        .map(|(_, share)| *share)
}

impl Progress {
    pub fn new(product: impl Into<String>) -> Self {
        Self {
            step: 0,
            total_steps: 0,
            fraction: 0.0,
            step_name: String::new(),
            step_id: String::new(),
            recovery_key: String::new(),
            cumulative_pct: 0.0,
            weight_pct: 0.0,
            step_frac: 0.0,
            post_pull_base: None,
            product: product.into(),
        }
    }

    pub fn reset(&mut self) {
        let product = std::mem::take(&mut self.product);
        *self = Self::new(product);
    }

    /// What to call the current step: the branding copy line
    /// `step_<step_id>` (shared/branding/README.md, "Install steps"), so a
    /// product can rebrand it. A step without an id, or an id the copy has
    /// no line for, falls back to `step_name`.
    pub fn step_label(&self, branding: &crate::branding::Branding) -> String {
        if !self.step_id.is_empty() {
            let label = branding.text(&(String::from("step_") + &self.step_id));
            if !label.is_empty() {
                return label;
            }
        }
        self.step_name.clone()
    }

    /// True once fisherman has said anything, i.e. the bar means something.
    pub fn started(&self) -> bool {
        self.step > 0
    }

    /// Parses one line, updates the bar, and returns the text to show in the
    /// log pane.
    ///
    /// The protocol is machine-readable and the pane is not, so events are
    /// rendered for a person; a line that is not an event is returned as it
    /// stands, because fisherman's stderr is interleaved into the same stream
    /// and is already readable. `None` means show nothing.
    pub fn consume(&mut self, line: &str) -> Option<String> {
        let trimmed = line.trim_end();
        if !trimmed.starts_with('{') {
            return (!trimmed.is_empty()).then(|| trimmed.to_string());
        }
        let Ok(event) = serde_json::from_str::<Value>(trimmed) else {
            return Some(trimmed.to_string());
        };

        let str_field = |k: &str| event.get(k).and_then(Value::as_str).unwrap_or("");
        let num_field = |k: &str| event.get(k).and_then(Value::as_f64).unwrap_or(0.0);
        let before = self.fraction;

        match str_field("type") {
            "step" => {
                let step = num_field("step") as u64;
                // A repeated or earlier step is ignored, as in the canonical
                // parser: it must not reset the bar.
                if self.step > 0 && step <= self.step {
                    return Some(format!(
                        "[{}/{}] {}",
                        step,
                        num_field("total_steps") as u64,
                        str_field("step_name")
                    ));
                }
                self.step = step;
                self.step_frac = 0.0;
                self.post_pull_base = None;
                self.total_steps = num_field("total_steps") as u64;
                self.cumulative_pct = num_field("cumulative_pct") as f32;
                self.weight_pct = num_field("weight_pct") as f32;
                // The derivation is the fallback; overall_pct wins.
                self.fraction =
                    overall_fraction(&event, before).unwrap_or(self.cumulative_pct / 100.0);
                let name = str_field("step_name");
                self.step_name = friendly(name, &self.product);
                self.step_id = str_field("step_id").to_string();
                Some(format!("[{}/{}] {}", self.step, self.total_steps, name))
            }
            kind @ ("substep" | "info") => {
                let message = str_field("message");
                if kind == "substep" && self.weight_pct > 0.0 {
                    // The layer pull covers the first PULL_SHARE of the step;
                    // the named phases after it cover the rest.
                    let step_frac = if let Some((done, total)) = layer_progress(message) {
                        Some((done / total).min(1.0) * PULL_SHARE)
                    } else {
                        milestone(message).map(|share| {
                            let base = *self.post_pull_base.get_or_insert(self.step_frac);
                            base + share * (1.0 - base)
                        })
                    };
                    if let Some(step_frac) = step_frac {
                        // Never move backwards: a retried pull restarts its
                        // layer count.
                        self.step_frac = self.step_frac.max(step_frac);
                        self.fraction = ((self.cumulative_pct + self.step_frac * self.weight_pct)
                            / 100.0)
                            .min(1.0);
                    }
                }
                if kind == "substep" {
                    if let Some(fraction) = overall_fraction(&event, before) {
                        self.fraction = fraction;
                    }
                }
                (!message.is_empty()).then(|| format!("  {message}"))
            }
            "complete" => {
                // cumulative_pct only ever reaches 99; `complete` fills it.
                self.fraction = 1.0;
                let message = str_field("message");
                Some(if message.is_empty() {
                    "Installation complete".to_string()
                } else {
                    message.to_string()
                })
            }
            "error" => Some(format!("ERROR: {}", str_field("message"))),
            // Kept in the log as well as on the done page: the log is what
            // gets pasted into a bug report, and a key that only ever
            // existed on a screen the user already dismissed is no better
            // than one that was never shown.
            "recovery_key" => {
                self.recovery_key = str_field("key").to_string();
                Some(format!("Recovery key: {}", str_field("key")))
            }
            _ => None,
        }
    }
}

/// Whether the done page must hold its Restart button (#129).
///
/// A recovery key on screen that nobody has acknowledged is the one reason:
/// leaving that page is what ends the chance to read it. A failed install
/// enrolled nothing, and a non-TPM install was never given a key, so neither
/// is held -- a user must not be asked to tick a box about a key they do not
/// have.
///
/// Free function because TunaInstaller carries a cosmic Core, which cannot
/// be built in a unit test; the render itself is covered by the capture
/// harness, which asserts on the real frame.
pub fn holds_restart(install_ok: bool, recovery_key: &str, acknowledged: bool) -> bool {
    install_ok && !recovery_key.is_empty() && !acknowledged
}

/// `Pulling image: layer 23/71` -> (23.0, 71.0).
fn layer_progress(message: &str) -> Option<(f32, f32)> {
    let rest = message.strip_prefix("Pulling image: layer ")?;
    let (done, total) = rest.split_once('/')?;
    let done: f32 = done.trim().parse().ok()?;
    let total: f32 = total.trim().parse().ok()?;
    (total > 0.0).then_some((done, total))
}

/// Human labels for fisherman's step names, matching the other frontends
/// (shared/progress/progress_parser.py): the fallback for a step event
/// without a step_id, from a fisherman older than overall_pct/step_id. The
/// labels match the step_<id> copy defaults. An unknown step falls back to its
/// raw name, so a step added to fisherman later shows what it really is
/// rather than showing nothing.
fn friendly(name: &str, product: &str) -> String {
    match name {
        "Preparing disk" => "Checking your drive…".into(),
        "Partitioning disk" => "Setting up your drive…".into(),
        "Formatting EFI partition" => "Preparing the boot system…".into(),
        "Setting up disk encryption" => "Securing your drive…".into(),
        "Formatting root filesystem" => "Formatting your drive…".into(),
        "Mounting filesystem" => "Almost ready…".into(),
        "Formatting data disk (/var)" => "Preparing data storage…".into(),
        // The one label that names the product. Nothing here may name a
        // distro (CLAUDE.md); it comes from the branding resolver.
        "Installing OS" => format!("Installing {product}…"),
        "Enrolling TPM2 auto-unlock" => "Setting up auto-unlock…".into(),
        "Copying system Flatpaks" => "Installing your apps…".into(),
        "Configuring installed system" => "Configuring your system…".into(),
        "Finalizing installation" => "Finishing up…".into(),
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The numbers every frontend's bar must reproduce, generated from the
    /// canonical parser (shared/progress/generate-fraction-cases.py). Read
    /// at test time, not embedded: the flatpak builds from this tree alone.
    #[test]
    fn reproduces_the_shared_fraction_cases() {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../shared/progress/fraction-cases.json"
        );
        let text = std::fs::read_to_string(path).expect("shared/progress/fraction-cases.json");
        let doc: Value = serde_json::from_str(&text).unwrap();
        let cases = doc["cases"].as_array().unwrap();
        assert!(cases.len() >= 5);
        for case in cases {
            let name = case["name"].as_str().unwrap();
            let mut p = Progress::new("ExampleOS");
            let bars = case["bar"].as_array().unwrap();
            for (i, (event, want)) in case["events"]
                .as_array()
                .unwrap()
                .iter()
                .zip(bars)
                .enumerate()
            {
                p.consume(&event.to_string());
                let want = want.as_f64().unwrap() as f32;
                assert!(
                    (p.fraction - want).abs() < 1e-5,
                    "{name} event {i}: bar {} want {want}",
                    p.fraction
                );
            }
        }
    }

    fn step_event(step: u64, total: u64, name: &str, cumulative: i64, weight: i64) -> String {
        format!(
            r#"{{"type":"step","step":{step},"total_steps":{total},"step_name":"{name}","cumulative_pct":{cumulative},"weight_pct":{weight}}}"#
        )
    }

    /// shared/progress/overall-pct-cases.json: fisherman's overall_pct is
    /// the bar; an event without it falls back to the derivation.
    #[test]
    fn reproduces_the_shared_overall_pct_cases() {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../shared/progress/overall-pct-cases.json"
        );
        let text = std::fs::read_to_string(path).expect("shared/progress/overall-pct-cases.json");
        let doc: Value = serde_json::from_str(&text).unwrap();
        let cases = doc["cases"].as_array().unwrap();
        assert!(cases.len() >= 3);
        for case in cases {
            let name = case["name"].as_str().unwrap();
            let mut p = Progress::new("ExampleOS");
            for (i, (event, want)) in case["events"]
                .as_array()
                .unwrap()
                .iter()
                .zip(case["bar"].as_array().unwrap())
                .enumerate()
            {
                p.consume(&event.to_string());
                let want = want.as_f64().unwrap() as f32;
                assert!(
                    (p.fraction - want).abs() < 1e-5,
                    "{name} event {i}: bar {} want {want}",
                    p.fraction
                );
            }
        }
    }

    #[test]
    fn overall_pct_drives_the_bar() {
        let mut p = Progress::new("ExampleOS");
        p.consume(
            r#"{"type":"step","step":6,"total_steps":8,"step_name":"Copying system Flatpaks","step_id":"flatpaks","cumulative_pct":88,"weight_pct":11,"overall_pct":88}"#,
        );
        // The derivation would hold the bar through the Flatpak copy.
        p.consume(r#"{"type":"substep","message":"Copying Flatpak data: 50%","overall_pct":93.5}"#);
        assert!((p.fraction - 0.935).abs() < 1e-6, "{}", p.fraction);
        // Never backwards.
        p.consume(r#"{"type":"substep","message":"x","overall_pct":90}"#);
        assert!((p.fraction - 0.935).abs() < 1e-6, "{}", p.fraction);
    }

    #[test]
    fn without_overall_pct_the_bar_is_derived() {
        let mut p = Progress::new("ExampleOS");
        p.consume(&step_event(5, 8, "Installing OS", 1, 87));
        p.consume(r#"{"type":"substep","message":"Pulling image: layer 2/4"}"#);
        let want = (1.0 + 0.5 * 0.6 * 87.0) / 100.0;
        assert!((p.fraction - want).abs() < 1e-6, "{}", p.fraction);
    }

    fn branded(copy: serde_json::Value) -> crate::branding::Branding {
        let file = serde_json::json!({"name": "Marlin", "copy": copy});
        crate::branding::from_sources(file.as_object(), None, "")
    }

    #[test]
    fn step_id_is_labelled_from_the_copy() {
        let b = branded(serde_json::json!({"step_flatpaks": "Adding apps to {name}"}));
        let mut p = Progress::new("Marlin");
        p.consume(
            r#"{"type":"step","step":6,"total_steps":8,"step_name":"Copying system Flatpaks","step_id":"flatpaks","cumulative_pct":88,"weight_pct":11,"overall_pct":88}"#,
        );
        assert_eq!(p.step_label(&b), "Adding apps to Marlin");
        // The neutral default for an id the product left alone.
        p.consume(
            r#"{"type":"step","step":7,"total_steps":8,"step_name":"Installing OS","step_id":"install_os","cumulative_pct":88,"weight_pct":0,"overall_pct":88}"#,
        );
        assert_eq!(p.step_label(&b), "Installing Marlin…");
    }

    #[test]
    fn an_unknown_step_id_falls_back_to_the_step_name() {
        let b = branded(serde_json::json!({}));
        let mut p = Progress::new("Marlin");
        p.consume(
            r#"{"type":"step","step":2,"total_steps":8,"step_name":"Polishing the hull","step_id":"polish_hull","cumulative_pct":10,"weight_pct":5,"overall_pct":10}"#,
        );
        assert_eq!(p.step_label(&b), "Polishing the hull");
        // No step_id at all: the step-name table.
        p.consume(&step_event(3, 8, "Copying system Flatpaks", 88, 11));
        assert_eq!(p.step_label(&b), "Installing your apps…");
    }

    #[test]
    fn step_event_moves_the_bar() {
        let mut p = Progress::new("ExampleOS");
        assert_eq!(p.fraction, 0.0);
        p.consume(&step_event(5, 8, "Installing OS", 1, 87));
        assert_eq!(p.step, 5);
        assert_eq!(p.total_steps, 8);
        assert!((p.fraction - 0.01).abs() < 1e-6);
    }

    #[test]
    fn uses_cumulative_pct_not_step_over_total() {
        // step/total would put step 5 of 8 at 62%. The real position is 1%:
        // "Installing OS" has not started yet and carries 87% of the time.
        let mut p = Progress::new("ExampleOS");
        p.consume(&step_event(5, 8, "Installing OS", 1, 87));
        assert!(p.fraction < 0.5);
    }

    #[test]
    fn substep_interpolates_inside_the_long_step() {
        let mut p = Progress::new("ExampleOS");
        p.consume(&step_event(5, 8, "Installing OS", 1, 87));
        let at_step_start = p.fraction;
        p.consume(r#"{"type":"substep","message":"Pulling image: layer 47/71"}"#);
        assert!(p.fraction > at_step_start);
        assert!(p.fraction < 1.0);
    }

    #[test]
    fn complete_fills_the_bar() {
        let mut p = Progress::new("ExampleOS");
        p.consume(&step_event(8, 8, "Finalizing installation", 99, 1));
        assert!((p.fraction - 0.99).abs() < 1e-6);
        p.consume(r#"{"type":"complete","message":"Installation complete"}"#);
        assert_eq!(p.fraction, 1.0);
    }

    #[test]
    fn rejects_the_invented_step_prefix() {
        // The exact bug this parse replaces. "[9/9] Finalizing" is not
        // something fisherman writes, so it must move nothing — a parser that
        // accepts it is reading its own fixtures.
        let mut p = Progress::new("ExampleOS");
        p.consume("[1/9] Partitioning /dev/nvme0n1");
        p.consume("[9/9] Finalizing");
        assert_eq!(p.fraction, 0.0);
        assert_eq!(p.step, 0);
    }

    #[test]
    fn non_protocol_lines_are_shown_as_they_stand() {
        let mut p = Progress::new("ExampleOS");
        assert_eq!(
            p.consume("fisherman: warning: something").as_deref(),
            Some("fisherman: warning: something")
        );
        assert_eq!(p.fraction, 0.0);
    }

    #[test]
    fn unknown_step_name_falls_back_to_the_raw_name() {
        let mut p = Progress::new("ExampleOS");
        p.consume(&step_event(2, 8, "Polishing the hull", 10, 5));
        assert_eq!(p.step_name, "Polishing the hull");
    }

    #[test]
    fn product_label_is_branded_not_hardcoded() {
        let mut p = Progress::new("ExampleOS");
        p.consume(&step_event(5, 8, "Installing OS", 1, 87));
        assert_eq!(p.step_name, "Installing ExampleOS…");
    }

    #[test]
    fn events_render_for_a_person_not_as_json() {
        let mut p = Progress::new("ExampleOS");
        let shown = p.consume(&step_event(5, 8, "Installing OS", 1, 87)).unwrap();
        assert_eq!(shown, "[5/8] Installing OS");
        assert!(!shown.contains("cumulative_pct"));
    }

    fn recovery_event(key: &str) -> String {
        serde_json::json!({
            "type": "recovery_key",
            "key": key,
            "timestamp": "2026-01-01T00:00:00Z",
            "elapsed_ms": 1000,
        })
        .to_string()
    }

    /// The event was rendered and dropped: this branch formatted a log line
    /// and kept nothing, so after the install nothing could show the key.
    #[test]
    fn a_recovery_key_event_is_kept_not_just_printed() {
        let mut p = Progress::new("TunaOS");
        assert!(p.recovery_key.is_empty());

        let shown = p.consume(&recovery_event("abcd-efgh")).unwrap();

        assert_eq!(p.recovery_key, "abcd-efgh");
        // Still in the log, which is what gets pasted into a bug report.
        assert!(shown.contains("abcd-efgh"), "{shown}");
    }

    #[test]
    fn other_events_leave_the_key_alone() {
        let mut p = Progress::new("TunaOS");
        p.consume(&recovery_event("abcd-efgh"));
        p.consume(&step_event(5, 8, "Installing OS", 1, 87));
        assert_eq!(p.recovery_key, "abcd-efgh");
    }

    #[test]
    fn reset_forgets_the_key() {
        let mut p = Progress::new("TunaOS");
        p.consume(&recovery_event("abcd-efgh"));
        p.reset();
        assert!(p.recovery_key.is_empty());
    }

    #[test]
    fn restart_is_held_only_for_an_unacknowledged_key() {
        assert!(holds_restart(true, "abcd-efgh", false), "key, not ticked");
        assert!(!holds_restart(true, "abcd-efgh", true), "ticked");
        assert!(!holds_restart(true, "", false), "no key, so no gate");
        assert!(!holds_restart(false, "abcd-efgh", false), "install failed");
    }

    /// The old mitigation wrote "Recovery key: ..." into the pane. That text
    /// must not be parsed back out as an event.
    #[test]
    fn a_plain_log_line_is_not_an_event() {
        let mut p = Progress::new("TunaOS");
        p.consume("Recovery key: not-a-real-event");
        assert!(p.recovery_key.is_empty());
    }
}
