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
    // Done was pressed and the answer of the daemon is not here yet.
    property bool awaitingEnroll: false

    Connections {
        target: InstallerController

        function onRecoveryChanged(): void {
            if (!root.awaitingEnroll || InstallerController.recoveryBusy) {
                return;
            }
            root.awaitingEnroll = false;
            if (InstallerController.recoveryEnrolled) {
                root.advanceRequested();
            }
        }
    }

    // The step's own Done button moves on.
    nextEnabled: false

    Accessible.name: qsTr("Recovery key")

    contentItem: CenteredPage {
        Accessible.name: qsTr("Recovery key")

        maximumContentWidth: root.cardWidth

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
            // A bare error name of the daemon (io.systemd.System) is
            // for the log; it tells a person nothing.
            readonly property string reason: /^[a-z]+(\.[A-Za-z0-9]+)+\.?$/.test(InstallerController.recoveryError)
                ? "" : InstallerController.recoveryError
            text: root.hasKey
                ? (reason.length > 0
                   ? qsTr("The recovery key could not be saved to the disk: %1").arg(reason)
                   : qsTr("The recovery key could not be saved to the disk. Press Done to try again."))
                : (reason.length > 0
                   ? qsTr("No recovery key could be made: %1 Do not continue without one.").arg(reason)
                   : qsTr("No recovery key could be made. Do not continue without one."))
            actions: [
                Kirigami.Action {
                    objectName: "recoveryRetryAction"
                    text: qsTr("Try again")
                    icon.name: "view-refresh-symbolic"
                    visible: !root.hasKey && !InstallerController.recoveryBusy
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

                    // Side by side when both fit, else one above the
                    // other: a row wider than the card pushed the key out
                    // of it at 200 % text.
                    GridLayout {
                        columns: recoveryCopyButton.implicitWidth + recoveryQrButton.implicitWidth
                                 + columnSpacing <= width ? 2 : 1
                        columnSpacing: Kirigami.Units.smallSpacing
                        rowSpacing: Kirigami.Units.smallSpacing

                        Layout.fillWidth: true

                        Button {
                            id: recoveryCopyButton
                            objectName: "recoveryCopyButton"
                            Layout.alignment: Qt.AlignHCenter
                            text: InstallerController.text("recovery_key_copy")
                            icon.name: "edit-copy-symbolic"
                            onClicked: recoveryClip.selectAll(),
                                       recoveryClip.copy(),
                                       recoveryClip.deselect()
                        }

                        Button {
                            id: recoveryQrButton
                            objectName: "recoveryQrButton"
                            Layout.alignment: Qt.AlignHCenter
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

        // A disabled button alone is faint, and does not say what it
        // waits for.
        Label {
            objectName: "recoveryDoneHint"
            visible: root.hasKey && !InstallerController.recoveryAck
            text: qsTr("To continue, tick the box when you have saved the key.")
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap

            Layout.fillWidth: true
        }

        Button {
            objectName: "recoveryDoneButton"
            text: qsTr("Done")
            icon.name: "dialog-ok-apply"
            highlighted: true
            enabled: root.hasKey && InstallerController.recoveryAck && !InstallerController.recoveryBusy

            topPadding: Kirigami.Units.largeSpacing
            bottomPadding: Kirigami.Units.largeSpacing
            leftPadding: Kirigami.Units.gridUnit
            rightPadding: Kirigami.Units.gridUnit

            Layout.alignment: Qt.AlignHCenter

            // Enrol, then go on. The call does not block: the step goes
            // on when the daemon says the key is enrolled. A refused
            // enrolment stays here and shows the reason above.
            onClicked: {
                root.awaitingEnroll = true;
                InstallerController.enrollRecoveryKey();
            }
        }

        // The daemon makes the key, or enrols it: say so while it does.
        RowLayout {
            objectName: "recoveryBusy"
            visible: InstallerController.recoveryBusy
            spacing: Kirigami.Units.largeSpacing

            Layout.alignment: Qt.AlignHCenter

            BusyIndicator {
                running: parent.visible
                implicitWidth: Kirigami.Units.iconSizes.medium
                implicitHeight: Kirigami.Units.iconSizes.medium
            }

            Label {
                text: root.hasKey ? qsTr("Saving the recovery key to the disk…")
                                  : qsTr("Making the recovery key…")
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

    // A popup, outside the scrolled page.
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
