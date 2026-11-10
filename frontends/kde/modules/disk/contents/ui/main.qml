// SPDX-License-Identifier: GPL-3.0-only

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

TunaComponents.SetupModule {
    id: root

    // No disk, no install: Recipe::validationError() rejects an empty disk.
    // With a catalog on screen an image must be chosen too, the way the
    // GNOME step holds its Next until a leaf is checked. Live media hides
    // the catalog (the running system is installed), so nothing is required.
    // fisherman's problem with the filesystem also holds Next: a composefs
    // image on a filesystem without fs-verity is refused at install time,
    // and this is the page that can fix it (#287).
    nextEnabled: InstallerController.disk.length > 0
        && (!InstallerController.hasCatalog || InstallerController.isLive
            || InstallerController.catalogIndex >= 0)
        && InstallerController.filesystemProblem === ""

    // Called by the wizard whenever this step becomes current, so hotplugged
    // media show up. Re-runs `fisherman probe --json`: the disks, their
    // order, size labels and models are fisherman's (shared/probe/README.md).
    function onPageActivated(): void {
        disks.refresh();
    }

    DiskModel {
        id: disks
    }

    contentItem: ScrollView {
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        contentWidth: -1

        ColumnLayout {
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing

            // The wording is the Widgets page's, kept deliberately. tunaOS's
            // screen contract (tests/installer-screens.yaml, vendored into
            // tests/parity_report.h) identifies a disk-selection screen by
            // "choose the disk" and "be installed", and after the rewrite no
            // text on this step said either: run 31143012730 published
            // `"disk": false` — a required screen reported missing — in the
            // same artifact as a screenshot of it. Reword this and that false
            // row comes back.
            //
            // The product name is substituted, so this reads "Choose the disk
            // where Skipjack will be installed." — both keywords survive the
            // substitution because neither one spans it. That is why the
            // sentence keeps the name in the MIDDLE and not at either end.
            Label {
                text: qsTr("Choose the disk where %1 will be installed.").arg(InstallerController.productName)
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.smallSpacing
            }

            Kirigami.InlineMessage {
                type: Kirigami.MessageType.Warning
                visible: true
                position: Kirigami.InlineMessage.Header
                text: qsTr("Everything on the selected disk will be erased.")

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing
            }

            // The image catalog (fisherman's images.json): which OS to
            // install, and the per-image choices that follow from it — the
            // account step, bootloader, filesystem, tour. Hidden on live
            // media, where the running system is installed, and when no
            // manifest is installed. The list is flat, so each row's title
            // is the breadcrumb (every name from the root): a channel name
            // such as "Stable" is not unique (shared/catalog/README.md).
            Label {
                visible: InstallerController.hasCatalog && !InstallerController.isLive
                text: qsTr("Choose what to install.")
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.smallSpacing
            }

            TextField {
                id: catalogSearch
                visible: InstallerController.hasCatalog && !InstallerController.isLive
                objectName: "catalogSearch"
                placeholderText: qsTr("Search images")

                Layout.fillWidth: true
                Layout.maximumWidth: root.cardWidth
                Layout.alignment: Qt.AlignHCenter
            }

            FormCard.FormCard {
                visible: InstallerController.hasCatalog && !InstallerController.isLive
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing

                ButtonGroup {
                    id: catalogGroup
                }

                Repeater {
                    model: InstallerController.catalogNames

                    delegate: FormCard.FormRadioDelegate {
                        required property int index
                        required property string modelData

                        readonly property string imgref: InstallerController.catalogImgrefs[index]
                        readonly property string desc: InstallerController.catalogDescs[index]
                        readonly property string query: catalogSearch.text.trim().toLowerCase()

                        // Group path, description and ref are all searchable,
                        // the way the GNOME step matches its search string.
                        visible: query.length === 0
                            || modelData.toLowerCase().indexOf(query) >= 0
                            || imgref.toLowerCase().indexOf(query) >= 0
                            || desc.toLowerCase().indexOf(query) >= 0

                        ButtonGroup.group: catalogGroup

                        text: modelData
                        description: desc.length > 0 ? desc + "\n" + imgref : imgref
                        checked: InstallerController.catalogIndex === index

                        onToggled: if (checked) {
                            InstallerController.selectCatalogImage(index);
                        }
                    }
                }
            }

            // The filesystem (#287): the selected image's choices, or this
            // frontend's own list for an image that names none. One choice
            // is no question, so the row shows only with more than one.
            // fisherman's problem with the value is shown here and holds
            // Next.
            FormCard.FormCard {
                visible: InstallerController.filesystemChoices.length > 1
                    || InstallerController.filesystemProblem !== ""
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: Kirigami.Units.largeSpacing

                FormCard.FormComboBoxDelegate {
                    objectName: "filesystemCombo"
                    text: qsTr("Filesystem")
                    model: InstallerController.filesystemChoices
                    currentIndex: InstallerController.filesystemChoices.indexOf(InstallerController.filesystem)
                    onActivated: (index) => InstallerController.filesystem = InstallerController.filesystemChoices[index]
                }

                FormCard.FormTextDelegate {
                    objectName: "filesystemProblem"
                    visible: InstallerController.filesystemProblem !== ""
                    text: InstallerController.filesystemProblem
                    textItem.wrapMode: Text.Wrap
                    textItem.color: Kirigami.Theme.negativeTextColor
                }
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth

                Layout.alignment: Qt.AlignHCenter

                Repeater {
                    model: disks

                    delegate: FormCard.FormRadioDelegate {
                        required property string device
                        required property string title
                        required property string subtitle
                        required property bool removable

                        // The model (the path when it is unknown); the
                        // path, fisherman's size label and the bus below.
                        text: title
                        description: subtitle
                        checked: InstallerController.disk === device

                        onToggled: if (checked) {
                            InstallerController.disk = device;
                            InstallerController.diskRemovable = removable;
                        }
                    }
                }
            }

            FormCard.FormCard {
                maximumWidth: root.cardWidth
                visible: disks.count === 0

                Layout.alignment: Qt.AlignHCenter

                FormCard.FormTextDelegate {
                    text: disks.error.length > 0 ? qsTr("Could not detect disks") : qsTr("No disks found")
                    description: disks.error.length > 0
                        ? disks.error
                        : qsTr("Connect a disk of at least 50 GiB to install to.")
                }
            }
        }
    }
}
