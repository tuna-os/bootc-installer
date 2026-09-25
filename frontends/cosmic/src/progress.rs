// fisherman's progress protocol, for the install page.
//
// fisherman writes newline-delimited JSON to stdout and nothing else
// (shared/progress/README.md). It has never written a "[n/9] " step prefix;
// two sibling frontends shipped parsers for one and their bars sat at zero
// for every real install, which is what `rejects_the_invented_step_prefix`
// below pins.
//
// Semantics match the canonical Python parser in shared/progress. The bar is
// driven by `cumulative_pct`, never by step/total_steps: fisherman computes
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
    pub step_name: String,
    /// The key fisherman emits once, after TPM enrolment (#129). It used to
    /// be formatted into a log line and dropped: the event was rendered but
    /// never stored, so nothing could show it after the install finished.
    pub recovery_key: String,
    cumulative_pct: f32,
    weight_pct: f32,
    product: String,
}

impl Progress {
    pub fn new(product: impl Into<String>) -> Self {
        Self {
            step: 0,
            total_steps: 0,
            fraction: 0.0,
            step_name: String::new(),
            recovery_key: String::new(),
            cumulative_pct: 0.0,
            weight_pct: 0.0,
            product: product.into(),
        }
    }

    pub fn reset(&mut self) {
        let product = std::mem::take(&mut self.product);
        *self = Self::new(product);
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

        match str_field("type") {
            "step" => {
                self.step = num_field("step") as u64;
                self.total_steps = num_field("total_steps") as u64;
                self.cumulative_pct = num_field("cumulative_pct") as f32;
                self.weight_pct = num_field("weight_pct") as f32;
                self.fraction = self.cumulative_pct / 100.0;
                let name = str_field("step_name");
                self.step_name = friendly(name, &self.product);
                Some(format!("[{}/{}] {}", self.step, self.total_steps, name))
            }
            kind @ ("substep" | "info") => {
                let message = str_field("message");
                if kind == "substep" && self.weight_pct > 0.0 {
                    if let Some((done, total)) = layer_progress(message) {
                        // Without this the bar freezes for the 87% of the
                        // install the image pull occupies.
                        self.fraction = ((self.cumulative_pct
                            + (done / total) * self.weight_pct)
                            / 100.0)
                            .min(1.0);
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
/// (shared/progress/progress_parser.py). An unknown step falls back to its
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

    fn step_event(step: u64, total: u64, name: &str, cumulative: i64, weight: i64) -> String {
        format!(
            r#"{{"type":"step","step":{step},"total_steps":{total},"step_name":"{name}","cumulative_pct":{cumulative},"weight_pct":{weight}}}"#
        )
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
