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
                running: !InstallerController.installFinished
                visible: running
                implicitWidth: Kirigami.Units.iconSizes.medium
                implicitHeight: Kirigami.Units.iconSizes.medium
            }

            Label {
                text: "Installing " + InstallerController.productName + " onto " + InstallerController.disk + ". Do not power off the machine."
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
