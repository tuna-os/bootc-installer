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
    // A screen reader reads the words: without a name a label is an empty
    // node in the AT-SPI tree (walkthrough, dev c1da3d96).
    Accessible.role: Accessible.StaticText
    Accessible.name: text
    Accessible.ignored: !visible || text === ""
    Behavior on opacity { NumberAnimation { duration: Theme.mediumDuration; easing.type: Theme.standardEasing } }
}
