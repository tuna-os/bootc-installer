// A step page that is centred when it fits and scrolls when it does not:
// large text or a 1024x600 screen. In a plain ScrollView the content takes
// its implicit height and sits at the top of the page, so the page here is
// at least as high as the view.
//
// SPDX-License-Identifier: GPL-3.0-only

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

ScrollView {
    id: scroller

    // The children go into a centred column.
    default property alias content: column.data
    property real maximumContentWidth: availableWidth

    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    contentWidth: availableWidth
    contentHeight: page.height
    clip: true
    background: null

    Item {
        id: page

        width: scroller.availableWidth
        height: Math.max(scroller.availableHeight, column.implicitHeight + 2 * Kirigami.Units.largeSpacing)

        ColumnLayout {
            id: column

            anchors.centerIn: parent
            width: Math.min(scroller.maximumContentWidth, parent.width - 2 * Kirigami.Units.largeSpacing)
            spacing: Kirigami.Units.largeSpacing
        }
    }
}
