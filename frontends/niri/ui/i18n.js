.pragma library

// The Qt catalog for the locale (#300). Quickshell installs no translator,
// so installer.qml calls createCatalog() once: it creates a Catalog of the
// TunaInstaller.Translations module (../translations/catalog.h), which
// loads ../translations/tuna-installer-niri_<lang>.qm next to `url`'s
// directory and retranslates every qsTr() binding.
//
// The module is created from a string, not imported, so the wizard still
// loads where it is not installed (the screenshot harness, the wasm
// preview, a bare `quickshell ui/installer.qml`): there is then no
// catalog, and the text stays English.
function createCatalog(parent, url) {
    try {
        return Qt.createQmlObject("import TunaInstaller.Translations\nCatalog {}", parent, url)
    } catch (e) {
        return null
    }
}
