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
shared/browser/run.sh niri             # QML, compiled to WebAssembly
```

Niri does not use Broadway. Refer to [Niri](#niri-go--qml) below.

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

### Its geometry does not match the Xvfb capture

The same page, same build, lays out differently in the two harnesses: under
Xvfb the GNOME welcome content is centred in a 1691x732 window, and under
Broadway it sits hard against the right edge of a window whose chrome draws
about 1000px wide. The DOM reports a 1691px-wide surface at x=61 while the
frame ends near x=1060, and the content is centred for the former.

Which of the two is showing real geometry is not established. Chasing it
produced two confident wrong answers -- a viewport crop (the window fits the
1200px viewport, so there was none) and a stale Broadway repaint after a
mid-run resize (sizing the viewport up front changes nothing) -- so the honest
statement is that nobody has explained it yet.

So: use this harness for content, branding, copy keys and interaction, which
is what it is good at and how it found the branding leak fixed in #117. Do
**not** read layout or spacing off it, and do not use it to compare styling
between frontends. The Xvfb captures remain the reference for geometry.

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

Qt has no Broadway equivalent. Qt 5.12 to 5.15 had a WebGL streaming
platform plugin, but Qt 6 does not have it. The only route is Qt for
WebAssembly, which compiles the app with Emscripten. #104 tracks this work.

**The C++ compiles and links for wasm.** Qt for WebAssembly has no
`QProcess`. The four places that start a process now have a
`QT_CONFIG(process)` branch, and on wasm they log a warning and do nothing.
The installer and the capture harness link against the Qt 6.9.3
`wasm_singlethread` and `wasm_multithread` builds with Emscripten 3.1.70.
`wasm-kde.yml` builds them, and the backend tests, on each change.

**The page stops at the first KF6 import.** Served to Chromium, the
installer starts and the QML engine reports:

```
qrc:/qt/qml/org/tunaos/installer/Main.qml:4:1: module "org.kde.kirigami" is not installed
```

The KF6 QML stack is the work that remains:

| Module | For wasm |
|---|---|
| Kirigami 6.18 | builds with `-DUSE_DBUS=OFF -DKF_IGNORE_PLATFORM_CHECK=ON`. It needs the `wasm_multithread` Qt, because it uses `QtConcurrent`. Its metainfo does not list WebAssembly, so the platform check stops it without the flag. |
| Kirigami Addons (FormCard) | not tried. FormCard needs KI18n, KConfig, KCoreAddons, KGuiAddons and KColorScheme, and three other Kirigami Addons modules. KI18n needs gettext. |
| `org.kde.desktop` style | not tried. It paints through `QStyle` and the Plasma platform theme, and a browser has neither. |

To build it locally, install the Qt host and wasm builds with `aqtinstall`
and activate Emscripten 3.1.70. Then run the commands in `wasm-kde.yml`.

The Xvfb harness (`frontends/kde/tests/capture.cpp`) continues to make the
screenshots.

### Niri (Go + QML)

**Niri works.** `shared/browser/run.sh niri` shows every wizard page in
Chromium, and `walk.mjs` applies the same checks as for GNOME and XFCE.

The installer is a Go program, and cgo cannot compile to wasm. But the UI is
not in the Go. `frontends/niri/tests/gui/capture-screens.py` loads the
unmodified `ui/installer.qml` under plain Qt Quick, with stubs for the two
Quickshell modules. No Go is in that path.

`frontends/niri/tests/wasm/` uses the same method with a different Qt
platform. A small C++ host loads the QML and the stubs from the binary, and
Qt for WebAssembly draws the window into a `<canvas>`. The page itself is the
app, so no daemon is necessary. `walk.mjs` requests pages through
`window.niri`, not through the two files that `present.py` uses.

This path gives more than Broadway does:

- The host reads its own scene. Thus `walk.mjs` gets the text of each page,
  and it fails a page that has no text.
- The host runs two checks from the capture harness. The progress bar fill
  must have a size. Restart must stay disabled until the user acknowledges
  the recovery key.
- Qt Quick's software scene graph works in wasm. Thus the run needs no
  WebGL and no GPU.

The canvas gives no DOM geometry, the same as GTK3. The build steps and the
page interface are in `frontends/niri/tests/wasm/README.md` (#103).

### Summary

| Frontend | Toolkit | In a browser | Blocker |
|---|---|---|---|
| GNOME | GTK4 / libadwaita | **works** | — |
| XFCE | GTK3 | **works** | canvas only, so no DOM geometry |
| COSMIC | libcosmic (Iced fork) | not yet | `atomicwrites` has no wasm arm, via `cosmic-config` (#105) |
| KDE | Qt6 Widgets + Quick | not yet | C++ builds for wasm; the KF6 QML stack does not yet (#104) |
| Niri | Go + QML (Quickshell) | **works** | canvas only; Qt for WebAssembly, not Broadway (#103) |

Three of five work today. GNOME and XFCE use Broadway, which is part of GTK.
Niri uses Qt for WebAssembly, because its UI is QML that runs without the Go.
COSMIC and KDE also need a wasm build. #104 and #105 record the measurements
for each of them.
