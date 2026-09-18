import QtQuick
import QtQuick.Controls
import "."

// DMS DankButton: a filled Material 3 button. `tonal` gives the secondary
// (surfaceContainerHigh) look DMS uses for Back/Close; `destructive` the
// error tone for the one action that erases a disk. Round (pill) at rest,
// squarer while pressed, state layer on hover/press, focus ring on keyboard.
AbstractButton {
    id: root

    property bool tonal: false
    property bool destructive: false
    property real buttonHeight: Theme.buttonHeightS
    property color backgroundColor: destructive ? Theme.error : (tonal ? Theme.surfaceContainerHigh : Theme.primary)
    property color textColor: destructive ? "#601410" : (tonal ? Theme.surfaceText : Theme.primaryText)
    readonly property color contentColor: enabled ? textColor : Theme.surfaceText38
    readonly property real sidePadding: buttonHeight <= Theme.buttonHeightS ? Theme.spacingL : Theme.spacingXL

    implicitWidth: Math.max(label.implicitWidth + sidePadding * 2, Theme.buttonMinWidth)
    implicitHeight: buttonHeight
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    Accessible.role: Accessible.Button
    Accessible.name: text

    background: Rectangle {
        radius: root.pressed ? Theme.cornerRadiusS : height / 2
        color: root.enabled ? root.backgroundColor : Theme.surfaceText12
        scale: root.pressed ? Theme.pressScale : 1.0
        Behavior on radius { NumberAnimation { duration: Theme.shortDuration; easing.type: Theme.standardEasing } }
        Behavior on scale { NumberAnimation { duration: Theme.shortDuration; easing.type: Theme.standardEasing } }

        // State layer (DMS StateLayer): the content colour at 8%/12%.
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: root.contentColor
            opacity: root.pressed ? Theme.stateLayerPressed : (root.hovered ? Theme.stateLayerHover : 0)
            Behavior on opacity { NumberAnimation { duration: Theme.shortDuration } }
        }
        // Focus ring (DMS FocusRing): outside the shape, primary, 2px.
        Rectangle {
            anchors.fill: parent
            anchors.margins: -Theme.focusRingOffset
            radius: parent.radius + Theme.focusRingOffset
            color: "transparent"
            border.color: Theme.primary
            border.width: Theme.focusRingWidth
            visible: root.visualFocus
        }
    }

    contentItem: StyledText {
        id: label
        text: root.text
        color: root.contentColor
        font.weight: Theme.fontWeightMedium
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
