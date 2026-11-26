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

    // Never larger than the screen. With large text (gridUnit grows with
    // the font) the minimum alone was larger than a 1024x600 screen. The
    // pages scroll, so a small window loses no content.
    // Before the window is on a screen the available size can be 0: then
    // the grid unit size applies.
    function fitScreen(size: real, available: real): real {
        return available > 0 ? Math.min(size, available) : size;
    }
    width: fitScreen(Kirigami.Units.gridUnit * 50, Screen.desktopAvailableWidth)
    height: fitScreen(Kirigami.Units.gridUnit * 36, Screen.desktopAvailableHeight)
    minimumWidth: fitScreen(Kirigami.Units.gridUnit * 34, Screen.desktopAvailableWidth)
    minimumHeight: fitScreen(Kirigami.Units.gridUnit * 26, Screen.desktopAvailableHeight)

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
