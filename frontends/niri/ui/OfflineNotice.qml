import QtQuick
import QtQuick.Layouts
import "."

// The offline notice (#301): shown while the selected image needs a
// download and the connectivity check says there is no network. It offers
// the desktop's own network tool and a recheck. The wizard owns the state
// and the two actions; this file only draws them.
Rectangle {
    id: notice

    // The check has answered at least once.
    property bool checked: false
    // A check is in progress.
    property bool checking: false
    // Why the network tool did not open, or "".
    property string toolError: ""

    signal recheck()
    signal openSettings()

    radius: Theme.cornerRadiusM
    color: Theme.withAlpha(Theme.warning, 0.12)
    implicitHeight: content.implicitHeight + Theme.spacingM * 2

    Column {
        id: content
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: Theme.spacingM }
        spacing: Theme.spacingS
        RowLayout {
            width: parent.width
            spacing: Theme.spacingM
            StyledText {
                text: notice.checked
                    ? qsTr("This computer is offline, and the selected image needs a download. Connect to a network, then select Recheck.")
                    : qsTr("Checking the network…")
                color: Theme.warning
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            DankButton {
                objectName: "offlineNetworkSettings"
                text: qsTr("Network settings")
                tonal: true
                onClicked: notice.openSettings()
            }
            DankButton {
                objectName: "offlineRecheck"
                text: qsTr("Recheck")
                tonal: true
                enabled: !notice.checking
                onClicked: notice.recheck()
            }
        }
        StyledText {
            text: notice.toolError
            visible: text !== ""
            color: Theme.warning
            font.pixelSize: Theme.fontSizeSmall
            wrapMode: Text.Wrap
            width: parent.width
        }
    }
}
