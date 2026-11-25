// A search field over a list with one current row: the language, keyboard
// and time zone steps (shared/flow/screens.yaml).
//
// Plasma's own first-run and System Settings pickers have this shape: a
// Kirigami.SearchField, a framed list, a check mark on the current row. The
// match is a plain "contains" on the lower-cased name, so it works for a
// name in any script.
//
// SPDX-License-Identifier: GPL-3.0-only

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

ColumnLayout {
    id: picker

    // What the rows show, and the id each row stores. Same length.
    property var names: []
    property var ids: []
    property string currentId: ""
    // The accessible name and the placeholder of the search field.
    property string searchLabel: ""
    property string emptyText: ""

    signal picked(string id)

    readonly property var matches: {
        const needle = search.text.trim().toLocaleLowerCase();
        const out = [];
        for (let i = 0; i < names.length; i++) {
            const name = String(names[i]);
            if (needle === "" || name.toLocaleLowerCase().indexOf(needle) >= 0
                || String(ids[i]).toLocaleLowerCase().indexOf(needle) >= 0) {
                out.push(i);
            }
        }
        return out;
    }

    spacing: Kirigami.Units.smallSpacing

    Kirigami.SearchField {
        id: search
        objectName: "pickerSearch"
        placeholderText: picker.searchLabel
        Accessible.name: picker.searchLabel

        Layout.fillWidth: true
    }

    // What applies when nobody picks a row: the row with the check mark, or
    // the image's own value when the list does not have the session's.
    Label {
        objectName: "pickerKeeps"
        visible: picker.ids.length > 0 && picker.ids.indexOf(picker.currentId) < 0
        text: qsTr("Nothing is chosen: the installed system keeps its own setting.")
        wrapMode: Text.Wrap

        Layout.fillWidth: true
    }

    ScrollView {
        id: scroll

        Layout.fillWidth: true
        Layout.fillHeight: true

        // The frame of a System Settings list.
        Component.onCompleted: if (background) {
            background.visible = true;
        }

        ListView {
            id: list
            objectName: "pickerList"
            clip: true
            model: picker.matches
            currentIndex: picker.matches.indexOf(picker.ids.indexOf(picker.currentId))
            keyNavigationEnabled: true
            activeFocusOnTab: true

            Accessible.role: Accessible.List
            Accessible.name: picker.searchLabel

            delegate: ItemDelegate {
                id: row

                required property int modelData
                required property int index

                readonly property bool current: picker.ids[modelData] === picker.currentId

                width: ListView.view.width
                text: picker.names[modelData]
                highlighted: current
                icon.name: current ? "checkmark-symbolic" : ""

                Accessible.role: Accessible.ListItem
                Accessible.name: text
                Accessible.selected: current

                onClicked: picker.picked(picker.ids[modelData])
            }

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.gridUnit * 4
                visible: list.count === 0
                icon.name: "edit-none-symbolic"
                text: picker.emptyText
            }

            // Show the current row when the step opens. Not when the list is
            // made: each step is made at the start, with no height, and the
            // row of "English (US)" was then far below the fold of a list
            // that looked as if nothing was chosen.
            function showCurrent(): void {
                forceLayout();
                positionViewAtIndex(Math.max(0, currentIndex), ListView.Center);
            }

            onVisibleChanged: if (visible) {
                Qt.callLater(showCurrent);
            }
            onHeightChanged: if (visible && !moving) {
                Qt.callLater(showCurrent);
            }
        }
    }
}
