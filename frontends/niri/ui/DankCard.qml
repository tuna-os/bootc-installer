import QtQuick
import "."

// DMS DankCard: a surfaceContainerHigh panel with the medium corner radius
// and an optional title in the accent colour. Children go in `content`.
Rectangle {
    id: card

    property int pad: Theme.spacingM
    property string title: ""
    default property alias content: contentItem.data
    readonly property real contentHeight: contentItem.childrenRect.height

    radius: Theme.cornerRadiusM
    color: Theme.surfaceContainerHigh
    implicitHeight: contentItem.childrenRect.height + pad * 2 + (titleLabel.visible ? titleLabel.height + Theme.spacingXS : 0)
    Accessible.role: Accessible.Pane
    Accessible.name: title

    StyledText {
        id: titleLabel
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: card.pad }
        text: card.title
        font.weight: Theme.fontWeightMedium
        color: Theme.primary
        visible: text !== ""
    }

    Item {
        id: contentItem
        anchors.fill: parent
        anchors.margins: card.pad
        anchors.topMargin: card.pad + (titleLabel.visible ? titleLabel.height + Theme.spacingXS : 0)
    }
}
