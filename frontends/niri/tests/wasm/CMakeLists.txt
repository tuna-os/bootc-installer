# The Niri wizard compiled for the browser with Qt for WebAssembly.
#
# No Go is built here. The host loads the same unmodified ui/installer.qml
# that tests/gui/capture-screens.py loads under PyQt6, with the same
# Quickshell stubs from tests/qml-stubs. The stubbed Process never spawns
# anything, and a browser has no processes to spawn anyway.
#
#   qt-cmake -S frontends/niri/tests/wasm -B build-wasm-niri -G Ninja
#   cmake --build build-wasm-niri
#
# qt-cmake must come from a Qt built for wasm32-emscripten (wasm_singlethread
# is enough), with the matching Emscripten SDK on PATH. See README.md here.
cmake_minimum_required(VERSION 3.21)
project(niri_wasm LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2)

get_filename_component(NIRI_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
get_filename_component(REPO_ROOT "${NIRI_ROOT}/../.." ABSOLUTE)

qt_add_executable(niri-wasm main.cpp)

# A browser has no filesystem to read ui/ or tests/qml-stubs/ from, so both
# go into the binary. BASE keeps their relative layout: installer.qml still
# finds Theme through its own qmldir and `import "."`, and the stubs keep the
# Quickshell/ and Quickshell/Io/ directories that `import Quickshell` needs.
file(GLOB NIRI_UI RELATIVE "${NIRI_ROOT}" CONFIGURE_DEPENDS
     "${NIRI_ROOT}/ui/*.qml" "${NIRI_ROOT}/ui/qmldir")
file(GLOB_RECURSE NIRI_STUBS RELATIVE "${NIRI_ROOT}" CONFIGURE_DEPENDS
     "${NIRI_ROOT}/tests/qml-stubs/*")
list(TRANSFORM NIRI_UI PREPEND "${NIRI_ROOT}/")
list(TRANSFORM NIRI_STUBS PREPEND "${NIRI_ROOT}/")
qt_add_resources(niri-wasm "niri_qml"
    PREFIX "/niri"
    BASE "${NIRI_ROOT}"
    FILES ${NIRI_UI} ${NIRI_STUBS})

# The install screen is fed fisherman's real transcript, as in the capture
# harness, so the progress bar is driven through appendLog().
qt_add_resources(niri-wasm "niri_fixtures"
    PREFIX "/fixtures"
    BASE "${REPO_ROOT}/shared/progress"
    FILES "${REPO_ROOT}/shared/progress/dry-run-transcript.ndjson")

target_link_libraries(niri-wasm PRIVATE
    Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick Qt6::QuickControls2)

# Qt for wasm is static, so every QML module installer.qml imports
# (QtQuick.Controls, QtQuick.Layouts) has to be linked in. The import
# scanner finds them by reading the QML; point it at the real sources and
# at the stubs, which it must resolve rather than report as missing.
set_target_properties(niri-wasm PROPERTIES
    QT_QML_ROOT_PATH "${NIRI_ROOT}/ui"
    QT_QML_IMPORT_PATH "${NIRI_ROOT}/tests/qml-stubs")
qt_import_qml_plugins(niri-wasm)

if(EMSCRIPTEN)
    # embind is what exposes niriShow()/niriState() to the page. The page
    # served is shell.html, so Qt's generated niri-wasm.html is left unused.
    target_link_options(niri-wasm PRIVATE -lembind)
    # qtloader.js refuses to pass an environment (?backend=software in
    # shell.html) unless the module exports ENV.
    set_target_properties(niri-wasm PROPERTIES QT_WASM_EXTRA_EXPORTED_METHODS "ENV")
    configure_file(shell.html "${CMAKE_CURRENT_BINARY_DIR}/index.html" COPYONLY)
endif()
