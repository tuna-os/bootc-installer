# Dependency choices

`cargo-sources.json` describes the crates that `Cargo.lock` pins, and
`just check-cargo-sources` verifies it. A crate that is not in the lockfile
needs a new `cargo-sources.json` in the same commit.

- `image_catalog`, `hardware`, `preflight`, `tour` and `i18n` use `std` and
  `serde_json` only.
- `offline` uses `sha2` for the SHA256 of the staged fisherman. `sha2` was
  in `Cargo.lock` before (libcosmic pulls it in), so `Cargo.toml` names a
  crate that is already vendored and `cargo-sources.json` did not change.
- `i18n` is a small shim, not Fluent. `fl!` needs `i18n-embed` and
  `rust-embed` as direct dependencies and an asset directory at build
  time. No translation ships yet, so the shim is the smaller change. See
  the comment at the top of `src/i18n.rs`.

There is no phone companion. The earlier port had a hand-written HTTP
server because no TLS stack is vendored, and it sent the account password
over plain HTTP. #293 removed it.
