// SPDX-License-Identifier: GPL-3.0-only

// Requirements (shared/flow/screens.yaml `requirements`): shown only while
// a gate is unmet. Too little memory or too few CPU cores hold Next until
// the person says to continue anyway. A boot without UEFI has no way on:
// only power off.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: !InstallerController.requirementsBlocking
        || (!InstallerController.requirementsFatal && InstallerController.continueAnyway)

    Accessible.name: qsTr("Requirements")

    contentItem: Item {
        Accessible.name: qsTr("Requirements")

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: InstallerController.requirementsFatal ? "dialog-error" : "dialog-warning"
                implicitWidth: Kirigami.Units.iconSizes.huge
                implicitHeight: Kirigami.Units.iconSizes.huge

                Layout.alignment: Qt.AlignHCenter
            }

            Kirigami.Heading {
                objectName: "requirementsHeading"
                text: InstallerController.requirementsFatal
                    ? qsTr("This computer cannot run the installer")
                    : qsTr("This computer is below the requirements")
                level: 1
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Kirigami.InlineMessage {
                objectName: "requirementsWarning"
                type: InstallerController.requirementsFatal ? Kirigami.MessageType.Error : Kirigami.MessageType.Warning
                visible: text.length > 0
                text: InstallerController.requirementsWarning

                Layout.fillWidth: true
            }

            FormCard.FormCard {
                visible: InstallerController.requirementsBlocking && !InstallerController.requirementsFatal
                maximumWidth: root.cardWidth

                Layout.fillWidth: true

                FormCard.FormCheckDelegate {
                    objectName: "continueAnywayCheck"
                    text: qsTr("Continue anyway")
                    description: qsTr("The installation can be slow or can fail on this computer.")
                    checked: InstallerController.continueAnyway
                    onToggled: InstallerController.continueAnyway = checked
                }
            }

            Button {
                objectName: "powerOffButton"
                text: qsTr("Power off")
                icon.name: "system-shutdown-symbolic"
                onClicked: InstallerController.poweroff()

                Layout.alignment: Qt.AlignHCenter
            }
        }
    }
}
