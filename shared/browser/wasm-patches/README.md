# Getting the COSMIC frontend to build for wasm32

These five patches take `frontends/cosmic` from "48 errors in mio, nowhere
near a browser" to a clean `cargo check --target wasm32-unknown-unknown`.
They are a record of an experiment, not something the build applies: four of
the five belong upstream, and the point of keeping them here is that the
upstream asks are now specific enough to make.

Tracked in #105.

## Result

```
cargo check --target wasm32-unknown-unknown
    Finished `dev` profile [unoptimized + debuginfo] target(s)
```

Everything compiles: `wgpu` 28, iced 0.14 in full (`core`, `graphics`,
`runtime`, `futures`, `tiny_skia`, `wgpu` **and `winit`**), `cosmic-config`,
`cosmic-theme`, `libcosmic`, and the installer crate itself.

**This is a type-check, not a running app.** It says the code can be built
for the browser. It does not say the renderer draws, that the event loop
runs, or that anything appears on a canvas. That is the next experiment, and
it needs `wasm-bindgen`, an HTML shell and a WebGL or WebGPU context.

## The patches

| | What | Where it belongs |
|---|---|---|
| `01` | `atomicwrites` has `mod imp` for unix, redox and windows, and no wasm arm, so `imp` does not resolve. Adds one using `std::fs::rename`. | upstream, [jackpot51/rust-atomicwrites](https://github.com/jackpot51/rust-atomicwrites) |
| `02` | `cosmic-config` binds `system_path` under `cfg(unix)` and `cfg(windows)`, then uses it unconditionally. wasm is neither, so it is used but never defined. Adds a `not(any(unix, windows))` arm returning `None`. | upstream, pop-os/libcosmic |
| `03` | libcosmic's vendored `iced_winit` has a **real web path that has bit-rotted** against the winit it pins. Four renamed APIs, one struct field the wasm arm never learned about, one lifetime bound. | upstream, pop-os/libcosmic |
| `04` | Our own `offline.rs` imports `std::os::unix` and calls `OpenOptions::mode` unconditionally. Gates both on `cfg(unix)`. | this repo |
| `05` | `tokio` trimmed to the four features this crate uses, libcosmic's `desktop` and `tokio` features dropped. | this repo |

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
wasm32-unknown-unknown` on libcosmic would have caught all six.

## Reproducing

```bash
cp -r frontends/cosmic /tmp/cosmic-wasm
cp -r <cargo checkout of libcosmic>   /tmp/libcosmic
cp -r <cargo checkout of atomicwrites> /tmp/atomicwrites
# apply 01 and 02 and 03 to the copies, 04 and 05 to /tmp/cosmic-wasm,
# then point Cargo at them:
#   [patch."https://github.com/pop-os/libcosmic"]
#   libcosmic = { path = "/tmp/libcosmic" }
#   cosmic-config = { path = "/tmp/libcosmic/cosmic-config" }
#   cosmic-theme = { path = "/tmp/libcosmic/cosmic-theme" }
#   [patch."https://github.com/jackpot51/rust-atomicwrites"]
#   atomicwrites = { path = "/tmp/atomicwrites" }
cd /tmp/cosmic-wasm && rustup target add wasm32-unknown-unknown
cargo check --target wasm32-unknown-unknown
```

Pinned at libcosmic `43a50cb`, winit `0.31.0-beta.2`
(`pop-os/winit`, tag `cosmic-0.14`), wgpu 28, iced 0.14. The winit API
details above are specific to that pin.
