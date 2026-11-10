// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

import org.tunaos.installer

Kirigami.AbstractApplicationWindow {
    id: root

    // Leaving mid-install kills it: the wrapper is fisherman's parent, and
    // fisherman exits when its parent dies. Mirrors BootcWindow's exit
    // dialog ("Exit Installer? Any progress will be lost."), which likewise
    // terminates the install on the Exit response. The dialog only appears
    // while an install is actually running — closing from any earlier step
    // loses nothing, the disk is untouched until Install.
    onClosing: (close) => {
        if (InstallerController.installing) {
            close.accepted = false;
            exitDialog.open();
        }
    }

    Kirigami.Dialog {
        id: exitDialog
        title: qsTr("Exit installer?")
        showCloseButton: false
        contentItem: Label {
            text: qsTr("The installation will be stopped. Any progress will be lost.")
            wrapMode: Text.Wrap
        }
        footer: RowLayout {
            Item {
                Layout.fillWidth: true
            }
            Button {
                text: qsTr("Keep installing")
                onClicked: exitDialog.close()
            }
            Button {
                text: qsTr("Exit")
                onClicked: {
                    InstallerController.cancelInstall();
                    exitDialog.close();
                    Qt.quit();
                }
            }
        }
    }

    title: qsTr("%1 Installer").arg(InstallerController.productName)

    width: Kirigami.Units.gridUnit * 50
    height: Kirigami.Units.gridUnit * 36
    minimumWidth: Kirigami.Units.gridUnit * 34
    minimumHeight: Kirigami.Units.gridUnit * 26

    // Forwarded for the screenshot harness, which drives the wizard from C++.
    // Navigation only — see Wizard.goToStep().
    function goToStep(index: int): void {
        wizard.goToStep(index);
    }
    readonly property alias stepCount: wizard.stepCount
    readonly property alias currentStepId: wizard.currentStepId

    Wizard {
        id: wizard
        anchors.fill: parent
    }
}
