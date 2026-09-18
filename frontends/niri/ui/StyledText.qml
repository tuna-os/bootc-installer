import QtQuick
import "."

// DMS StyledText: the design system's font, size, colour and wrapping by
// default, monospace on request (data is the protagonist in an installer).
Text {
    property bool isMonospace: false
    color: Theme.surfaceText
    font.family: isMonospace ? Theme.monoFontFamily : Theme.fontFamily
    font.pixelSize: Theme.fontSizeMedium
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    elide: Text.ElideRight
    verticalAlignment: Text.AlignVCenter
    Behavior on opacity { NumberAnimation { duration: Theme.mediumDuration; easing.type: Theme.standardEasing } }
}
