// SPDX-License-Identifier: GPL-3.0-only

// Disclaimer (shared/flow/screens.yaml `prerelease`): shown when
// os-release calls this a pre-release or an experiment. Informational:
// Next is never held here.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: true

    Accessible.name: qsTr("Disclaimer")

    // A plain Item, not a ScrollView: this step is short enough never to
    // scroll (see the done step for why that matters).
    contentItem: Item {
        Accessible.name: qsTr("Disclaimer")

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                objectName: "prereleaseIcon"
                source: "dialog-warning"
                implicitWidth: Kirigami.Units.iconSizes.enormous
                implicitHeight: Kirigami.Units.iconSizes.enormous

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            Kirigami.Heading {
                objectName: "prereleaseHeading"
                text: qsTr("Disclaimer")
                level: 1
                type: Kirigami.Heading.Type.Primary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: InstallerController.experimentText.length > 0
                    ? InstallerController.experimentText
                    : qsTr("This copy of %1 is a pre-release. It may break, and its behaviour may change before the final release.").arg(InstallerController.productName)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }
        }
    }
}
