// SPDX-License-Identifier: GPL-3.0-only

// Time zone (shared/flow/screens.yaml `timezone`): a searchable list of the
// IANA zones, and the one privacy choice of the first start, location
// services. The daemon hears about that switch only when the person moved
// it (ConfigureTarget `privacy.locationServices`); its default is off.

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

    Accessible.name: qsTr("Time zone")

    readonly property var zoneNames: InstallerController.timezones.map(zone => InstallerController.timezoneDisplay(zone))

    contentItem: Item {
        Accessible.name: qsTr("Time zone")

        ColumnLayout {
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Label {
                objectName: "timezoneIntro"
                text: qsTr("Choose the time zone of the installed system.")
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            PickerList {
                objectName: "timezonePicker"
                names: root.zoneNames
                ids: InstallerController.timezones
                currentId: InstallerController.timezone
                searchLabel: qsTr("Search time zones")
                emptyText: qsTr("No time zone matches the search.")
                onPicked: id => InstallerController.timezone = id

                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            // Daemon backend only: the recipe has no field for it.
            FormCard.FormCard {
                visible: InstallerController.daemonBackend
                maximumWidth: root.cardWidth

                Layout.fillWidth: true

                FormCard.FormSwitchDelegate {
                    objectName: "locationServicesSwitch"
                    text: qsTr("Location services")
                    description: qsTr("Let apps of the installed system find the location of this computer. Off unless you turn it on.")
                    checked: InstallerController.locationServices
                    onToggled: InstallerController.locationServices = checked
                }
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
