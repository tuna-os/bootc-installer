//! Copies the data the five frontends share from the monorepo's `shared/`
//! into OUT_DIR, where `include_str!` compiles it in. There is no copy of
//! these files in this tree.
//!
//! The default is `../../shared`, next to this crate in a checkout. A build
//! without the monorepo around it (the Flatpak, a copy for the wasm build)
//! sets TUNA_SHARED_DIR to where it put `shared/`.

use std::env;
use std::fs;
use std::path::PathBuf;

/// (path under shared/, file name in OUT_DIR)
const SHARED: &[(&str, &str)] = &[
    ("branding/copy-defaults.json", "copy-defaults.json"),
    ("recipe/encryption-choices.json", "encryption-choices.json"),
    ("account/groups.json", "account-groups.json"),
];

fn main() {
    println!("cargo:rerun-if-env-changed=TUNA_SHARED_DIR");
    let shared = match env::var_os("TUNA_SHARED_DIR") {
        Some(dir) => PathBuf::from(dir),
        None => {
            PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").expect("cargo sets CARGO_MANIFEST_DIR"))
                .join("..")
                .join("..")
                .join("shared")
        }
    };
    let out = PathBuf::from(env::var_os("OUT_DIR").expect("cargo sets OUT_DIR"));
    for (from, to) in SHARED {
        let src = shared.join(from);
        println!("cargo:rerun-if-changed={}", src.display());
        let text = fs::read(&src).unwrap_or_else(|e| {
            panic!(
                "{} cannot be read ({e}). Set TUNA_SHARED_DIR to the monorepo's shared/ directory.",
                src.display()
            )
        });
        fs::write(out.join(to), text).expect("OUT_DIR is writable");
    }
}
