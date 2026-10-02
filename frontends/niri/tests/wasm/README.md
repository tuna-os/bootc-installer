# Niri wizard in a browser (Qt for WebAssembly)

This directory compiles the Niri wizard to WebAssembly. The browser then shows
the real QML, and Playwright can step through it, click it and read it.

The build does not compile Go. The host in `main.cpp` loads the same unmodified
`ui/installer.qml` that `tests/gui/capture-screens.py` loads under PyQt6. It
uses the same Quickshell stubs from `tests/qml-stubs/`. The stubbed `Process`
never starts a program, and a browser cannot start one.

| File | What it does |
|---|---|
| `main.cpp` | loads the wizard, steps the pages and reports the state to the page |
| `CMakeLists.txt` | puts `ui/`, the stubs and the progress transcript into the binary |
| `shell.html` | starts the wasm module and gives the page `window.niri` |

## Build and walk

You need Qt 6.9 for `wasm_singlethread`, the host Qt of the same version, and
Emscripten 3.1.70. `aqtinstall` installs both Qt builds:

```bash
pip install aqtinstall ninja
aqt install-qt linux desktop 6.9.3 linux_gcc_64 -O ~/qt
aqt install-qt all_os wasm 6.9.3 wasm_singlethread -O ~/qt
git clone --depth 1 https://github.com/emscripten-core/emsdk.git ~/emsdk
~/emsdk/emsdk install 3.1.70 && ~/emsdk/emsdk activate 3.1.70
source ~/emsdk/emsdk_env.sh

~/qt/6.9.3/wasm_singlethread/bin/qt-cmake -G Ninja \
  -S frontends/niri/tests/wasm -B build-wasm-niri \
  -DQT_HOST_PATH=$HOME/qt/6.9.3/gcc_64
cmake --build build-wasm-niri

shared/browser/run.sh niri
```

`run.sh` serves `build-wasm-niri/` on a local port. Set `NIRI_WASM_DIR` to use a
different directory. The images and `browser-walkthrough-niri.json` go to
`docs/browser/niri/`.

## The page interface

`shell.html` gives `shared/browser/walk.mjs` three things:

| Name | Value |
|---|---|
| `niri.ready` | `true` when the Qt `main()` runs |
| `niri.show(name)` | changes to the wizard page `name` |
| `niri.state()` | `{pages, current, text, checks, error}` |

The pages and the steps for each page are the same as `PAGES` in
`capture-screens.py`. The install page gets the real fisherman transcript
through `appendLog()`. The recovery page gets the `recovery_key` event.

`current` changes only after Qt draws a frame of the page. Thus the browser
does not take a screenshot during a page change.

`text` contains the text of the visible page. GTK Broadway sends text as
pixels, but this host reads its own scene. `checks` contains two checks from
`capture-screens.py`:

- `progress-bar`: the fill of the progress bar has a size and is visible.
- `recovery-key`: the key is in the text, and Restart is disabled.

`walk.mjs` fails a page if its text is empty or if a check fails.

## Scene graph

The `?backend=software` query sets `QT_QUICK_BACKEND=software`. This
renderer does not use WebGL, so headless Chromium needs no GPU and no
SwiftShader flags. `run.sh` uses it by default. To use the WebGL renderer,
set `NIRI_QUICK_BACKEND=` (empty). Both renderers show the same pages in
headless Chromium.

## Limits

- The window fills the browser viewport (1200x820), not the 800x600 of the
  Xvfb capture. Use the Xvfb capture for layout.
- The fonts come from Qt for WebAssembly, not from the system.
- Mouse and keyboard input go to the real QML. A click on the welcome button
  changes the wizard to the disk page. The stub then supplies the disks.
