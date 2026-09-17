// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: true

    // A plain Item, not a ScrollView. These two steps are short enough never to
    // scroll, and inside a ScrollView the content item collapses to its
    // implicit height — which is why the first CI render came out hard against
    // the top of the page with the whole lower half empty. The Control sizes
    // this to the full step rect, so centring on it actually centres.
    contentItem: Item {

        ColumnLayout {
            anchors.centerIn: parent
            width: Math.min(root.cardWidth, parent.width)
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: InstallerController.succeeded ? "checkmark" : "dialog-error"
                implicitWidth: Kirigami.Units.iconSizes.enormous
                implicitHeight: Kirigami.Units.iconSizes.enormous

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.gridUnit
            }

            Kirigami.Heading {
                text: InstallerController.succeeded ? "Installation complete" : "Installation failed"
                level: 1
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                text: InstallerController.succeeded
                    ? InstallerController.productName + " has been installed. Remove the installation media and restart to boot into your new system."
                    : "The installation did not finish. The log above has the details — exit code "
                      + InstallerController.exitCode + "."
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            // The log shown on the previous step dies with this window; this
            // is where the copy on disk is. Hidden when the file could not be
            // opened, rather than pointing at a path that does not exist.
            Label {
                text: "Log saved to " + InstallerController.logPath
                visible: InstallerController.logPath.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                font: Kirigami.Theme.smallFont
                opacity: 0.8

                Layout.fillWidth: true
            }

        }
    }
}
