# Rendering the installers in a browser

The Xvfb capture harnesses (`tests/gui/capture-screens.py` and its siblings)
can look at a frontend. They cannot touch it. This directory renders the same
real windows into a browser instead, so Playwright can screenshot **and**
drive them: click, type, trace, record video, step a wizard and check what
the next page did.

Nothing is reimplemented in HTML. The widgets are the widgets the shipped
Flatpak presents, drawn by GTK's own renderer, delivered over a socket.

```bash
shared/browser/run.sh gnome            # GTK4 + libadwaita
shared/browser/run.sh xfce             # GTK3
```

Output lands in `docs/browser/<frontend>/`: one PNG per wizard page plus
`browser-walkthrough-<frontend>.json`.

## How it works

GTK ships its own HTML5 backend, Broadway. A daemon (`gtk4-broadwayd` for
GTK4, `broadwayd` for GTK3) owns a display and serves it over HTTP; a client
started with `GDK_BACKEND=broadway` draws into it and receives real input
events back. No compositor, no GPU, no X server.

| Piece | What it does |
|---|---|
| `run.sh` | picks a free display, starts the daemon and the frontend, runs the driver, tears everything down |
| `present.py` | builds the frontend's real window from its own capture fixtures and holds it up |
| `walk.mjs` | connects Playwright, steps every wizard page, screenshots, asserts |

`present.py` imports each frontend's existing capture harness rather than
restating its mocks. The fake disks, the canned recipe and the guard that
fails the run if anything tries to launch fisherman are defined once, and
both harnesses use that definition.

Which page is showing is negotiated through two files — the browser writes
the page it wants, the app writes back which page it has actually drawn. The
browser waits for the second before it screenshots, so no image is ever
caught mid-transition. A GTK main loop is already running in that process; a
poll on a `GLib.timeout_add` is less machinery than an HTTP server for two
strings.

## Two things about Broadway that shape everything

**Text is never in the DOM.** GTK rasterises glyphs and Broadway ships them
as textures. There is no accessibility tree in the page, so `getByRole` and
`getByText` cannot work, and widgets are found by colour and geometry rather
than by label. This is the real limit of the approach: it verifies *design*,
not *semantics*. For text assertions, use the Xvfb harnesses, which read the
widget tree in-process.

**GTK4 and GTK3 do not render alike.**

| | GTK4 (GNOME) | GTK3 (XFCE) |
|---|---|---|
| DOM | a tree of positioned `<div>`s, one per render node, plus texture `<img>`s | a single `<canvas>` |
| Geometry from the DOM | yes — positions and sizes of every node | none |
| Screenshots | yes | yes |
| Mouse and keyboard | yes | yes |

So `walk.mjs` asserts geometry on GTK4 only, and says `canvas` rather than
silently reporting nothing for GTK3.

## What the checks actually catch

A blank window still writes a valid PNG, so file size alone proves nothing.
Three conditions together do:

- the app confirmed it drew the page that was asked for;
- the PNG is over 4 KB, so something was drawn;
- the PNG differs from the page before it.

The third is the one worth having. A per-page screenshot cannot notice a
wizard that quietly stopped advancing — every image is valid, every image is
of the same page. Comparing consecutive pages does notice. Verified by
pointing the driver at a page list nothing would ever advance: it reported
`the app never confirmed the page` for both pages and exited 1.

## Input works, and it is the point

Playwright's mouse and keyboard reach the real widgets. A click lands on a
`GtkButton` and fires its `clicked` handler; `keyboard.type` reaches a
focused `GtkEntry` and fires `changed`. Both confirmed against a GTK4 app
that logged what it received.

Locate a widget by colour and position, then drive it with `page.mouse` and
`page.keyboard` at coordinates. `page.click('selector')` will not work —
there is no selector for a widget that only exists as pixels.

## Requirements

| | |
|---|---|
| GTK4 path | `libgtk-4-bin` (`gtk4-broadwayd`), `gir1.2-gtk-4.0`, `gir1.2-adw-1` |
| GTK3 path | `libgtk-3-bin` (`broadwayd`), `gir1.2-gtk-3.0` |
| Driver | Node with `playwright` and its Chromium |

`walk.mjs` finds Playwright in a local `node_modules`, a global install, or
wherever `PLAYWRIGHT_MODULE` points. ESM `import` ignores `NODE_PATH`, and a
global install is the normal case on a machine that is not a Node project.

The daemon and the client must agree on `XDG_RUNTIME_DIR`, because that is
where the display socket lands. `run.sh` exports one for both. Worth knowing:
the XFCE capture harness sets its own when the environment has none, which is
how a client ends up searching a directory the daemon never wrote to, and the
only symptom is `cannot open display`.

The GNOME frontend needs its GResource bundle built (`meson setup build
-Dbuild-fisherman=false && ninja -C build`) and `BOOTC_RESOURCE` pointing at
it. A stale bundle fails with `Unable to retrieve child object ... from class
template` followed by an `AttributeError` on the missing child, because the
compiled templates no longer match the Python that binds them.

## The other three frontends

The GTK frontends work today. The rest do not, and the reasons are specific
rather than "needs work".

### COSMIC (Rust, libcosmic)

Upstream Iced does target the browser through wgpu on WebGL. This frontend
does not use upstream Iced: it uses `libcosmic`, which vendors its own Iced
fork, and it builds the whole thing against `tokio` with `features = ["full"]`.

Tested, not assumed — `cargo check --target wasm32-unknown-unknown` in
`frontends/cosmic`:

```
error: could not compile `mio` (lib) due to 48 previous errors
```

`tokio`'s full feature set pulls in `mio`, and `mio` has no
`wasm32-unknown-unknown` support: its `IoSource` has no `register`,
`reregister` or `deregister` there, and the `UdpSocket` conversions expect
file descriptors that the target does not have. The build never reaches
libcosmic, let alone its renderer.

That is where the obvious reading stops, and it is wrong. **The COSMIC
installer renders in a browser**, and Playwright can click through it —
eight patches, 278 diff lines, five of them upstream. `wasm-patches/` has
them, the screenshots and the commands.

The most useful thing found there: libcosmic's vendored `iced_winit`
**already has a web path**, inherited from upstream iced, which attaches a
canvas and spawns the event loop through `wasm_bindgen_futures`. It had
simply never been compiled, so it drifted out of step with the winit it
pins — renamed traits, a missing struct field, one lifetime bound. Nobody
decided against the web; nobody built it.

The single most costly line is in `iced_wgpu`: it sets
`VK_LOADER_DRIVERS_DISABLE` under `cfg(wayland_platform)` and unsets it
ungated. wasm panics on `remove_var`, so no libcosmic app can reach its
first frame in a browser until that cfg is matched up. One line.

#105 tracks the upstream conversation.

### KDE (C++, Qt6 Widgets + Quick)

Qt has no Broadway equivalent. The WebGL streaming platform plugin that would
have been the closest match was a Qt 5.12–5.15 feature and is gone in Qt6, so
the only route is Qt for WebAssembly: an Emscripten toolchain plus a
wasm-targeted Qt build, neither of which is a package install. The frontend
also links `Qt6::Widgets`, and the capture path would need every system call
it makes stubbed before it could run in a sandbox with no processes.

Feasible in principle, a large piece of work, and the Xvfb harness
(`frontends/kde/tests/capture.cpp`) already covers the screenshots.

### Niri (Go + QML)

The most promising of the three, which is not the obvious answer.

The installer is a Go program and cgo cannot target wasm, so the shipped
binary is not going anywhere. That does not matter, because the UI is not in
the Go. `frontends/niri/tests/gui/capture-screens.py` already loads the same
unmodified `ui/installer.qml` under a plain Qt Quick runtime, supplying stub
implementations of the two Quickshell modules it imports. No Go participates
in that path at all.

So the browser version is the same trick against a different Qt platform:
Qt Quick for WebAssembly in place of the offscreen plugin, with the QML and
the stubs bundled into the package. It needs the Emscripten and Qt-for-wasm
toolchain, which is the real cost and is shared with KDE, but it needs no
architectural change. Tracked in #103.

### Summary

| Frontend | Toolkit | In a browser | Blocker |
|---|---|---|---|
| GNOME | GTK4 / libadwaita | **works** | — |
| XFCE | GTK3 | **works** | canvas only, so no DOM geometry |
| COSMIC | libcosmic (Iced fork) | not yet | `atomicwrites` has no wasm arm, via `cosmic-config` (#105) |
| KDE | Qt6 Widgets + Quick | not yet | needs Emscripten + a Qt-for-wasm build (#104) |
| Niri | Go + QML (Quickshell) | not yet | needs Qt-for-wasm; the UI itself is Go-free (#103) |

Two of five today, and the two that work are the two whose toolkit ships a
browser backend in the box. That is the pattern: Broadway is a GTK feature,
not a general technique, and everything else has to be compiled to wasm
instead of streamed.

Niri looks furthest because it is written in Go, and is closest because its
UI is pure QML that already renders without the Go. COSMIC looks closest
because Iced runs on the web, and is not — but it is nearer than its first
error suggests, and its remaining blocker is a small upstream one rather
than anything in this repository. #103, #104 and #105 carry the detail, and
each records what was measured rather than what was assumed.
