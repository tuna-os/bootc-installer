// SPDX-License-Identifier: GPL-3.0-only

// Existing data found (shared/flow/screens.yaml `wipe-or-free`): the chosen
// disk holds data with room to spare. Free space keeps what is there;
// erasing takes the whole disk. When the free space cannot fit the install
// the choice is gone: Install erases, with a countdown on the button.
// Skipped when the disk is empty — and on the recipe backend, which keeps
// its erase behaviour.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    Accessible.name: qsTr("Existing data found")
    readonly property bool forced: InstallerController.selectedDiskForceErase
    // A method, read again when the disk changes.
    readonly property string systems: InstallerController.disk.length > 0
        ? InstallerController.selectedDiskOperatingSystems().join(", ") : ""
    readonly property string freeSpace: InstallerController.selectedDiskFreeSpace
    property int eraseCountdown: 0


    contentItem: ScrollView {
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                objectName: "wipeHeading"
                text: qsTr("Existing data found")
                level: 1
                type: Kirigami.Heading.Type.Primary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            Label {
                text: root.systems.length > 0
                    ? qsTr("%1 is already on %2.").arg(root.systems).arg(InstallerController.disk)
                    : qsTr("%1 already holds data.").arg(InstallerController.disk)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            Label {
                visible: root.freeSpace.length > 0
                text: qsTr("%1 free.").arg(root.freeSpace)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            Kirigami.InlineMessage {
                visible: root.forced
                type: Kirigami.MessageType.Warning
                text: qsTr("This disk cannot keep its data: the free space is too small, or its partition table cannot stay. Installing erases the whole disk.")

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            Button {
                objectName: "freeSpaceButton"
                visible: !root.forced
                text: qsTr("Install to Free Space")
                icon.name: "arrow-right-symbolic"

                highlighted: true

                topPadding: Kirigami.Units.largeSpacing
                bottomPadding: Kirigami.Units.largeSpacing
                leftPadding: Kirigami.Units.gridUnit
                rightPadding: Kirigami.Units.gridUnit

                onClicked: {
                    InstallerController.installMode = "free_space";
                    root.advanceRequested();
                }

                Layout.alignment: Qt.AlignHCenter
            }

            Button {
                objectName: "eraseDiskButton"
                visible: !root.forced
                text: qsTr("Erase and Install")
                icon.name: "edit-delete-symbolic"

                topPadding: Kirigami.Units.largeSpacing
                bottomPadding: Kirigami.Units.largeSpacing
                leftPadding: Kirigami.Units.gridUnit
                rightPadding: Kirigami.Units.gridUnit

                onClicked: {
                    InstallerController.installMode = "erase";
                    root.advanceRequested();
                }

                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.smallSpacing
            }

            // Forced erase: no choice, and the destructive button counts
            // down first, the way the GNOME forced-erase dialog does.
            Button {
                objectName: "forcedEraseButton"
                visible: root.forced
                enabled: eraseCountdown <= 0
                text: eraseCountdown > 0
                    ? qsTr("Erase and Install (%1)").arg(eraseCountdown)
                    : qsTr("Erase and Install")
                icon.name: "edit-delete-symbolic"

                topPadding: Kirigami.Units.largeSpacing
                bottomPadding: Kirigami.Units.largeSpacing
                leftPadding: Kirigami.Units.gridUnit
                rightPadding: Kirigami.Units.gridUnit

                onClicked: {
                    InstallerController.installMode = "erase";
                    root.advanceRequested();
                }

                Layout.alignment: Qt.AlignHCenter
            }

            Timer {
                id: eraseTimer
                interval: 1000
                repeat: true
                running: root.forced && eraseCountdown > 0
                onTriggered: eraseCountdown--
            }
        }
    }

    // Restart the countdown every time the step opens. No backend work here:
    // activation only resets page state.
    function onPageActivated(): void {
        eraseCountdown = root.forced ? 3 : 0;
    }
}
