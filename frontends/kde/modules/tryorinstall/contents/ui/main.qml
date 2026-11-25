// SPDX-License-Identifier: GPL-3.0-only

// Try or install (shared/flow/screens.yaml): the first screen. On live
// media, trying ends the wizard and keeps the live session; installing
// moves on. Off live media there is no session to try: the screen then
// introduces the install with the product's welcome copy and one button.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: true

    Accessible.name: qsTr("Welcome")

    // A plain Item, not a ScrollView: this step is short enough never to
    // scroll (see the done step for why that matters).
    contentItem: Item {
        Accessible.name: qsTr("Welcome")

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                objectName: "tryLogo"
                source: InstallerController.welcomeImageSource
                    || InstallerController.logoSource
                    || "system-software-install"
                fallback: "system-software-install"
                implicitWidth: Kirigami.Units.iconSizes.enormous
                implicitHeight: Kirigami.Units.iconSizes.enormous

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            Kirigami.Heading {
                objectName: "tryHeading"
                text: InstallerController.isLive ? InstallerController.productName
                                                 : InstallerController.text("welcome_title")
                level: 1
                type: Kirigami.Heading.Type.Primary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: InstallerController.text("welcome_subtitle")
                visible: text.length > 0 && !InstallerController.isLive
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: InstallerController.isLive
                    ? qsTr("Try %1 without changing this computer, or install it.").arg(InstallerController.productName)
                    : qsTr("This wizard will guide you through installing %1 onto this computer.").arg(InstallerController.productName)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            RowLayout {
                spacing: Kirigami.Units.largeSpacing

                Layout.alignment: Qt.AlignHCenter

                Button {
                    objectName: "tryButton"
                    visible: InstallerController.isLive
                    Accessible.name: qsTr("Try %1").arg(InstallerController.productName)
                    text: qsTr("Try %1").arg(InstallerController.productName)

                    topPadding: Kirigami.Units.largeSpacing
                    bottomPadding: Kirigami.Units.largeSpacing
                    leftPadding: Kirigami.Units.gridUnit
                    rightPadding: Kirigami.Units.gridUnit

                    onClicked: Qt.quit()
                }

                Button {
                    objectName: "installNowButton"
                    Accessible.name: text
                    // Off live media the button carries the product's own
                    // word for leaving the welcome screen (branding copy).
                    text: InstallerController.isLive ? qsTr("Install now")
                                                     : InstallerController.text("welcome_button")
                    icon.name: "arrow-right-symbolic"

                    highlighted: true

                    topPadding: Kirigami.Units.largeSpacing
                    bottomPadding: Kirigami.Units.largeSpacing
                    leftPadding: Kirigami.Units.gridUnit
                    rightPadding: Kirigami.Units.gridUnit

                    onClicked: root.advanceRequested()
                }
            }
        }
    }
}
