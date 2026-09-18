import QtQuick
import QtQuick.Controls
import "."

// DMS DankListItem: a row of a grouped list. Rows sit on surfaceContainerLow
// with the small inner radius; the first and last row of a group get the
// large outer radius, so a group reads as one rounded card split by 2px
// gaps. The selected row is the primaryContainer tone.
AbstractButton {
    id: root

    property bool isSelected: false
    property bool firstInGroup: true
    property bool lastInGroup: true
    property string primaryText: ""
    property string secondaryText: ""
    property bool monospace: false
    readonly property color contentColor: !enabled ? Theme.surfaceText38 : (isSelected ? Theme.primaryContainerText : Theme.surfaceText)
    readonly property color supportingColor: !enabled ? Theme.surfaceText38 : (isSelected ? Theme.primaryContainerText : Theme.surfaceVariantText)

    implicitHeight: Theme.listItemHeight
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.ListItem
    Accessible.name: primaryText
    Accessible.selected: isSelected

    background: Rectangle {
        color: root.isSelected ? Theme.primaryContainer : Theme.surfaceContainerLow
        radius: Theme.groupedListInnerRadius
        topLeftRadius: root.firstInGroup ? Theme.groupedListOuterRadius : radius
        topRightRadius: topLeftRadius
        bottomLeftRadius: root.lastInGroup ? Theme.groupedListOuterRadius : radius
        bottomRightRadius: bottomLeftRadius
        Behavior on color { ColorAnimation { duration: Theme.shortDuration } }
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            topLeftRadius: parent.topLeftRadius; topRightRadius: parent.topRightRadius
            bottomLeftRadius: parent.bottomLeftRadius; bottomRightRadius: parent.bottomRightRadius
            color: root.contentColor
            opacity: root.pressed ? Theme.stateLayerPressed : (root.hovered ? Theme.stateLayerHover : 0)
            Behavior on opacity { NumberAnimation { duration: Theme.shortDuration } }
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: -Theme.focusRingOffset
            radius: Theme.groupedListOuterRadius + Theme.focusRingOffset
            color: "transparent"
            border.color: Theme.primary
            border.width: Theme.focusRingWidth
            visible: root.visualFocus
        }
    }

    contentItem: Item {
        Column {
            anchors { left: parent.left; right: radio.left; verticalCenter: parent.verticalCenter; leftMargin: Theme.spacingL; rightMargin: Theme.spacingM }
            spacing: Theme.spacingXXS
            StyledText {
                width: parent.width
                text: root.primaryText
                isMonospace: root.monospace
                color: root.contentColor
                font.weight: Theme.fontWeightMedium
            }
            StyledText {
                width: parent.width
                text: root.secondaryText
                visible: text !== ""
                color: root.supportingColor
                font.pixelSize: Theme.fontSizeSmall
            }
        }
        // Material 3 radio: outlined circle, filled dot when selected.
        Rectangle {
            id: radio
            anchors { right: parent.right; verticalCenter: parent.verticalCenter; rightMargin: Theme.spacingL }
            width: 20; height: 20; radius: 10
            color: "transparent"
            border.width: 2
            border.color: root.isSelected ? Theme.primary : root.supportingColor
            Rectangle {
                anchors.centerIn: parent
                width: 10; height: 10; radius: 5
                color: Theme.primary
                visible: root.isSelected
            }
        }
    }
}
