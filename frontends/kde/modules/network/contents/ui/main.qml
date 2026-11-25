// SPDX-License-Identifier: GPL-3.0-only

// Network (shared/flow/screens.yaml `network`): shown only when the install
// needs a download. Live media and an image in the offline stores skip it.
// The check runs in this frontend; the daemon does not check the network.
// The way to connect is Plasma's own network settings, on the host.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    readonly property bool offline: InstallerController.onlineKnown && !InstallerController.online
    readonly property bool checking: InstallerController.checkingOnline

    // Blocking: no Next while the check says there is no connection.
    nextEnabled: !offline

    Accessible.name: qsTr("Network")

    // Checked again every time the step opens: the cable may be in now.
    function onPageActivated(): void {
        InstallerController.checkConnectivity();
    }

    contentItem: Item {
        Accessible.name: qsTr("Network")

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: root.offline ? "network-offline" : "network-wired-activated"
                fallback: "network-wired"
                implicitWidth: Kirigami.Units.iconSizes.huge
                implicitHeight: Kirigami.Units.iconSizes.huge

                Layout.alignment: Qt.AlignHCenter
            }

            Kirigami.Heading {
                objectName: "networkHeading"
                text: root.offline ? qsTr("No internet connection")
                    : root.checking ? qsTr("Checking the internet connection…")
                    : qsTr("Connected to the internet")
                level: 1
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: root.offline
                    ? qsTr("The selected image needs to be downloaded. Connect this computer to a network, then check again.")
                    : qsTr("The selected image is downloaded during the installation.")
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
            }

            RowLayout {
                spacing: Kirigami.Units.largeSpacing

                Layout.alignment: Qt.AlignHCenter

                Button {
                    objectName: "networkSettingsButton"
                    text: qsTr("Network settings")
                    icon.name: "preferences-system-network-symbolic"
                    onClicked: InstallerController.openNetworkSettings()
                }

                Button {
                    objectName: "networkRecheckButton"
                    text: qsTr("Recheck")
                    icon.name: "view-refresh-symbolic"
                    enabled: !root.checking
                    onClicked: InstallerController.checkConnectivity()
                }
            }
        }
    }
}
