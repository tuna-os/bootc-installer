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
        }

        // The install's real position, from fisherman's progress protocol
        // (shared/progress/README.md). Before this the step showed a
        // spinner and a log pane and nothing else for the whole install —
        // docs/PARITY.md gap #2.
        ColumnLayout {
            spacing: Kirigami.Units.smallSpacing

            Layout.fillWidth: true

            ProgressBar {
                // The capture harness looks this up by name and fails when it
                // is missing or draws nothing (tests/capture.cpp). It is an
                // objectName rather than an id because findChild() cannot see
                // QML ids.
                objectName: "installProgressBar"

                // Indeterminate only before the first event arrives, so the
                // step never looks stalled while fisherman starts up.
                indeterminate: InstallerController.installStep === 0
                    && !InstallerController.installFinished
                value: InstallerController.installFraction
                from: 0
                to: 1

                Layout.fillWidth: true
            }

            Label {
                // "Step 5 of 8 — Installing <product>…". The count comes
                // from the event, never a constant: fisherman computes
                // total_steps from the recipe.
                // Plain concatenation, not i18nc(): nothing in this app sets
                // a KLocalizedContext on the QML engine, so i18n functions
                // are undefined here and every other string is built this way.
                text: InstallerController.installStep > 0
                    ? "Step " + InstallerController.installStep
                      + " of " + InstallerController.installTotalSteps
                      + (InstallerController.installStepName
                         ? " — " + InstallerController.installStepName : "")
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
