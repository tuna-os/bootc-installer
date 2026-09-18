import QtQuick
import QtQuick.Controls
import "."

// DMS DankTextField, filled variant: surfaceContainerHigh field with the
// extra-small radius, a 1px outlineVariant border that becomes a 2px primary
// border on focus, placeholder in the variant text colour.
TextField {
    id: root

    property bool isError: false
    property string supportingText: ""

    implicitHeight: Theme.fieldHeight
    implicitWidth: 320
    leftPadding: Theme.spacingM
    rightPadding: Theme.spacingM
    color: enabled ? Theme.surfaceText : Theme.surfaceText38
    placeholderTextColor: Theme.surfaceVariantText
    selectionColor: Theme.primary
    selectedTextColor: Theme.primaryText
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSizeMedium
    verticalAlignment: TextInput.AlignVCenter

    background: Rectangle {
        radius: Theme.cornerRadiusXS
        color: Theme.surfaceContainerHigh
        border.width: root.activeFocus ? Theme.outlineWidthFocused : Theme.outlineWidth
        border.color: root.isError ? Theme.error : (root.activeFocus ? Theme.primary : Theme.outlineVariant)
        Behavior on border.color { ColorAnimation { duration: Theme.shortDuration } }
    }
}
