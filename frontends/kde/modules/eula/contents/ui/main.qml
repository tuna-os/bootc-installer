// SPDX-License-Identifier: GPL-3.0-only

// Terms of use (shared/flow/screens.yaml `eula`): the agreement sections
// the image ships. Skipped when there is no EULA file. Next stays off
// until the box is ticked.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: InstallerController.eulaAvailable && InstallerController.eulaAccepted

    Accessible.name: qsTr("Terms of use")

    contentItem: ScrollView {
        // Content taller than the page must not paint over the footer.
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                objectName: "eulaHeading"
                text: qsTr("Terms of use")
                level: 1
                type: Kirigami.Heading.Type.Primary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            // The file exists but cannot be shown (shared/flow eula-unreadable):
            // no terms to accept, only powering off.
            Kirigami.InlineMessage {
                visible: InstallerController.eulaError.length > 0
                type: Kirigami.MessageType.Error
                text: InstallerController.eulaError

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            Button {
                objectName: "eulaPowerOffButton"
                visible: InstallerController.eulaError.length > 0
                text: qsTr("Power off")
                icon.name: "system-shutdown-symbolic"
                onClicked: InstallerController.poweroff()

                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing
            }

            Repeater {
                model: InstallerController.eulaAvailable ? InstallerController.eulaSections : []

                delegate: ColumnLayout {
                    required property var modelData

                    spacing: Kirigami.Units.smallSpacing

                    Layout.fillWidth: true
                    Layout.maximumWidth: root.cardWidth
                    Layout.alignment: Qt.AlignHCenter
                    Layout.bottomMargin: Kirigami.Units.largeSpacing

                    Label {
                        visible: modelData.heading.length > 0
                        text: modelData.heading
                        font.bold: true
                        wrapMode: Text.Wrap

                        Layout.fillWidth: true
                    }

                    Repeater {
                        model: modelData.blocks

                        delegate: Label {
                            required property var modelData

                            text: modelData.kind === "p" ? modelData.text
                                : modelData.kind === "ol"
                                    ? modelData.items.map((item, i) => (i + 1) + ". " + item).join("\n")
                                    : modelData.items.map((item) => "• " + item).join("\n")
                            wrapMode: Text.Wrap

                            Layout.fillWidth: true
                            Layout.topMargin: Kirigami.Units.smallSpacing
                        }
                    }
                }
            }

            CheckBox {
                objectName: "eulaAcceptCheck"
                Accessible.name: qsTr("I have read and accept the Terms of Use")
                visible: InstallerController.eulaAvailable
                text: qsTr("I have read and accept the Terms of Use")
                checked: InstallerController.eulaAccepted
                onToggled: InstallerController.eulaAccepted = checked

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing
            }
        }
    }
}
