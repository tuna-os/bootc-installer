// SPDX-License-Identifier: GPL-3.0-only

// Intel RST (shared/flow/screens.yaml `rst`): shown when fishermand's Probe
// reports remapped NVMe, before the disk list. It warns and continues —
// gnome-setup does not block here either. Skipped when nothing is remapped.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: true

    Accessible.name: qsTr("Intel RST")
    Accessible.role: Accessible.Alert

    contentItem: ScrollView {
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                objectName: "rstHeading"
                text: qsTr("Intel RST is on")
                level: 1
                type: Kirigami.Heading.Type.Primary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Warning
                visible: true
                text: qsTr("This computer uses Intel RST (RAID mode), which can hide disks. If the disk that you want is not in the list of the next step, switch the storage to AHCI in the firmware settings.")

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            Label {
                visible: InstallerController.rstAffectedDisks.length > 0
                text: qsTr("Hidden disks: %1").arg(InstallerController.rstAffectedDisks.join(", "))
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            Button {
                objectName: "rstPowerOffButton"
                text: qsTr("Power off")
                icon.name: "system-shutdown-symbolic"
                onClicked: InstallerController.poweroff()

                Layout.alignment: Qt.AlignHCenter
            }
        }
    }
}
