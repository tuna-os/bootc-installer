pragma Singleton
import QtQuick

// Stub of the Quickshell singleton, for running ui/installer.qml under a plain
// Qt Quick runtime. Only env() is used by the installer.
QtObject {
    function env(name) {
        return ""   // fall through to the QML's own default
    }
}
