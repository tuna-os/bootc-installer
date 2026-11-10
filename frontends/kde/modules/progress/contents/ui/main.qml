// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    // There is no way forward from here by hand: the wizard advances itself
    // when fisherman exits.
    nextEnabled: false

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            spacing: Kirigami.Units.largeSpacing

            Layout.fillWidth: true

            BusyIndicator {
                // Only until fisherman says something. Once the protocol is
                // flowing the bar below carries the state, and a spinner
                // beside a moving bar says nothing the bar does not.
                running: !InstallerController.installFinished
                    && InstallerController.installStep === 0
                visible: running
                implicitWidth: Kirigami.Units.iconSizes.medium
                implicitHeight: Kirigami.Units.iconSizes.medium
            }

            Label {
                text: InstallerController.text("progress_title") + " " + InstallerController.disk + ". " + InstallerController.text("progress_note")
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            // Asks first (#299): a stray click must not stop a disk write
            // half-way. Only the dialog's own action stops the install. The
            // wizard goes to the done step when the process exits, and that
            // step shows the cancelled page.
            Button {
                objectName: "cancelInstallButton"
                text: qsTr("Cancel")
                icon.name: "dialog-cancel-symbolic"
                visible: InstallerController.installing && !InstallerController.installFinished
                onClicked: cancelDialog.open()
            }

            Kirigami.PromptDialog {
                id: cancelDialog
                objectName: "cancelConfirmDialog"

                title: qsTr("Stop the installation?")
                subtitle: qsTr("The disk %1 is erased already. If you stop now, no system can start from it until you install again.").arg(InstallerController.disk)
                standardButtons: Kirigami.Dialog.NoButton
                customFooterActions: [
                    Kirigami.Action {
                        objectName: "cancelConfirmStop"
                        text: qsTr("Stop the installation")
                        icon.name: "dialog-cancel-symbolic"
                        onTriggered: {
                            cancelDialog.close();
                            InstallerController.cancelInstall();
                        }
                    },
                    Kirigami.Action {
                        objectName: "cancelConfirmKeep"
                        text: qsTr("Keep installing")
                        onTriggered: cancelDialog.close()
                    }
                ]

                // An install that ends by itself leaves nothing to ask about.
                Connections {
                    target: InstallerController
                    function onInstallCompleted(exitCode: int): void {
                        cancelDialog.close();
                    }
                }
            }
        }

        // The install's real position, from fisherman's progress protocol
        // (shared/progress/README.md). Before this the step showed a
        // spinner and a log pane and nothing else for the whole install —
        // docs/PARITY.md gap #2.
        ColumnLayout {
            spacing: Kirigami.Units.smallSpacing

            Layout.fillWidth: true

            ProgressBar {
                id: installBar

                // The capture harness looks this up by name and fails when it
                // is missing or draws nothing (tests/capture.cpp).
                objectName: "installProgressBar"

                // Indeterminate only before the first event arrives, so the
                // step never looks stalled while fisherman starts up.
                indeterminate: InstallerController.installStep === 0
                    && !InstallerController.installFinished
                value: InstallerController.installFraction
                from: 0
                to: 1

                Layout.fillWidth: true

                // Drawn here rather than by the style.
                //
                // With the stock delegates this control laid out at 964x16,
                // visible, opacity 1, value and position both 0.586, range
                // 0..1, not indeterminate, enabled, nothing clipping it --
                // and painted not one pixel. Measured, not guessed: see
                // tests/capture.cpp. It is not the style failing wholesale,
                // because the same org.kde.desktop style paints the Breeze
                // radio indicators, text fields and buttons on the other
                // steps; it is this control's painting path specifically.
                //
                // Two Rectangles in Kirigami theme colours paint under any
                // style and any backend. The control stays a real
                // ProgressBar -- its value, range and semantics are
                // untouched -- so only the groove's appearance changes, and
                // it now follows the colour scheme rather than the widget
                // style. If someone on a real Breeze desktop confirms the
                // native delegates paint there, these can go.
                background: Rectangle {
                    implicitWidth: 200
                    implicitHeight: 6
                    radius: height / 2
                    color: Kirigami.Theme.alternateBackgroundColor
                }

                contentItem: Item {
                    implicitHeight: 6

                    Rectangle {
                        width: installBar.visualPosition * parent.width
                        height: parent.height
                        radius: height / 2
                        color: Kirigami.Theme.highlightColor
                    }
                }
            }

            Label {
                // "Step 5 of 8 — Installing <product>…". The count comes
                // from the event, never a constant: fisherman computes
                // total_steps from the recipe.
                // qsTr(), not i18nc(): nothing in this app sets a
                // KLocalizedContext on the QML engine, so the KDE i18n
                // functions are undefined here. Qt's own are not.
                text: InstallerController.installStep > 0
                    ? (InstallerController.installStepName
                       ? qsTr("Step %1 of %2 — %3").arg(InstallerController.installStep)
                             .arg(InstallerController.installTotalSteps)
                             .arg(InstallerController.installStepName)
                       : qsTr("Step %1 of %2").arg(InstallerController.installStep)
                             .arg(InstallerController.installTotalSteps))
                    : ""
                visible: text !== ""
                color: Kirigami.Theme.disabledTextColor
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }
        }

        Kirigami.Card {
            Layout.fillWidth: true
            Layout.fillHeight: true

            contentItem: ScrollView {
                id: logScroll

                TextArea {
                    id: logView

                    text: InstallerController.log
                    readOnly: true
                    wrapMode: TextEdit.NoWrap
                    font.family: "monospace"
                    background: null

                    // Follow the tail, the way the old QPlainTextEdit did.
                    onTextChanged: logScroll.ScrollBar.vertical.position =
                        Math.max(0, 1 - logScroll.ScrollBar.vertical.size)
                }
            }
        }
    }
}
