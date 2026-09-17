// Disk encryption choice.
//
// The recipe has carried encryption.type and encryption.passphrase since the
// beginning and fisherman honours both, but nothing ever set them until this
// step existed (tunaOS#734). The wording deliberately matches
// tuna-installer-xfce, the reference implementation.
//
// SPDX-License-Identifier: GPL-3.0-only

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

    readonly property bool needsPassphrase: InstallerController.encryptionType.endsWith("passphrase")
    readonly property bool passphrasesMatch: passphraseField.text.length > 0
        && passphraseField.text === confirmField.text

    // Recipe::validationError() rejects a *-passphrase type with an empty or
    // mismatched passphrase; catching it here means the user finds out while
    // they can still fix it, instead of as an opaque failure mid-install.
    nextEnabled: !needsPassphrase || passphrasesMatch

    // Keep the recipe in step with the fields, but never leave a passphrase in
    // it for a type that does not take one.
    function commitPassphrase(): void {
        InstallerController.passphrase = (needsPassphrase && passphrasesMatch) ? passphraseField.text : "";
    }

    contentItem: ScrollView {
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Label {
                text: "Encryption protects your files if the disk is lost or stolen. It cannot be turned on later without reinstalling."
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter

                FormCard.FormRadioDelegate {
                    text: "No encryption"
                    description: "Anyone with the disk can read your files."
                    checked: InstallerController.encryptionType === "none"
                    onToggled: if (checked) {
                        InstallerController.encryptionType = "none";
                    }
                }

                FormCard.FormRadioDelegate {
                    text: "Passphrase"
                    description: "You'll type it at every boot."
                    checked: InstallerController.encryptionType === "luks-passphrase"
                    onToggled: if (checked) {
                        InstallerController.encryptionType = "luks-passphrase";
                        root.commitPassphrase();
                    }
                }

                // TPM options are hidden, not disabled, on a machine without a
                // TPM: offering them there only fails at install time.
                FormCard.FormRadioDelegate {
                    visible: InstallerController.hasTpm
                    text: "TPM"
                    description: "Unlocks automatically on this hardware."
                    checked: InstallerController.encryptionType === "tpm2-luks"
                    onToggled: if (checked) {
                        InstallerController.encryptionType = "tpm2-luks";
                    }
                }

                FormCard.FormRadioDelegate {
                    visible: InstallerController.hasTpm
                    text: "TPM + passphrase"
                    description: "Automatic unlock, passphrase as fallback."
                    checked: InstallerController.encryptionType === "tpm2-luks-passphrase"
                    onToggled: if (checked) {
                        InstallerController.encryptionType = "tpm2-luks-passphrase";
                        root.commitPassphrase();
                    }
                }
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth
                visible: root.needsPassphrase

                Layout.topMargin: Kirigami.Units.largeSpacing
                Layout.alignment: Qt.AlignHCenter

                FormCard.FormPasswordFieldDelegate {
                    id: passphraseField

                    label: "Passphrase"

                    onTextChanged: {
                        showPasswordQuality = text.length > 0;
                        root.commitPassphrase();
                    }
                }

                FormCard.FormPasswordFieldDelegate {
                    id: confirmField

                    label: "Confirm passphrase"

                    status: (text.length > 0 && text !== passphraseField.text)
                        ? Kirigami.MessageType.Error : Kirigami.MessageType.Information
                    statusMessage: (text.length > 0 && text !== passphraseField.text)
                        ? "Passphrases do not match." : ""

                    onTextChanged: root.commitPassphrase()
                }
            }
        }
    }
}
