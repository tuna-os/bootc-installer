import QtQuick

// Line-oriented reader. The installer appends each `read` to its log.
QtObject {
    signal read(string data)
    function feed(line) { read(line) }
}
