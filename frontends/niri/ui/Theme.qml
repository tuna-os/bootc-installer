pragma Singleton
import QtQuick

// DankMaterialShell's theme tokens, mirrored.
//
// This installer is modelled on DMS (see README) and runs inside a DMS/niri
// session, so it should look like it belongs there rather than inventing its
// own palette. Names, scale and stock values are taken from DMS's
// quickshell/Common/Theme.qml and PLUGINS/THEME_REFERENCE.md, so anything
// written against DMS's docs reads the same here.
//
// DMS derives its real colours from the user's wallpaper via matugen at
// runtime; the values below are its STOCK dark fallbacks, which is the right
// baseline for an installer that runs before any of that is configured. If
// this ever needs to follow a live DMS session, this is the single file to
// point at DMS's exported colours — every call site already goes through it.
QtObject {
    // ── Surfaces ────────────────────────────────────────────────────────────
    property color surface: "#1a1c1e"
    property color surfaceContainerLowest: "#0e1013"
    property color surfaceContainerLow: "#181a1d"
    property color surfaceContainer: "#1e2023"
    property color surfaceContainerHigh: "#292b2f"
    property color surfaceContainerHighest: "#343740"
    property color surfaceVariant: "#44464f"

    // ── Content ─────────────────────────────────────────────────────────────
    // NAMING follows DMS's own property names, not the shorthand in its
    // THEME_REFERENCE.md. "onSurface"/"onPrimary" cannot be QML property names
    // here: `on<Capital>` is signal-handler syntax, so `onPrimary` parses as a
    // handler for changes to `primary` and the file fails to load with "Cannot
    // assign a value to a signal". DMS uses the *Text spellings for exactly
    // this reason.
    property color surfaceText: "#e3e8ef"
    property color surfaceVariantText: "#c4c7c5"
    property color outline: "#8e918f"

    // ── Semantic ────────────────────────────────────────────────────────────
    property color primary: "#42a5f5"
    property color primaryText: "#ffffff"
    property color primaryContainer: "#1976d2"
    property color error: "#F2B8B5"
    property color warning: "#FFB77C"
    property color success: "#A6E3A1"

    // ── Metrics ─────────────────────────────────────────────────────────────
    readonly property real spacingXXS: 2
    readonly property real spacingXS: 4
    readonly property real spacingS: 8
    readonly property real spacingM: 12
    readonly property real spacingL: 16
    readonly property real spacingXL: 24

    readonly property real cornerRadius: 12
    readonly property real cornerRadiusSmall: 8
    readonly property real cornerRadiusLarge: 16

    readonly property real fontSizeSmall: 12
    readonly property real fontSizeMedium: 14
    readonly property real fontSizeLarge: 16
    readonly property real fontSizeXLarge: 20

    // DMS uses OutCubic at ~200ms for standard transitions.
    readonly property int shortDuration: 150
    readonly property int mediumDuration: 200
    readonly property int standardEasing: Easing.OutCubic
}
