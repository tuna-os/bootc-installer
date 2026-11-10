// The network gate (#301): what the welcome and confirm steps show while the
// connectivity check runs and when it failed.
//
// A failed check blocks only while the install needs a download: live media
// and an image already in the host's offline stores need none. The check
// tries the registry of the selected image first (InstallerController), so
// the confirm step asks again once an image is chosen.
//
// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.tunaos.installer

ColumnLayout {
    id: gate

    // The step holds Next (or Install) while this is true.
    readonly property bool blocked: InstallerController.onlineKnown
        && !InstallerController.online && InstallerController.needsNetwork

    spacing: Kirigami.Units.smallSpacing
    visible: checking.visible || offline.visible

    Kirigami.InlineMessage {
        id: checking
        type: Kirigami.MessageType.Information
        visible: InstallerController.checkingOnline && InstallerController.needsNetwork
        text: qsTr("Checking the internet connection…")

        Layout.fillWidth: true
    }

    Kirigami.InlineMessage {
        id: offline
        objectName: "networkBlockedMessage"
        type: Kirigami.MessageType.Error
        visible: gate.blocked
        text: qsTr("No internet connection was found, and the selected image needs to be downloaded. Connect and retry.")
        actions: [
            // The desktop's own tool, on the host: this installer has no
            // Wi-Fi page of its own.
            Kirigami.Action {
                objectName: "networkSettingsAction"
                text: qsTr("Network settings")
                icon.name: "preferences-system-network-symbolic"
                onTriggered: InstallerController.openNetworkSettings()
            },
            Kirigami.Action {
                text: qsTr("Retry")
                icon.name: "view-refresh-symbolic"
                onTriggered: InstallerController.checkConnectivity()
            }
        ]

        Layout.fillWidth: true
    }
}
