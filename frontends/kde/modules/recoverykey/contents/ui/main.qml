// SPDX-License-Identifier: GPL-3.0-only

// Recovery key (shared/flow/screens.yaml `recovery-key`): its own step
// after the install of an encrypted disk. The key is a text label whose
// accessible name is the key itself (the test contract matches it by
// shape). A button opens the key as a QR code. Done stays off until the
// person says the key is saved; on the daemon backend Done also enrols the
// key (io.systemd.CryptEnroll.Enroll). Without a key the step offers only
// a retry: it never goes on with none (recovery-key-failed).
//
// The key stays in memory for this step. It reaches no log.

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    readonly property bool hasKey: InstallerController.recoveryKey.length > 0

    // The step's own Done button moves on.
    nextEnabled: false

    Accessible.name: qsTr("Recovery key")

    contentItem: Item {
        Accessible.name: qsTr("Recovery key")

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: "dialog-password"
                fallback: "document-encrypt"
                implicitWidth: Kirigami.Units.iconSizes.huge
                implicitHeight: Kirigami.Units.iconSizes.huge

                Layout.alignment: Qt.AlignHCenter
            }

            Kirigami.Heading {
                objectName: "recoveryHeading"
                text: InstallerController.text("recovery_key_title")
                level: 1
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: InstallerController.text("recovery_key_body")
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            // No key, or the key was not enrolled: say why and offer a retry.
            Kirigami.InlineMessage {
                objectName: "recoveryError"
                type: Kirigami.MessageType.Error
                visible: InstallerController.recoveryError.length > 0
                text: root.hasKey
                    ? qsTr("The recovery key could not be saved to the disk: %1").arg(InstallerController.recoveryError)
                    : qsTr("No recovery key could be made: %1 Do not continue without one.").arg(InstallerController.recoveryError)
                actions: [
                    Kirigami.Action {
                        objectName: "recoveryRetryAction"
                        text: qsTr("Try again")
                        icon.name: "view-refresh-symbolic"
                        visible: !root.hasKey
                        onTriggered: InstallerController.makeRecoveryKey()
                    }
                ]

                Layout.fillWidth: true
            }

            FormCard.FormCard {
                objectName: "recoveryPanel"
                visible: root.hasKey
                maximumWidth: root.cardWidth

                Layout.fillWidth: true

                FormCard.AbstractFormDelegate {
                    background: null
                    focusPolicy: Qt.NoFocus

                    contentItem: ColumnLayout {
                        spacing: Kirigami.Units.smallSpacing

                        // A label, not a field: the key is read, not edited.
                        // Its accessible name is the key (shared/flow, test
                        // contract rule 3).
                        Kirigami.SelectableLabel {
                            objectName: "recoveryKeyLabel"
                            text: InstallerController.recoveryKey
                            font.family: Kirigami.Theme.fixedWidthFont.family
                            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.15
                            horizontalAlignment: Text.AlignHCenter
                            // Breaks after a hyphen, so a group of the
                            // key stays whole.
                            wrapMode: Text.Wrap
                            Accessible.name: InstallerController.recoveryKey

                            Layout.fillWidth: true
                        }

                        RowLayout {
                            spacing: Kirigami.Units.smallSpacing

                            Layout.alignment: Qt.AlignHCenter

                            Button {
                                objectName: "recoveryCopyButton"
                                text: InstallerController.text("recovery_key_copy")
                                icon.name: "edit-copy-symbolic"
                                onClicked: recoveryClip.selectAll(),
                                           recoveryClip.copy(),
                                           recoveryClip.deselect()
                            }

                            Button {
                                objectName: "recoveryQrButton"
                                text: qsTr("Show QR Code for Recovery Key")
                                icon.name: "view-barcode-qr"
                                enabled: InstallerController.recoveryQrRows.length > 0
                                onClicked: qrDialog.open()
                            }
                        }
                    }
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormCheckDelegate {
                    objectName: "recoveryAckCheck"
                    text: InstallerController.text("recovery_key_ack")
                    checked: InstallerController.recoveryAck
                    onToggled: InstallerController.recoveryAck = checked
                }
            }

            Button {
                objectName: "recoveryDoneButton"
                text: qsTr("Done")
                icon.name: "dialog-ok-apply"
                highlighted: true
                enabled: root.hasKey && InstallerController.recoveryAck

                topPadding: Kirigami.Units.largeSpacing
                bottomPadding: Kirigami.Units.largeSpacing
                leftPadding: Kirigami.Units.gridUnit
                rightPadding: Kirigami.Units.gridUnit

                Layout.alignment: Qt.AlignHCenter

                // Enrol, then go on. A refused enrolment stays here and
                // shows the reason above.
                onClicked: if (InstallerController.enrollRecoveryKey()) {
                    root.advanceRequested();
                }
            }

            // QtQuick has no clipboard object; a hidden TextEdit is the
            // standard way to reach one.
            TextEdit {
                id: recoveryClip
                visible: false
                text: InstallerController.recoveryKey
            }
        }

        Kirigami.Dialog {
            id: qrDialog
            objectName: "recoveryQrDialog"

            title: qsTr("Recovery key")
            standardButtons: Kirigami.Dialog.Close
            padding: Kirigami.Units.largeSpacing

            // Black on white whatever the colour scheme, with the quiet
            // zone a scanner needs: a QR code is not a themed element.
            Rectangle {
                id: qrPlate

                readonly property var rows: InstallerController.recoveryQrRows
                readonly property int modules: rows.length
                readonly property int cell: Math.max(2, Math.floor(Kirigami.Units.gridUnit * 14 / Math.max(1, modules + 8)))

                objectName: "recoveryQr"
                implicitWidth: cell * (modules + 8)
                implicitHeight: implicitWidth
                color: "white"

                Accessible.role: Accessible.Graphic
                Accessible.name: qsTr("QR code of the recovery key")

                Column {
                    x: qrPlate.cell * 4
                    y: qrPlate.cell * 4

                    Repeater {
                        model: qrPlate.rows

                        delegate: Row {
                            id: qrRow

                            required property string modelData

                            Repeater {
                                model: qrRow.modelData.length

                                delegate: Rectangle {
                                    required property int index

                                    width: qrPlate.cell
                                    height: qrPlate.cell
                                    color: qrRow.modelData.charAt(index) === "1" ? "black" : "white"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
