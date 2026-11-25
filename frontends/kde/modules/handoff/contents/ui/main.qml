// SPDX-License-Identifier: GPL-3.0-only

// Handoff (shared/flow/screens.yaml `handoff`): how the installed system
// takes over. The mode is the daemon's decision, read from Probe: this step
// only words it and calls Handoff with no mode.
//
//   migrate      the live session becomes the installed system; nothing
//                restarts, and the session's files stay
//   soft_reboot  the desktop restarts into the copy; the session's files
//                do not carry over
//   reboot       a full restart
//
// Continue starts it. Not now goes to the done step, which still offers
// the restart. A refused handoff shows the reason, a restart and a close.

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

    readonly property string mode: InstallerController.handoffMode
    readonly property bool started: InstallerController.handoffState === "started"
    readonly property bool failed: InstallerController.handoffState === "failed"

    // Continue and Not now are the step's own buttons.
    nextEnabled: false

    Accessible.name: qsTr("Handoff")

    contentItem: Item {
        Accessible.name: qsTr("Handoff")

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: root.mode === "migrate" ? "system-switch-user" : "system-reboot"
                fallback: "system-reboot"
                implicitWidth: Kirigami.Units.iconSizes.huge
                implicitHeight: Kirigami.Units.iconSizes.huge

                Layout.alignment: Qt.AlignHCenter
            }

            Kirigami.Heading {
                objectName: "handoffHeading"
                text: root.mode === "migrate" ? qsTr("Switch to the installed system")
                    : root.mode === "soft_reboot" ? qsTr("Restart into the installed system")
                    : qsTr("Restart the computer")
                level: 1
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            // What carries over, said plainly for each mode.
            Label {
                objectName: "handoffBody"
                text: root.mode === "migrate"
                    ? qsTr("This session becomes the installed system. Nothing restarts. The files and settings of this session stay.")
                    : root.mode === "soft_reboot"
                        ? qsTr("The desktop restarts into the installed system. The computer does not go through its firmware. The files and settings of this session do not carry over.")
                        : qsTr("The computer restarts into the installed system. The files and settings of this session do not carry over. Remove the install medium when the screen goes dark.")
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                objectName: "handoffFirstBoot"
                visible: InstallerController.firstBootTool.length > 0
                text: qsTr("Plasma asks for your user account when the installed system starts for the first time.")
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
            }

            Kirigami.InlineMessage {
                objectName: "handoffError"
                type: Kirigami.MessageType.Error
                visible: root.failed
                text: qsTr("The handoff did not start: %1").arg(InstallerController.handoffError)
                actions: [
                    Kirigami.Action {
                        objectName: "handoffRestartAction"
                        text: InstallerController.text("done_restart")
                        icon.name: "system-reboot-symbolic"
                        onTriggered: InstallerController.reboot()
                    },
                    Kirigami.Action {
                        objectName: "handoffCloseAction"
                        text: qsTr("Close")
                        icon.name: "window-close-symbolic"
                        onTriggered: root.advanceRequested()
                    }
                ]

                Layout.fillWidth: true
            }

            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Error
                visible: InstallerController.shutdownError.length > 0
                text: qsTr("The computer cannot restart now: %1").arg(InstallerController.shutdownError)

                Layout.fillWidth: true
            }

            // The restart is on its way: nothing more to press.
            RowLayout {
                visible: root.started && !InstallerController.sessionKeepsRunning
                spacing: Kirigami.Units.largeSpacing

                Layout.alignment: Qt.AlignHCenter

                BusyIndicator {
                    running: parent.visible
                    implicitWidth: Kirigami.Units.iconSizes.medium
                    implicitHeight: Kirigami.Units.iconSizes.medium
                }

                Label {
                    objectName: "handoffStarted"
                    text: qsTr("Restarting…")
                }
            }

            RowLayout {
                visible: !root.started
                spacing: Kirigami.Units.largeSpacing

                Layout.alignment: Qt.AlignHCenter

                Button {
                    objectName: "handoffNotNowButton"
                    text: qsTr("Not now")

                    topPadding: Kirigami.Units.largeSpacing
                    bottomPadding: Kirigami.Units.largeSpacing
                    leftPadding: Kirigami.Units.gridUnit
                    rightPadding: Kirigami.Units.gridUnit

                    onClicked: root.advanceRequested()
                }

                Button {
                    objectName: "handoffContinueButton"
                    text: qsTr("Continue")
                    icon.name: "arrow-right-symbolic"
                    highlighted: true
                    enabled: !root.failed

                    topPadding: Kirigami.Units.largeSpacing
                    bottomPadding: Kirigami.Units.largeSpacing
                    leftPadding: Kirigami.Units.gridUnit
                    rightPadding: Kirigami.Units.gridUnit

                    // A migrate handoff leaves the session running: go on to
                    // the done step. A restart leaves this step on screen
                    // until the system goes down.
                    onClicked: if (InstallerController.handoff() && InstallerController.sessionKeepsRunning) {
                        root.advanceRequested();
                    }
                }
            }
        }
    }
}
