// TunaOS Niri Installer — Quickshell + Go installer wizard
//
// QML (Quickshell) UI layer over the Go backend in ../installer, which wraps
// fisherman. Backend binary is resolved from $TUNA_BACKEND or PATH
// ("tuna-installer-backend"; the Flatpak installs it at /app/bin).
//
// Visual design target: ../DESIGN.md (scrolling column strip, instrument
// panel). This file is the functional wizard; the strip treatment lands on top.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import "."

ApplicationWindow {
    id: root
    title: root.productName + " Installer"
    width: 800
    height: 600
    visible: true
    color: Theme.surface

    // Every Text here was coloured from a bespoke palette while the CONTROLS
    // kept Qt Quick Controls' light defaults — the install-progress log pane
    // rendered 93% white on a near-black background. Setting the palette once
    // from the DMS tokens fixes every control at once, and keeps the installer
    // looking like the shell it runs inside.
    palette.window: Theme.surface
    palette.windowText: Theme.surfaceText
    palette.base: Theme.surfaceContainerLow
    palette.alternateBase: Theme.surfaceContainer
    palette.text: Theme.surfaceText
    palette.button: Theme.surfaceContainerHigh
    palette.buttonText: Theme.surfaceText
    palette.highlight: Theme.primary
    palette.highlightedText: Theme.primaryText
    palette.placeholderText: Theme.outline
    palette.mid: Theme.surfaceVariant
    palette.dark: Theme.surfaceContainerLowest

    property string backendBin: Quickshell.env("TUNA_BACKEND") || "tuna-installer-backend"

    // Per-variant product name. tunaOS's branding pipeline
    // (build_scripts/90-image-info.sh) computes a PRETTY_NAME per variant and
    // writes it into /etc/os-release, which is why GNOME's welcome screen reads
    // "Welcome to Skipjack". The backend's `detect` reads it back (preferring
    // /run/host/etc/os-release, since this ships as a flatpak) and reports it
    // here, so a Skipjack ISO says Skipjack rather than a hardcoded "TunaOS".
    // "TunaOS" stays the fallback for when os-release yields nothing.
    property string productName: "TunaOS"

    // Wizard state
    property int currentPage: 0 // 0=welcome, 1=disk, 2=encryption, 3=confirm, 4=progress, 5=done

    // Slugs for the readiness stamp. Kept in the same order as currentPage
    // above, and matching the names the other frontends use so the tunaOS
    // screen contract reads one vocabulary rather than five.
    function pageSlug(i) {
        const slugs = ["welcome", "disk", "encryption", "confirm", "installing", "done"]
        return (i >= 0 && i < slugs.length) ? slugs[i] : "unknown"
    }
    // Encryption was previously hardcoded to "none" in the recipe with no UI,
    // so every install came out unencrypted (tuna-os/tunaOS#734).
    property string encType: "none"
    property string passphrase: ""
    property bool hasTpm: false
    property var disks: []
    property var selectedDisk: ({})
    property string hostname: "tunaos"
    property bool installSuccess: false
    property string installLog: ""
    // Recipe JSON awaiting the backend child's stdin channel (fed on
    // Process.started). Kept on the root so the passphrase-bearing recipe
    // never appears in the install command argv (see #22).
    property string pendingRecipe: ""

    // Offline facts from `detect` (spec §4)
    property string liveImage: ""
    property var offlineStores: []
    property string defaultImage: "ghcr.io/tuna-os/albacore:gnome"

    Component.onCompleted: detectProc.running = true

    // Readiness stamp — see ../installer/readiness.go.
    //
    // tunaOS's installer-smoke.yml proves this frontend is up with
    // `flatpak ps`, which answers "is the process alive" rather than "did the
    // user get a window". Those already diverged: the COSMIC leg ran the
    // process with no window ever appearing and the check stayed green.
    //
    // frameSwapped, NOT Component.onCompleted. onCompleted fires when the
    // object tree finishes building, which happens whether or not anything
    // ever reaches the screen — stamping there would reproduce exactly the
    // gap this closes. frameSwapped means Qt swapped a frame to the
    // compositor, which is the strongest claim of the five frontends.
    //
    // Fires on every frame, so `stamped` makes it a one-shot: this spawns a
    // process, and doing that at 60Hz would be its own bug.
    property bool stamped: false
    onFrameSwapped: {
        if (!root.stamped) {
            root.stamped = true
            readinessProc.running = true
        }
    }

    Process {
        id: readinessProc
        command: [root.backendBin, "readiness", root.pageSlug(root.currentPage)]
    }

    Process {
        id: detectProc
        command: [root.backendBin, "detect"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const facts = JSON.parse(text)
                    root.liveImage = facts.liveImage || ""
                    root.hasTpm = facts.hasTpm === true
                    root.offlineStores = facts.offlineStores || []
                    if (facts.productName) root.productName = facts.productName
                } catch (e) { /* detect is best-effort */ }
            }
        }
    }

    Process {
        id: discoverProc
        command: [root.backendBin, "discover-disks"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.disks = JSON.parse(text) } catch (e) { root.disks = [] }
            }
        }
    }

    Process {
        id: installProc
        // The recipe may hold a LUKS passphrase. Feed it over stdin
        // (Process.write) instead of argv: /proc/PID/cmdline is
        // world-readable, so an argv recipe leaks the passphrase to any
        // local user while the backend runs. Quickshell starts the child
        // asynchronously, so write on the started signal — writing before
        // the child's stdin channel is open would drop the recipe.
        stdinEnabled: true
        onStarted: {
            installProc.write(root.pendingRecipe)
            root.pendingRecipe = ""
        }
        stdout: SplitParser {
            onRead: data => root.installLog += data + "\n"
        }
        stderr: SplitParser {
            onRead: data => root.installLog += data + "\n"
        }
        onExited: (code, status) => {
            root.installSuccess = (code === 0)
            root.currentPage = 5
        }
    }

    function startInstall() {
        installLog = ""
        currentPage = 4
        const recipe = {
            disk: "/dev/" + selectedDisk.name,
            filesystem: "xfs",
            encryption: root.encType.endsWith("passphrase")
                ? { type: root.encType, passphrase: root.passphrase }
                : { type: root.encType },
            // Empty image = live-ISO self-install (bootc uses the running container)
            image: liveImage !== "" ? "" : defaultImage,
            hostname: hostname,
            distroID: "tunaos",
            selinuxDisabled: true,
            additionalImageStores: offlineStores
        }
        installProc.command = [root.backendBin, "install"]
        root.pendingRecipe = JSON.stringify(recipe)
        installProc.running = true
        // The recipe is fed over stdin on Process.started — never argv, so
        // the LUKS passphrase does not leak via /proc/PID/cmdline. See
        // tuna-os/tuna-installer-niri#22.
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: currentPage

        // Page 0: Welcome
        Item {
            ColumnLayout {
                spacing: 20
                anchors.centerIn: parent

                Text {
                    // "Welcome to <product>", matching the GNOME installer's
                    // welcome screen. The leading "Welcome" is deliberate: the
                    // screen-parity contract keys the welcome screen off
                    // product-free words, and a bare "<product> Installer"
                    // would match none of them.
                    text: "Welcome to " + root.productName
                    font.pixelSize: 28
                    font.weight: Font.Light
                    color: Theme.primary // --sonar
                    Layout.alignment: Qt.AlignHCenter
                }
                Text {
                    text: root.liveImage !== ""
                        ? "Install this system — no download required."
                        : "This wizard will guide you through installing " + root.productName + " onto your computer."
                    font.pixelSize: 14
                    color: Theme.surfaceVariantText // --fog
                    wrapMode: Text.WordWrap
                    Layout.maximumWidth: 420
                    Layout.alignment: Qt.AlignHCenter
                }
                Button {
                    text: "Get Started"
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 200
                    onClicked: {
                        discoverProc.running = true
                        root.currentPage = 1
                    }
                }
            }
        }

        // Page 1: Disk Selection
        ColumnLayout {
            spacing: 16
            anchors.margins: 40

            Text {
                text: "Destination"
                font.pixelSize: 22
                font.weight: Font.Light
                color: Theme.surfaceVariantText
            }
            Text {
                text: root.selectedDisk.name !== undefined
                    ? "erases everything on " + root.selectedDisk.name
                    : "All data on the selected disk will be erased."
                font.pixelSize: 13
                color: Theme.warning // --catch
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: root.disks
                clip: true
                delegate: ItemDelegate {
                    width: ListView.view.width
                    height: 48
                    text: "/dev/" + modelData.name + "  (" + modelData.size + ")  [" + (modelData.tran || "?") + "]"
                    font.family: "monospace"
                    highlighted: root.selectedDisk.name === modelData.name
                    onClicked: root.selectedDisk = modelData
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Button { text: "Back"; onClicked: root.currentPage = 0 }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Continue"
                    enabled: root.selectedDisk.name !== undefined
                    highlighted: true
                    onClicked: root.currentPage = 2
                }
            }
        }

        // Page 2: Encryption
        //
        // Options mirror tuna-installer-xfce's ENCRYPTION_CHOICES, which is the
        // reference implementation — same values, same wording, so the
        // frontends describe the same choice identically. The tpm2 options are
        // omitted entirely when the backend reports no TPM, rather than shown
        // and then failing at install time.
        ColumnLayout {
            spacing: 12
            anchors.margins: 40

            Text {
                text: "Disk Encryption"
                font.pixelSize: 28; font.bold: true; color: Theme.surfaceText
            }
            Text {
                text: "Encryption protects your files if the disk is lost or stolen. It cannot be turned on later without reinstalling."
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                color: Theme.surfaceVariantText
            }

            ButtonGroup { id: encGroup }

            Repeater {
                model: [
                    { value: "none",                 label: "No encryption",    explain: "Anyone with the disk can read your files." },
                    { value: "luks-passphrase",      label: "Passphrase",       explain: "You'll type it at every boot." },
                    { value: "tpm2-luks",            label: "TPM",              explain: "Unlocks automatically on this hardware." },
                    { value: "tpm2-luks-passphrase", label: "TPM + passphrase", explain: "Automatic unlock, passphrase as fallback." }
                ]
                ColumnLayout {
                    spacing: 2
                    visible: !modelData.value.startsWith("tpm2") || root.hasTpm
                    RadioButton {
                        text: modelData.label
                        ButtonGroup.group: encGroup
                        checked: root.encType === modelData.value
                        onClicked: root.encType = modelData.value
                        palette.windowText: "white"
                    }
                    Text {
                        text: modelData.explain
                        color: Theme.outline; leftPadding: 32
                    }
                }
            }

            // Only meaningful for the *-passphrase modes.
            ColumnLayout {
                visible: root.encType.endsWith("passphrase")
                spacing: 6
                Layout.leftMargin: 32
                TextField {
                    id: passField
                    placeholderText: "Enter passphrase"
                    echoMode: TextInput.Password
                    Layout.preferredWidth: 320
                    onTextChanged: root.passphrase = text
                }
                TextField {
                    id: passConfirm
                    placeholderText: "Confirm passphrase"
                    echoMode: TextInput.Password
                    Layout.preferredWidth: 320
                }
                Text {
                    id: passError
                    color: Theme.error
                    visible: text !== ""
                }
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Button { text: "Back"; onClicked: root.currentPage = 1 }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Continue"
                    onClicked: {
                        // fisherman rejects a *-passphrase type with an empty
                        // passphrase, but that only surfaces mid-install; catch
                        // it here where it can still be corrected.
                        if (root.encType.endsWith("passphrase")) {
                            if (passField.text === "") {
                                passError.text = "Enter a passphrase."
                                return
                            }
                            if (passField.text !== passConfirm.text) {
                                passError.text = "Passphrases do not match."
                                return
                            }
                        }
                        passError.text = ""
                        root.passphrase = passField.text
                        root.currentPage = 3
                    }
                }
            }
        }

        // Page 3: Confirm
        ColumnLayout {
            spacing: 12
            anchors.margins: 40

            Text {
                text: "Confirm Installation"
                font.pixelSize: 22
                font.weight: Font.Light
                color: Theme.surfaceVariantText
            }
            GridLayout {
                columns: 2
                columnSpacing: 24
                rowSpacing: 8
                Text { text: "Target Disk:"; font.bold: true; color: Theme.surfaceVariantText }
                Text {
                    text: root.selectedDisk.name ? "/dev/" + root.selectedDisk.name : "—"
                    font.family: "monospace"; color: Theme.surfaceText
                }
                Text { text: "Filesystem:"; font.bold: true; color: Theme.surfaceVariantText }
                Text { text: "xfs"; font.family: "monospace"; color: Theme.surfaceText }
                Text { text: "Encryption:"; font.bold: true; color: Theme.surfaceVariantText }
                Text { text: root.encType; font.family: "monospace"; color: Theme.surfaceText }
                Text { text: "Hostname:"; font.bold: true; color: Theme.surfaceVariantText }
                TextField {
                    text: root.hostname
                    onTextChanged: root.hostname = text
                    font.family: "monospace"
                }
                Text { text: "Image:"; font.bold: true; color: Theme.surfaceVariantText }
                Text {
                    text: root.liveImage !== ""
                        ? root.liveImage + "  (this system, no download)"
                        : root.defaultImage
                    color: Theme.surfaceVariantText; font.pixelSize: 12; font.family: "monospace"
                }
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                Button { text: "Back"; onClicked: root.currentPage = 2 }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Install"
                    highlighted: true
                    onClicked: root.startInstall()
                }
            }
        }

        // Page 4: Install Progress
        ColumnLayout {
            spacing: 12
            anchors.margins: 40

            Text {
                text: "Installing…"
                font.pixelSize: 22
                font.weight: Font.Light
                color: Theme.surfaceVariantText
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                TextArea {
                    text: root.installLog === "" ? "Starting…" : root.installLog
                    font.family: "monospace"
                    font.pixelSize: 11
                    readOnly: true
                    wrapMode: TextEdit.Wrap
                }
            }
        }

        // Page 5: Done
        Item {
            ColumnLayout {
                spacing: 20
                anchors.centerIn: parent

                Text {
                    text: root.installSuccess ? "✓ Installation Complete" : "✗ Installation Failed"
                    font.pixelSize: 28
                    font.weight: Font.Light
                    color: root.installSuccess ? Theme.primary : Theme.warning
                    Layout.alignment: Qt.AlignHCenter
                }
                Text {
                    text: root.installSuccess
                        ? "Remove the installation media and restart your computer."
                        : "Check the installation log above for details."
                    font.pixelSize: 14
                    color: Theme.surfaceVariantText
                    Layout.alignment: Qt.AlignHCenter
                }
                Button {
                    text: "Close"
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 200
                    onClicked: Qt.quit()
                }
            }
        }
    }
}
