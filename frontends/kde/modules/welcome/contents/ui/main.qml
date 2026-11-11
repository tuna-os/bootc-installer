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

    // The hardware gates (fisherman's system.unmet) and the network gate.
    // A non-UEFI boot has no continue path, like BootcUnsupportedWindow;
    // unmet RAM/CPU hold Next until the override is ticked, like the
    // BootcCpuWindow/BootcRamWindow continue buttons. A failed connectivity
    // check only blocks when the install needs the network (conn_check.py).
    readonly property bool gateBlocked: InstallerController.requirementsBlocking
        && (InstallerController.requirementsFatal || !InstallerController.continueAnyway)
    nextEnabled: !gateBlocked && !networkGate.blocked

    // Rechecked every time the step opens: the cable may have been plugged
    // in while the user was choosing a disk.
    function onPageActivated(): void {
        InstallerController.checkConnectivity();
    }

    contentItem: ScrollView {
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Item {
                // The hero artwork keeps its air when the form below grows:
                // a fixed spacer, not centring, which a ScrollView collapses
                // (the first CI render jammed the welcome text hard against
                // the top for exactly this reason — that step was short).
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit
            }

            // The product's artwork from the branding resolver:
            // assets.welcome_image, then the logo (a theme icon or a file).
            // When neither is set or neither resolves, a full-colour themed
            // installer icon. Not drive-harddisk-symbolic: Breeze draws that
            // at 32 px at most, and scaled to the hero size it came out as a
            // grey blob that read as missing artwork.
            Kirigami.Icon {
                objectName: "welcomeLogo"
                source: InstallerController.welcomeImageSource
                    || InstallerController.logoSource
                    || "system-software-install"
                fallback: "system-software-install"
                implicitWidth: Kirigami.Units.iconSizes.enormous
                implicitHeight: Kirigami.Units.iconSizes.enormous

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.gridUnit
            }

            // Flavour text is branding copy (shared/branding): the product's
            // welcome line and, when it sets one, a subtitle. Nothing here
            // names a product.
            Kirigami.Heading {
                text: InstallerController.text("welcome_title")
                level: 1
                type: Kirigami.Heading.Type.Primary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: InstallerController.text("welcome_subtitle")
                visible: text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: qsTr("This wizard will guide you through installing %1 onto this computer.").arg(InstallerController.productName)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            Label {
                text: qsTr("You will choose a disk and how it should be encrypted. Everything after that is handled by the installer.")
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            // fisherman's minimum requirements (RAM, CPU cores, UEFI). A
            // warning, not a gate — except the cases below.
            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Warning
                visible: text.length > 0
                text: InstallerController.requirementsWarning

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            // The non-fatal gate: unmet RAM/CPU hold Next until the user
            // explicitly continues anyway.
            CheckBox {
                objectName: "continueAnywayCheck"
                visible: InstallerController.requirementsBlocking
                    && !InstallerController.requirementsFatal
                text: qsTr("This computer does not meet the requirements, but install anyway")
                checked: InstallerController.continueAnyway
                onToggled: InstallerController.continueAnyway = checked

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            // The fatal gate: without UEFI there is no install to continue
            // to, only powering off — the BootcUnsupportedWindow path.
            Button {
                objectName: "powerOffButton"
                visible: InstallerController.requirementsFatal
                text: qsTr("Power off")
                icon.name: "system-shutdown-symbolic"
                onClicked: InstallerController.poweroff()

                Layout.alignment: Qt.AlignHCenter
            }

            // Network preflight (the conn_check step): a failed check blocks
            // only while the install needs a download. Live media and images
            // already in the host's offline stores never need it.
            // The message, Retry and the way to the desktop's network
            // settings are NetworkGate's (#301).
            NetworkGate {
                id: networkGate

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            // Region & language. The recipe carries them (`locale`,
            // `keyboard`, `timezone`) and fisherman writes them to the
            // installed system (#292). The confirm step lists them.
            Label {
                text: qsTr("Region & language")
                font.bold: true
                horizontalAlignment: Text.AlignHCenter

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing
            }

            Label {
                objectName: "regionApplied"
                text: qsTr("The installed system uses these settings.")
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            Label {
                objectName: "regionProblem"
                text: InstallerController.regionProblem
                visible: text.length > 0
                color: Kirigami.Theme.negativeTextColor
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter

                FormCard.FormComboBoxDelegate {
                    id: languageCombo
                    text: qsTr("Language")
                    model: InstallerController.languageNames
                    currentIndex: InstallerController.languageIds.indexOf(InstallerController.language)
                    onActivated: (index) => InstallerController.language = InstallerController.languageIds[index]
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormComboBoxDelegate {
                    id: keyboardCombo
                    text: qsTr("Keyboard")
                    model: InstallerController.keyboardLayoutNames
                    currentIndex: InstallerController.keyboardLayoutIds.indexOf(InstallerController.keyboardLayout)
                    onActivated: (index) => InstallerController.keyboardLayout = InstallerController.keyboardLayoutIds[index]
                }

                FormCard.FormDelegateSeparator {}

                FormCard.FormComboBoxDelegate {
                    id: timezoneCombo
                    text: qsTr("Time zone")
                    model: InstallerController.timezones
                    // IANA ids are exact but ugly; the pretty form is what
                    // the row shows, the id is what it stores.
                    displayText: InstallerController.timezoneDisplay(currentValue ?? "")
                    currentIndex: InstallerController.timezones.indexOf(InstallerController.timezone)
                    onActivated: (index) => InstallerController.timezone = InstallerController.timezones[index]
                }
            }
        }
    }
}
