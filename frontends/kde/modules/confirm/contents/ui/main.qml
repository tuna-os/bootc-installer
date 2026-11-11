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

    // fisherman's hostname rule (`validate --json --partial`) holds Install
    // while it reports a problem, and so does a missing or rejected account:
    // without one the installed system has nobody to sign in as — unless
    // the selected image creates its own first user, in which case the
    // account step was skipped and nothing is required here either.
    // No network for an image that needs a download holds it too (#301):
    // the check runs again here, against the registry of the chosen image.
    nextEnabled: InstallerController.disk.length > 0 && InstallerController.hostnameProblem === ""
        && InstallerController.regionProblem === ""
        && (!InstallerController.needsUserCreation
            || (InstallerController.username.length > 0 && InstallerController.usernameProblem === ""))
        && !networkGate.blocked
        && !InstallerController.sourceBlocked

    function onPageActivated(): void {
        InstallerController.checkConnectivity();
        // What fisherman says about the selected image (#266) and this
        // computer's bootc storage (#267); asked again on each visit.
        InstallerController.checkSource();
    }

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
                text: InstallerController.text(InstallerController.diskRemovable ? "confirm_warning_removable" : "confirm_warning", InstallerController.disk)

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            NetworkGate {
                id: networkGate

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            // fisherman's problem with the hostname, in the copy's words.
            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Error
                visible: text !== ""
                text: InstallerController.hostnameProblem

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            // The product's own lines (a quote, a tagline) from the branding
            // copy; empty in the neutral defaults, so hidden.
            Label {
                text: InstallerController.text("confirm_subtitle")
                visible: text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                font.italic: true

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter

                FormCard.FormTextDelegate {
                    text: qsTr("Target disk")
                    description: InstallerController.disk
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: qsTr("Filesystem")
                    description: InstallerController.btrfsSubvolumes
                        ? qsTr("%1 (with subvolumes)").arg(InstallerController.filesystem)
                        : InstallerController.filesystem
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: qsTr("Encryption")
                    description: InstallerController.encryptionLabel(InstallerController.encryptionType)
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormTextDelegate {
                    text: qsTr("Hostname")
                    description: InstallerController.hostname
                }

                FormCard.FormDelegateSeparator {}

                // The account step's username (and full name, when given);
                // never the password. Hidden when the selected image creates
                // its own first user: the account step was skipped, and an
                // empty row would report a choice nobody made.
                FormCard.FormTextDelegate {
                    objectName: "confirmUsername"
                    visible: InstallerController.needsUserCreation
                    text: qsTr("Username")
                    description: InstallerController.fullname.length > 0
                        ? qsTr("%1 (%2)").arg(InstallerController.username).arg(InstallerController.fullname)
                        : InstallerController.username
                }

                FormCard.FormDelegateSeparator {
                    visible: InstallerController.needsUserCreation
                }

                // The image the recipe installs: the catalog's name for it
                // (product and channel) over the reference.
                FormCard.FormTextDelegate {
                    objectName: "confirmImage"
                    text: qsTr("Image")
                    // Empty on live media: bootc installs the running container,
                    // so the recipe legitimately omits `image`.
                    description: InstallerController.image.length === 0
                        ? qsTr("the running live system")
                        : (InstallerController.imageLabel.length > 0
                           ? InstallerController.imageLabel + "\n" + InstallerController.image
                           : InstallerController.image)
                }

                // The image updates follow, only when it is not the image
                // that is installed (shared/catalog/README.md).
                FormCard.FormDelegateSeparator {
                    visible: updatesRow.visible
                }

                FormCard.FormTextDelegate {
                    id: updatesRow
                    objectName: "confirmTargetImgref"
                    visible: InstallerController.targetImgref.length > 0
                        && InstallerController.targetImgref !== InstallerController.image
                    text: qsTr("Updates come from")
                    description: InstallerController.targetImgref
                }

                // The region choices of the welcome step: the recipe's
                // locale, keyboard and timezone (#292). A row is hidden when
                // the recipe has no such key.
                FormCard.FormDelegateSeparator {
                    visible: languageRow.visible
                }

                FormCard.FormTextDelegate {
                    id: languageRow
                    objectName: "confirmLanguage"
                    visible: InstallerController.localeName.length > 0
                    text: qsTr("Language")
                    description: {
                        const i = InstallerController.languageIds.indexOf(InstallerController.language)
                        const name = i >= 0 ? InstallerController.languageNames[i] : InstallerController.language
                        return qsTr("%1 (%2)").arg(name).arg(InstallerController.localeName)
                    }
                }

                FormCard.FormDelegateSeparator {
                    visible: keyboardRow.visible
                }

                FormCard.FormTextDelegate {
                    id: keyboardRow
                    objectName: "confirmKeyboard"
                    visible: InstallerController.keyboardChosen
                    text: qsTr("Keyboard")
                    description: {
                        const i = InstallerController.keyboardLayoutIds.indexOf(InstallerController.keyboardLayout)
                        return i >= 0 ? InstallerController.keyboardLayoutNames[i] : InstallerController.keyboardLayout
                    }
                }

                FormCard.FormDelegateSeparator {
                    visible: timezoneRow.visible
                }

                FormCard.FormTextDelegate {
                    id: timezoneRow
                    objectName: "confirmTimezone"
                    visible: InstallerController.timezoneChosen
                    text: qsTr("Time zone")
                    description: InstallerController.timezoneDisplay(InstallerController.timezone)
                }
            }
            // The source check: the source of the install, the update
            // reference of the new system, what this computer runs, the
            // check's state and reason, and this computer's bootc storage.
            FormCard.FormHeader {
                visible: InstallerController.sourceVisible
                title: qsTr("Selected image")
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter
            }

            FormCard.FormCard {
                objectName: "confirmSourceCheck"
                visible: InstallerController.sourceVisible
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter

                Repeater {
                    model: InstallerController.sourceRows

                    FormCard.FormTextDelegate {
                        required property var modelData

                        text: modelData.title
                        description: modelData.subtitle
                        textItem.wrapMode: Text.Wrap
                    }
                }
            }

            Label {
                text: InstallerController.text("confirm_body")
                visible: text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing
            }
        }
    }
}
