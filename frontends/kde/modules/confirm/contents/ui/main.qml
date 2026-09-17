// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: InstallerController.disk.length > 0

    contentItem: ScrollView {
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Warning
                visible: true
                position: Kirigami.InlineMessage.Header
                // "begins" is deliberately avoided: the screen contract
                // matches a welcome screen on the keyword "begin", so that word
                // here credited a welcome screen off the confirm page in run
                // 31143012730 — and would keep crediting one if the welcome
                // step were ever removed. Same sentence, one word different.
                text: "Selecting Install erases " + InstallerController.disk + " and writes " + InstallerController.productName + " to it."

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter

                FormCard.FormTextDelegate {
                    text: "Target disk"
                    description: InstallerController.disk
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: "Filesystem"
                    description: InstallerController.filesystem
                        + (InstallerController.btrfsSubvolumes ? " (with subvolumes)" : "")
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: "Encryption"
                    description: InstallerController.encryptionLabel(InstallerController.encryptionType)
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: "Hostname"
                    description: InstallerController.hostname
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: "Image"
                    // Empty on live media: bootc installs the running container,
                    // so the recipe legitimately omits `image`.
                    description: InstallerController.image.length > 0
                        ? InstallerController.image
                        : "the running live system"
                }
            }
        }
    }
}
