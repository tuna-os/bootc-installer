import QtQuick

// Collects a whole stream, then signals once. Mirrors Quickshell.Io's API
// surface as used by the installer: a `text` property and streamFinished.
QtObject {
    property string text: ""
    signal streamFinished()
    function feed(data) { text = data; streamFinished() }
}
