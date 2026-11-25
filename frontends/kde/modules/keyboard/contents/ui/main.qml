// SPDX-License-Identifier: GPL-3.0-only

// Keyboard layout (shared/flow/screens.yaml `keyboard`): a searchable list
// of the XKB layouts. The pick goes to the installed system. It does not
// change the keys of this live session, so the step has no test field: a
// field here would test the wrong layout.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: InstallerController.regionProblem === ""

    Accessible.name: qsTr("Keyboard layout")

    contentItem: Item {
        Accessible.name: qsTr("Keyboard layout")

        ColumnLayout {
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Label {
                objectName: "keyboardIntro"
                text: qsTr("Choose the keyboard layout of the installed system. This session keeps its own layout.")
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            PickerList {
                objectName: "keyboardPicker"
                names: InstallerController.keyboardLayoutNames
                ids: InstallerController.keyboardLayoutIds
                currentId: InstallerController.keyboardLayout
                searchLabel: qsTr("Search keyboards")
                emptyText: qsTr("No keyboard layout matches the search.")
                onPicked: id => InstallerController.keyboardLayout = id

                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Error
                visible: text.length > 0
                text: InstallerController.regionProblem

                Layout.fillWidth: true
            }
        }
    }
}
