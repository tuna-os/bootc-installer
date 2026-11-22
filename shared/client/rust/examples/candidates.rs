//! List the disks of the installer daemon, as gnome-setup does.
//!
//!     cargo run --example candidates -- [SOCKET]
use serde_json::{json, Value};
use varlink_thin::{sizes::normalize_size_text, Connection};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args().nth(1).unwrap_or_else(|| "/run/systemd/io.systemd.SysInstall".into());
    let mut c = Connection::connect(path)?;
    c.call_more(
        "io.systemd.SysInstall.ListCandidateDevices",
        json!({ "definitions": [], "subscribe": false }),
        |d: Value| {
            if let Some(node) = d["node"].as_str() {
                let name = format!("{} {}", d["vendor"].as_str().unwrap_or(""), d["model"].as_str().unwrap_or(""));
                let gb = d["sizeBytes"].as_f64().unwrap_or(0.0) / 1e9;
                println!("{node} {} {gb:.1} GB {}", normalize_size_text(&name), d["fit"].as_str().unwrap_or(""));
            }
            true
        },
    )?;
    Ok(())
}
