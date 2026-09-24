pragma Singleton
import QtQuick

// DankMaterialShell's design tokens, mirrored from dank-qml-common
// (DankCommon/Common/Style.qml) so this installer reads as part of the DMS
// session it runs in. Names follow DMS's own property names (the *Text
// spellings, not `on<Capital>`, which QML parses as signal handlers).
//
// DMS derives its real colours from the wallpaper via matugen at runtime;
// the values below are its stock dark fallbacks, the right baseline for an
// installer that runs before any of that is configured. To follow a live
// DMS session, point this one file at DMS's exported colours: every call
// site already goes through it.
QtObject {
    // ── Surfaces (Style.qml stock dark) ────────────────────────────────────
    property color surface: "#141218"
    property color surfaceDim: "#141218"
    property color surfaceBright: "#3b383e"
    property color surfaceContainerLowest: "#0f0d13"
    property color surfaceContainerLow: "#1d1b20"
    property color surfaceContainer: "#211f24"
    property color surfaceContainerHigh: "#2b292f"
    property color surfaceContainerHighest: "#36343b"
    property color surfaceVariant: "#49454e"

    // ── Content ─────────────────────────────────────────────────────────────
    property color surfaceText: "#e6e0e9"
    property color surfaceVariantText: "#cac4cf"
    property color outline: "#948f99"
    property color outlineVariant: "#49454f"

    // ── Semantic ────────────────────────────────────────────────────────────
    property color primary: "#D0BCFF"
    property color primaryText: "#381E72"
    property color primaryContainer: "#4F378B"
    property color primaryContainerText: "#EADDFF"
    property color secondary: "#CCC2DC"
    property color error: "#F2B8B5"
    property color warning: "#FF9800"
    property color success: "#4CAF50"

    // State layers (Style.stateLayer*)
    readonly property real stateLayerHover: 0.08
    readonly property real stateLayerFocus: 0.12
    readonly property real stateLayerPressed: 0.12
    function withAlpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
    readonly property color surfaceText38: withAlpha(surfaceText, 0.38)
    readonly property color surfaceText12: withAlpha(surfaceText, 0.12)

    // ── Metrics (Style.qml) ─────────────────────────────────────────────────
    readonly property real spacingXXS: 2
    readonly property real spacingXS: 4
    readonly property real spacingS: 8
    readonly property real spacingM: 12
    readonly property real spacingL: 16
    readonly property real spacingXL: 24

    readonly property real cornerRadiusXS: 4
    readonly property real cornerRadiusS: 8
    readonly property real cornerRadiusM: 12
    readonly property real cornerRadiusL: 16
    readonly property real cornerRadiusXL: 28
    readonly property real cornerRadius: cornerRadiusM
    readonly property real groupedListInnerRadius: cornerRadiusXS
    readonly property real groupedListOuterRadius: cornerRadiusL
    readonly property real groupedListGap: spacingXXS

    readonly property real iconSize: 24
    readonly property real iconButtonSize: 40
    readonly property real listItemHeight: 56
    readonly property real buttonHeightXS: 32
    readonly property real buttonHeightS: 40
    readonly property real buttonHeightM: 56
    readonly property real buttonMinWidth: 58
    readonly property real fieldHeight: 42
    readonly property real outlineWidth: 1
    readonly property real outlineWidthFocused: 2
    readonly property real focusRingWidth: 2
    readonly property real focusRingOffset: 4
    readonly property real pressScale: 0.98

    // ── Type (Style.fontFamily / monoFontFamily; DMS's Fonts.sans/mono) ─────
    // Google Sans Flex is DMS's default UI face; the Flatpak bundles Inter as
    // the fallback so a runner without DMS's fonts renders the same
    // hierarchy. Fira Code is DMS's mono face; JetBrains Mono the fallback.
    readonly property string fontFamily: "Google Sans Flex, Inter, sans-serif"
    readonly property string monoFontFamily: "Fira Code, JetBrains Mono, monospace"
    readonly property int fontSizeSmall: 12
    readonly property int fontSizeMedium: 14
    readonly property int fontSizeLarge: 16
    readonly property int fontSizeXLarge: 20
    readonly property int fontSizeXXLarge: 28
    readonly property int fontSizeDisplay: 36
    readonly property int fontWeightMedium: Font.Medium
    readonly property int fontWeightBold: Font.Bold

    // ── Motion (Appearance.anim) ────────────────────────────────────────────
    readonly property int shortDuration: 150
    readonly property int mediumDuration: 300
    readonly property int longDuration: 500
    readonly property int standardEasing: Easing.OutCubic
    readonly property var standardCurve: [0.2, 0, 0, 1, 1, 1]
    readonly property var expressiveEffectsCurve: [0.34, 0.8, 0.34, 1, 1, 1]
}
