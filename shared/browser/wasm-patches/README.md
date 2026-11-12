# Getting the COSMIC frontend to build for wasm32

These patches take `frontends/cosmic` from "48 errors in mio, nowhere
near a browser" to a clean `cargo check --target wasm32-unknown-unknown`.
The files here are the record of the first experiment. The build does not
apply them. CI builds the same fixes from the tuna-os forks.

Tracked in #105.

## Where each patch comes from now

pop-os does not accept LLM-generated changes. It closed libcosmic#1446,
iced#397 and iced#398. Agents send no more upstream PRs. The advisory job
`.github/workflows/wasm-cosmic.yml` builds against the tuna-os forks. Each
fork is pinned by a full commit SHA in `frontends/cosmic/web/`.

| Patch | Source in the wasm job |
|---|---|
| `01` | tuna-os/rust-atomicwrites, branch `wasm/fallback-imp-for-unsupported-targets`, pinned in `web/cargo-patch.toml` |
| `02` | tuna-os/libcosmic `master` (tuna-os/libcosmic#1), pinned in `web/cargo-patch.toml` |
| `03`, `06` | tuna-os/iced#2 and tuna-os/iced#1. `web/assemble-iced.sh` applies the two commits on top of the iced commit that libcosmic pins. The fork `master` has them only on a newer iced, and libcosmic does not build against that iced. |
| `04`, `08` | `frontends/cosmic/src`, under `cfg(unix)` and `cfg(target_arch = "wasm32")` |
| `05` | `frontends/cosmic/Cargo.toml`: the `desktop` feature (the default) and the `web` feature |
| `07` | not applied. No fork has it. The `cargo check` does not need it. A render in Chromium needs it. |

The patch overrides reach Cargo only through `cargo --config` in that job.
`Cargo.toml` has no `[patch]`. `Cargo.lock`, the Flatpak cargo sources and
the native build do not change. Thus a fork that stops building does not
block `dev`.

`08` changed. The web build needs no `wasm_bindgen(start)` entry, because
wasm-bindgen starts the `main` of a binary. Thus the build needs no new
dependency, and `Cargo.lock` stays the same. On wasm, the probe reads
`shared/probe/fixtures/laptop.json`, and the install path refuses to run.

`05` changed too. `tokio/full`, `libcosmic/tokio` and `libcosmic/desktop`
are in the `desktop` feature. The `web` feature turns off none of them.
Thus the web build is `--no-default-features --features web`.

A person can still send `06` or `02` to pop-os by hand. When upstream
merges one, remove its entry from `web/`.

## Result

**It renders, and Playwright can drive it.**

| | |
|---|---|
| ![welcome](screenshots/01-welcome.png) | ![select a disk](screenshots/02-select-a-disk.png) |

Real libcosmic: the COSMIC header bar with its window controls, the
`cosmic-theme` dark palette, the step indicator, the accent-coloured pill
button. Drawn by wgpu on WebGL in headless Chromium. One Playwright click at
the "Get started" coordinates advanced it to step 2, which lists the capture
fixtures' disks — so input reaches the widgets, not just the canvas.

"Welcome to Linux" rather than a product name is the branding resolver
behaving correctly: there is no `os-release` in a browser, so it falls
through to the neutral copy, exactly as `shared/branding/README.md`
specifies.

The run is clean — no panics, no unhandled rejections, and the console
carries only WebGPU-unavailable notices (expected; the build asks for
WebGL) and WebGL performance warnings.

## The patches

Eight patches, 278 diff lines. Five are fixes to libraries, three are ours.

| | What | Where it belongs |
|---|---|---|
| `01` | `atomicwrites` has `mod imp` for unix, redox and windows, and no wasm arm, so `imp` does not resolve. Adds one using `std::fs::rename`. | tuna-os/rust-atomicwrites |
| `02` | `cosmic-config` binds `system_path` under `cfg(unix)` and `cfg(windows)`, then uses it unconditionally. wasm is neither, so it is used but never defined. Adds a `not(any(unix, windows))` arm returning `None`. | tuna-os/libcosmic |
| `03` | libcosmic's vendored `iced_winit` has a **real web path that has bit-rotted** against the winit it pins. Four renamed APIs, one struct field the wasm arm never learned about, one lifetime bound. | tuna-os/iced |
| `06` | `iced_wgpu` sets `VK_LOADER_DRIVERS_DISABLE` under `cfg(wayland_platform)` but **unsets it ungated**. wasm cannot unset an environment variable — std panics rather than failing softly — so every browser build dies there. | tuna-os/iced |
| `07` | libcosmic exposes no way to reach iced's `webgl` feature. Adds a passthrough, off by default. | not carried |
| `04` | Our own `offline.rs` imports `std::os::unix` and calls `OpenOptions::mode` unconditionally. Gates both on `cfg(unix)`. | `frontends/cosmic` |
| `05` | `tokio` trimmed to the four features this crate uses, libcosmic's `desktop` and `tokio` features dropped, `webgl` enabled, a `cdylib` lib target added. | `frontends/cosmic` |
| `08` | A `wasm_bindgen(start)` entry beside `main`, and the two host-dependent calls gated: the `live_iso_image` probe (no host to shell out to) and `scan_disks` (no lsblk, no tokio reactor — it returns the capture fixtures instead). The frontend has since replaced `scan_disks` with `probe()` (`shared/probe/README.md`), so this hunk no longer applies as written. | `frontends/cosmic` |

## The interesting one

`03` is the finding worth carrying forward. The assumption was that
libcosmic never intended to run on the web. That is not what the code says:
`iced/winit/src/lib.rs` has `#[cfg(target_arch = "wasm32")]` blocks that
attach a canvas, spawn the event loop through
`wasm_bindgen_futures::spawn_local` and pull the canvas back out of the
window. The web support is **there**, inherited from upstream iced. It has
simply never been compiled, so it drifted:

- winit 0.31 renamed the web extension traits — `WindowAttributesExtWebSys`
  → `WindowAttributesWeb` (and it is now a platform-attributes struct passed
  to `with_platform_attributes`, not an extension trait), `WindowExtWebSys`
  → `WindowExtWeb`, `EventLoopExtWebSys` → `EventLoopExtWeb`.
- `EventLoopExtWeb` no longer has `spawn_app`; `run_app` is the entry point,
  and on web it does not return.
- `Window::canvas()` hands back a `Ref<HtmlCanvasElement>` rather than the
  element.
- Their own `Runner` grew an `is_booted` field that only the non-wasm
  initializer was updated for.
- `spawn_local` needs a `'static` future, so the compositor associated type
  needs a `'static` bound that the non-wasm path never required.

Every one of these is what you would expect from code nobody builds. None of
them is a design problem. A CI job that only ran `cargo check --target
wasm32-unknown-unknown` on libcosmic would have caught all six, and `06`
besides.

`06` is the one worth singling out, because it is a one-line asymmetry with
a total effect: the `set_var` carries `#[cfg(wayland_platform)]` and the
matching `remove_var` carries nothing. On a desktop that is harmless — it
clears a variable that was never set. On wasm `std::env::remove_var` panics
outright, so the compositor never finishes starting and no browser build of
any libcosmic app can draw a frame.

## Running it yourself

`index.html`, `render.mjs` and `drive.mjs` here are the shell and the two
Playwright drivers used for the screenshots above.

The screenshots came from the first experiment, which had `07` and a
`cdylib` target. The wasm job has neither, so these commands are a record
of that run. A render needs `07` in a fork first.

```bash
cargo build --target wasm32-unknown-unknown --lib
wasm-bindgen --target web --out-dir web --no-typescript \
    target/wasm32-unknown-unknown/debug/tuna_installer_cosmic.wasm
cd web && npx http-server -p 8099 -s &
node render.mjs 45000     # load, report status and console, screenshot
node drive.mjs            # click through to step 2
```

The debug artefact is 396 MB before `wasm-bindgen` and 46 MB after, which
loads in about 40 seconds. A release build would be far smaller and is what
any real harness should use. Chromium needs `--use-gl=swiftshader
--enable-unsafe-swiftshader` on a runner with no GPU; WebGPU is not
available there, which is why `07` exists.

## Reproducing the build

The commands of `wasm-cosmic.yml`, in `frontends/cosmic`:

```bash
rustup target add wasm32-unknown-unknown
web/assemble-iced.sh
cargo update --config web/cargo-patch.toml -p atomicwrites
cargo check --target wasm32-unknown-unknown \
    --no-default-features --features web --config web/cargo-patch.toml
git checkout Cargo.lock
```

The `cargo update` changes `Cargo.lock` for the forks. Do not commit that
change. `git checkout Cargo.lock` puts it back.

The first experiment used libcosmic `43a50cb`, winit
`0.31.0-beta.2` (`pop-os/winit`, tag `cosmic-0.14`), wgpu 28, iced 0.14.
The wasm job uses tuna-os/libcosmic `f59dea6` and iced `5fc4372` with `06`
and `03`. These use the same winit.
