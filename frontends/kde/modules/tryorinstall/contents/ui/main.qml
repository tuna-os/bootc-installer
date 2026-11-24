// SPDX-License-Identifier: GPL-3.0-only

// Try or install (shared/flow/screens.yaml): the first screen on live
// media. Trying ends the wizard and keeps the live session; installing
// moves on. Never shown off live media (Wizard skips it there).

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
                source: InstallerController.logoSource || "system-software-install"
                fallback: "system-software-install"
                implicitWidth: Kirigami.Units.iconSizes.enormous
                implicitHeight: Kirigami.Units.iconSizes.enormous

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            Kirigami.Heading {
                objectName: "tryHeading"
                text: InstallerController.productName
                level: 1
                type: Kirigami.Heading.Type.Primary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: qsTr("Try %1 without changing this computer, or install it.").arg(InstallerController.productName)
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
                    Accessible.name: qsTr("Install now")
                    text: qsTr("Install now")
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
