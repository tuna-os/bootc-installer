// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import org.kde.kirigami as Kirigami

import org.tunaos.installer

Kirigami.AbstractApplicationWindow {
    id: root

    title: InstallerController.productName + " Installer"

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
