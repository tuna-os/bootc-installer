// SPDX-License-Identifier: GPL-3.0-only

// Language (shared/flow/screens.yaml `language`): a searchable list of the
// locales this system has. The pick goes to the installed system: the
// recipe's `locale`, or ConfigureTarget on the daemon backend.

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

    Accessible.name: qsTr("Language")

    contentItem: Item {
        Accessible.name: qsTr("Language")

        ColumnLayout {
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Label {
                objectName: "languageIntro"
                text: qsTr("Choose the language of the installed system.")
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            PickerList {
                objectName: "languagePicker"
                names: InstallerController.languageNames
                ids: InstallerController.languageIds
                currentId: InstallerController.language
                searchLabel: qsTr("Search languages")
                emptyText: qsTr("No language matches the search.")
                onPicked: id => InstallerController.language = id

                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            Kirigami.InlineMessage {
                objectName: "regionProblem"
                type: Kirigami.MessageType.Error
                visible: text.length > 0
                text: InstallerController.regionProblem

                Layout.fillWidth: true
            }
        }
    }
}
