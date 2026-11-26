//! A screen reader and a display scale, on the first page (tunaOS#5012).
//!
//! The live session gets them at once, through the host's own tools: the
//! at-spi status that cosmic-session watches to start orca (the same one that
//! Super+Alt+S toggles), and cosmic-randr for each enabled output. The
//! installed system gets them through ConfigureTarget `accessibility`, which
//! fishermand turns into a first-login step for each account.

/// The scales on offer, in percent. 100 is the first: a person who set
/// another can go back.
pub const SCALES: [u32; 5] = [100, 125, 150, 175, 200];

/// `busctl` on the host: the at-spi status of the session.
pub fn screen_reader_command(on: bool) -> Vec<String> {
    crate::offline::host_command(&[
        "busctl",
        "--user",
        "set-property",
        "org.a11y.Bus",
        "/org/a11y/bus",
        "org.a11y.Status",
        "ScreenReaderEnabled",
        "b",
        if on { "true" } else { "false" },
    ])
}

/// One enabled output at its current mode, from `cosmic-randr list --kdl`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Output {
    pub name: String,
    pub width: u32,
    pub height: u32,
    /// mHz.
    pub refresh: u32,
}

/// The enabled outputs of `cosmic-randr list --kdl` (cosmic-randr
/// cli/src/main.rs `list_kdl`), each at its current mode.
pub fn parse_outputs(kdl: &str) -> Vec<Output> {
    let mut out = Vec::new();
    let mut current: Option<(String, bool)> = None;
    for line in kdl.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("output \"") {
            let name = rest.split('"').next().unwrap_or("").to_string();
            current = Some((name, rest.contains("enabled=#true")));
        } else if let (Some(rest), Some((name, true))) = (line.strip_prefix("mode "), &current) {
            if !rest.contains("current=#true") {
                continue;
            }
            let nums: Vec<u32> = rest.split_whitespace().take(3).filter_map(|n| n.parse().ok()).collect();
            if let [width, height, refresh] = nums[..] {
                out.push(Output { name: name.clone(), width, height, refresh });
            }
        }
    }
    out
}

/// `cosmic-randr mode` on the host for one output at `percent`.
pub fn scale_command(output: &Output, percent: u32) -> Vec<String> {
    let scale = format!("{}.{:02}", percent / 100, percent % 100);
    let refresh = format!("{}.{:03}", output.refresh / 1000, output.refresh % 1000);
    let (width, height) = (output.width.to_string(), output.height.to_string());
    crate::offline::host_command(&[
        "cosmic-randr",
        "mode",
        "--scale",
        &scale,
        "--refresh",
        &refresh,
        &output.name,
        &width,
        &height,
    ])
}

/// Scale every enabled output of the live session. Best effort: a session
/// with no cosmic-randr stays as it is.
pub fn apply_scale(percent: u32) {
    let list = crate::offline::host_command(&["cosmic-randr", "list", "--kdl"]);
    let Some((program, args)) = list.split_first() else { return };
    let Ok(out) = std::process::Command::new(program).args(args).output() else { return };
    for output in parse_outputs(&String::from_utf8_lossy(&out.stdout)) {
        crate::preflight::apply_best_effort(&scale_command(&output, percent));
    }
}

/// The ConfigureTarget `accessibility` object: only what the person changed.
pub fn configure_value(screen_reader: Option<bool>, scale: Option<u32>) -> Option<serde_json::Value> {
    if screen_reader.is_none() && scale.is_none() {
        return None;
    }
    let mut value = serde_json::Map::new();
    if let Some(on) = screen_reader {
        value.insert("screenReader".into(), on.into());
    }
    if let Some(percent) = scale {
        value.insert("scalePercent".into(), percent.into());
    }
    Some(value.into())
}

#[cfg(test)]
mod tests {
    use super::*;

    // The format of cosmic-randr list --kdl.
    const KDL: &str = "output \"eDP-1\" enabled=#true {
  description make=\"BOE\" model=\"0x0BCA\"
  scale 1.00
  modes {
    mode 2560 1600 60002 current=#true preferred=#true
    mode 1920 1200 59950
  }
}
output \"HDMI-A-1\" enabled=#false {
  modes {
    mode 1920 1080 60000 current=#true
  }
}
";

    #[test]
    fn only_enabled_outputs_at_their_current_mode() {
        assert_eq!(
            parse_outputs(KDL),
            vec![Output { name: "eDP-1".into(), width: 2560, height: 1600, refresh: 60002 }]
        );
    }

    #[test]
    fn the_scale_command_names_the_mode_it_keeps() {
        let out = &parse_outputs(KDL)[0];
        let argv = scale_command(out, 150);
        let tail: Vec<&str> = argv.iter().rev().take(9).rev().map(String::as_str).collect();
        assert_eq!(tail, ["cosmic-randr", "mode", "--scale", "1.50", "--refresh", "60.002", "eDP-1", "2560", "1600"]);
    }

    #[test]
    fn only_what_was_changed_is_sent() {
        assert_eq!(configure_value(None, None), None);
        assert_eq!(configure_value(Some(true), None), Some(serde_json::json!({"screenReader": true})));
        assert_eq!(
            configure_value(Some(false), Some(125)),
            Some(serde_json::json!({"screenReader": false, "scalePercent": 125}))
        );
    }

    #[test]
    fn the_screen_reader_is_the_status_that_super_alt_s_toggles() {
        let argv = screen_reader_command(true);
        assert!(argv.ends_with(&[
            "org.a11y.Status".to_string(), "ScreenReaderEnabled".into(), "b".into(), "true".into()
        ]));
    }
}
