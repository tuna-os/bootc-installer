// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    nextEnabled: true

    Accessible.name: qsTr("Done")

    // After a migrate handoff the live session is the installed system:
    // there is nothing to restart.
    readonly property bool takenOver: InstallerController.succeeded
        && InstallerController.sessionKeepsRunning
    // The daemon's reason for a failure, in words (shared/flow failure
    // states device-lost, repart-error, daemon-unreachable).
    readonly property string failureText: {
        switch (InstallerController.failureReason) {
        case "device_lost":
            return qsTr("The disk went away during the installation. Check that it is connected, or choose another disk.");
        case "repart_failed":
            return qsTr("The disk could not be partitioned.");
        case "luks_failed":
            return qsTr("The disk could not be encrypted.");
        case "validation_failed":
            return qsTr("The installer daemon refused these settings. The log names the field.");
        case "daemon_unreachable":
            return qsTr("The installer daemon does not answer.");
        default:
            return "";
        }
    }
    readonly property string failureIcon: InstallerController.cancelled
        ? "dialog-cancel" : "dialog-error"

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

            // Success shows the product's artwork from the branding resolver
            // (assets.complete_image, then the logo) with a themed check as
            // the fallback; a failure keeps the error icon. A cancelled
            // install is neither (#299): the user stopped it.
            Kirigami.Icon {
                objectName: "doneLogo"
                source: InstallerController.succeeded
                    ? (InstallerController.completeImageSource
                       || InstallerController.logoSource
                       || "checkmark")
                    : root.failureIcon
                fallback: InstallerController.succeeded ? "checkmark" : root.failureIcon
                implicitWidth: Kirigami.Units.iconSizes.enormous
                implicitHeight: implicitWidth

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            // "<product> is installed": the one heading on this page. The
            // header shows only the step indicator here (Wizard.heroStep).
            Kirigami.Heading {
                objectName: "doneHeading"
                text: InstallerController.succeeded
                    ? InstallerController.text("done_title")
                    : InstallerController.cancelled
                        ? InstallerController.text("done_cancelled_title")
                        : InstallerController.text("done_failed_title")
                level: 1
                type: Kirigami.Heading.Type.Primary
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            Label {
                objectName: "doneBody"
                text: InstallerController.succeeded
                    ? (root.takenOver
                        ? qsTr("This session is now the installed system. You can close this window.")
                        : InstallerController.text("done_subtitle"))
                    : InstallerController.cancelled
                        ? (InstallerController.diskUnchanged
                            ? qsTr("You stopped the installation. The selected disk was not changed.")
                            : qsTr("You stopped the installation. The selected disk is erased and has no complete system. Start the installer again to install."))
                        : root.failureText.length > 0
                            ? root.failureText
                            : qsTr("The installation did not finish. The log has the details — exit code %1.").arg(InstallerController.exitCode)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            // A failure: whether fisherman changed the disk, and a cleanup
            // that failed or timed out (its `error` event, fisherman#449).
            Label {
                objectName: "doneFailureLines"
                text: InstallerController.failureLines.join("\n\n")
                visible: !InstallerController.succeeded && !InstallerController.cancelled
                    && text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true
            }

            // Installed, restart required: never "verified". Only the new
            // system can check its own start (#269,
            // shared/completion/README.md).
            // The receipt line says what fisherman's `receipt` event set up
            // for that check, and the install id.
            Label {
                objectName: "doneVerification"
                text: InstallerController.receiptLines.join("\n\n")
                visible: InstallerController.succeeded && text.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                opacity: 0.75

                Layout.fillWidth: true
            }

            // store_label -> store_url, on every frontend when the branding
            // sets a store (docs/PARITY.md).
            Label {
                text: "<a href=\"" + InstallerController.storeUrl + "\">" + InstallerController.text("store_label") + "</a>"
                visible: InstallerController.succeeded && InstallerController.storeUrl.length > 0
                textFormat: Text.RichText
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap

                Layout.fillWidth: true

                onLinkActivated: link => Qt.openUrlExternally(link)
            }

            // A first look at the installed system (the GNOME tour step):
            // the selected catalog image's carousel slides. Title and
            // description travel; the artwork does not — the manifest names
            // GNOME GResource paths (resource:///...), which nothing here
            // can resolve, so slides show without it rather than not at all.
            // Hidden without a catalog selection that names slides.
            ColumnLayout {
                id: tourCarousel
                objectName: "tourCarousel"
                visible: InstallerController.succeeded && InstallerController.tourSlides.length > 0
                spacing: Kirigami.Units.smallSpacing

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing

                property int tourIndex: 0
                readonly property var slide: InstallerController.tourSlides[tourIndex] ?? {}
                readonly property string slideTitle: (slide["title"] ?? "") + ""
                readonly property string slideDescription: ((slide["description"] ?? slide["desc"]) ?? "") + ""

                Label {
                    text: qsTr("Take a tour")
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap

                    Layout.fillWidth: true
                }

                Label {
                    text: tourCarousel.slideTitle
                    visible: text.length > 0
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap

                    Layout.fillWidth: true
                }

                Label {
                    text: tourCarousel.slideDescription
                    visible: text.length > 0
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    opacity: 0.8

                    Layout.fillWidth: true
                }

                RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Layout.alignment: Qt.AlignHCenter

                    Button {
                        text: qsTr("Previous")
                        icon.name: "arrow-left-symbolic"
                        enabled: tourCarousel.tourIndex > 0
                        onClicked: tourCarousel.tourIndex--
                    }

                    Label {
                        text: qsTr("%1 of %2").arg(tourCarousel.tourIndex + 1).arg(InstallerController.tourSlides.length)
                        color: Kirigami.Theme.disabledTextColor

                        Layout.leftMargin: Kirigami.Units.smallSpacing
                        Layout.rightMargin: Kirigami.Units.smallSpacing
                    }

                    Button {
                        text: qsTr("Next")
                        icon.name: "arrow-right-symbolic"
                        enabled: tourCarousel.tourIndex < InstallerController.tourSlides.length - 1
                        onClicked: tourCarousel.tourIndex++
                    }
                }

                // A new leaf resets the index: slides from the previous
                // image must not page through the new one's count.
                Connections {
                    target: InstallerController
                    function onCatalogChanged(): void {
                        tourCarousel.tourIndex = 0;
                    }
                }
            }

            // Restart is the primary action after a successful install, the
            // same as on the other frontends; Close stays in the footer.
            Button {
                objectName: "doneRestartButton"
                text: InstallerController.text("done_restart")
                icon.name: "system-reboot-symbolic"
                visible: InstallerController.succeeded && !root.takenOver
                highlighted: true
                // Held until the key is acknowledged (the recovery-key step).
                enabled: !InstallerController.recoveryKeyPending

                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing

                onClicked: InstallerController.reboot()
            }

            // reboot-failed: the daemon refused the restart (an inhibitor,
            // or one already on its way).
            Kirigami.InlineMessage {
                objectName: "doneShutdownError"
                type: Kirigami.MessageType.Error
                visible: InstallerController.shutdownError.length > 0
                text: qsTr("The computer cannot restart now: %1").arg(InstallerController.shutdownError)

                Layout.fillWidth: true
            }

            // After a failure or a cancel: back to the disk step for
            // another try. Close stays in the footer.
            Button {
                objectName: "doneRetryButton"
                text: qsTr("Try again")
                icon.name: "view-refresh-symbolic"
                visible: InstallerController.installFinished && !InstallerController.succeeded
                highlighted: true

                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: Kirigami.Units.largeSpacing

                onClicked: root.retryRequested()
            }

            // The log shown on the previous step dies with this window; this
            // is where the copy on disk is. Hidden when the file could not be
            // opened, rather than pointing at a path that does not exist.
            // The button copies the in-window log for a bug report (the GNOME
            // BootcDialogOutput copy action); the label says where the file
            // is for later.
            Label {
                text: qsTr("Log saved to %1").arg(InstallerController.logPath)
                visible: InstallerController.logPath.length > 0
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                font: Kirigami.Theme.smallFont
                opacity: 0.8

                Layout.fillWidth: true
            }

            Button {
                objectName: "copyLogButton"
                text: qsTr("Copy install log")
                icon.name: "edit-copy-symbolic"
                visible: InstallerController.logPath.length > 0
                onClicked: InstallerController.copyLogToClipboard()

                Layout.alignment: Qt.AlignHCenter
            }

        }
    }
}
