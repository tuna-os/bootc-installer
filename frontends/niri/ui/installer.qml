// Niri installer — Quickshell + Go installer wizard
//
// QML (Quickshell) UI layer over the Go backend in ../installer, which wraps
// fisherman. Backend binary is resolved from $TUNA_BACKEND or PATH
// ("tuna-installer-backend"; the Flatpak installs it at /app/bin).
//
// Visual design: DankMaterialShell (../DESIGN.md). Every surface, control and
// type size comes from Theme.qml, which mirrors DMS's Style.qml tokens, and
// the controls are the DMS widget set (DankButton, DankCard, DankListItem,
// DankTextField, StyledText) rebuilt on plain Qt Quick so the installer draws
// the same inside the DMS session and under the docs capture harness.

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
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSizeMedium

    // Qt Quick Controls that are not one of the Dank widgets (the log
    // ScrollView) still pick up the DMS palette.
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

    // Product identity from the backend's `detect` (shared/branding/README.md:
    // branding.json first, os-release second, neutral last). The QML never
    // names a product; before detect answers it shows the neutral name.
    property var branding: ({})
    readonly property string productName: branding.name || "Linux"
    readonly property string storeUrl: branding.storeUrl || ""

    // Flavour text (shared/branding copy keys) with {name}/{disk} filled in.
    // Neutral until detect delivers the branding; never a product literal.
    function text(key, values) {
        const copy = root.branding.copy || {}
        let line = copy[key] !== undefined ? copy[key] : ({
            welcome_title: "Welcome to {name}", welcome_subtitle: "",
            welcome_install: "Install {name}",
            welcome_button: "Get started", confirm_title: "Confirm installation",
            confirm_subtitle: "", confirm_body: "",
            confirm_warning: "Everything on {disk} will be erased. This cannot be undone.",
            confirm_button: "Install", progress_title: "Installing {name}…",
            progress_note: "Do not power off the computer.",
            done_title: "{name} is installed",
            done_subtitle: "Remove the installation media and restart the computer.",
            done_restart: "Restart now", done_failed_title: "Installation failed",
            store_label: "Visit the store"
        })[key] || ""
        line = line.split("{name}").join(root.productName)
        for (const k in (values || {}))
            line = line.split("{" + k + "}").join(values[k])
        return line
    }

    // Wizard state
    property int currentPage: 0 // 0=welcome, 1=disk, 2=encryption, 3=confirm, 4=progress, 5=done
    readonly property var pageNames: ["Welcome", "Disk", "Encryption", "Confirm", "Installing", "Done"]

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
    property string hostname: branding.defaultHostname || "linux"
    property bool installSuccess: false
    property string installLog: ""
    // The determinate bar is driven by fisherman's newline-delimited JSON
    // progress protocol (shared/progress/README.md).
    //
    // This used to be `/^\[(\d+)\/(\d+)\]/` against a fixed nine steps.
    // fisherman has never emitted that prefix — it writes JSON on stdout and
    // nothing else — so the bar stayed at zero and the caption read
    // "Starting…" for the whole of every install. The step count was wrong
    // independently: fisherman computes total_steps from the recipe (8,
    // adjusted for manual layout, LUKS, TPM2 enrolment and a separate /var
    // disk), so nine was never right either.
    //
    // installFraction, not step/total: "Installing OS" alone is 87% of a cold
    // install and five other steps are 0%, so a bar advanced one-nth per step
    // sits near empty for the whole visible install and then jumps.
    property int installStep: 0
    property int installSteps: 0
    property real installFraction: 0
    property string installStepName: ""
    // Parser context carried across lines, for substep interpolation.
    property int installCumulativePct: 0
    property int installWeightPct: 0
    // Recipe JSON awaiting the backend child's stdin channel (fed on
    // Process.started). Kept on the root so the passphrase-bearing recipe
    // never appears in the install command argv (see #22).
    property string pendingRecipe: ""

    // Offline facts from `detect` (spec §4)
    property string liveImage: ""
    property var offlineStores: []
    // The image installed off a live ISO: branding.json's default_image.
    // Empty means the backend refuses ("image is required") rather than
    // installing somebody else's product.
    readonly property string defaultImage: branding.defaultImage || ""

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
                    if (facts.branding) root.branding = facts.branding
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
            onRead: data => root.appendLog(data)
        }
        stderr: SplitParser {
            onRead: data => root.appendLog(data)
        }
        onExited: (code, status) => {
            root.installSuccess = (code === 0)
            root.currentPage = 5
        }
    }

    // One fisherman event, or a plain stderr line. Returns the text to show;
    // the protocol is machine-readable and this pane is not, so events are
    // rendered rather than dumped as JSON.
    function renderEvent(event) {
        switch (event.type) {
        case "step":
            return "[" + event.step + "/" + event.total_steps + "] " + (event.step_name || "")
        case "substep":
        case "info":
            return event.message ? "  " + event.message : ""
        case "complete":
            return event.message || "Installation complete"
        case "error":
            return "ERROR: " + (event.message || "")
        case "recovery_key":
            // Niri has no recovery-key screen (docs/PARITY.md), so this is
            // the only place the user can read a key they cannot recover
            // later. Hiding it here would lose it outright.
            return "Recovery key: " + (event.key || "")
        }
        return ""
    }

    function appendLog(line) {
        let event = null
        if (line.charAt(0) === "{") {
            try { event = JSON.parse(line) } catch (e) { event = null }
        }
        if (event === null || typeof event !== "object") {
            installLog += line + "\n"
            return
        }

        const shown = renderEvent(event)
        if (shown !== "")
            installLog += shown + "\n"

        if (event.type === "step") {
            installStep = event.step
            installSteps = event.total_steps
            installStepName = event.step_name || ""
            installCumulativePct = event.cumulative_pct || 0
            installWeightPct = event.weight_pct || 0
            installFraction = installCumulativePct / 100
        } else if (event.type === "substep") {
            // Inside the long image pull, interpolate across layers so the
            // bar keeps moving for the 87% of the install that step covers.
            const m = /Pulling image: layer (\d+)\/(\d+)/.exec(event.message || "")
            if (m && installWeightPct > 0) {
                const sub = parseInt(m[1]) / parseInt(m[2])
                installFraction = Math.min(
                    (installCumulativePct + sub * installWeightPct) / 100, 1)
            }
        } else if (event.type === "complete") {
            // cumulative_pct only ever reaches 99; `complete` is what fills
            // the bar.
            installFraction = 1
        }
    }

    // Restart from the done page: the backend runs `systemctl reboot` on the
    // host (through flatpak-spawn when sandboxed), the same path the other
    // frontends use.
    Process {
        id: rebootProc
        command: [root.backendBin, "reboot"]
    }

    function startInstall() {
        installLog = ""
        installStep = 0
        installSteps = 0
        installFraction = 0
        installStepName = ""
        installCumulativePct = 0
        installWeightPct = 0
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
            distroID: root.branding.id || "linux",
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

    // ── Keyboard: Enter advances, Shift+Enter goes back (the hint bar says so) ──
    function advance() {
        switch (currentPage) {
        case 0: discoverProc.running = true; currentPage = 1; break
        case 1: if (selectedDisk.name !== undefined) currentPage = 2; break
        case 2: encryptionPage.next(); break
        case 3: if (selectedDisk.name !== undefined) startInstall(); break
        }
    }
    function back() {
        if (currentPage >= 1 && currentPage <= 3) currentPage -= 1
    }
    Shortcut {
        sequence: "Return"
        enabled: !passField.activeFocus && !passConfirm.activeFocus && !hostField.activeFocus
        onActivated: root.advance()
    }
    Shortcut { sequence: "Shift+Return"; onActivated: root.back() }

    // ── Layout: DMS top bar, page area, hint bar ─────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingXL
        spacing: Theme.spacingL

        // Top bar (DMS bar look): step counter left, step dots right.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingM
            StyledText {
                text: "Step " + (root.currentPage + 1) + " of " + root.pageNames.length + " · " + root.pageNames[root.currentPage]
                color: Theme.surfaceVariantText
                font.pixelSize: Theme.fontSizeSmall
                font.weight: Theme.fontWeightMedium
            }
            Item { Layout.fillWidth: true }
            Row {
                spacing: Theme.spacingS
                Repeater {
                    model: root.pageNames.length
                    Rectangle {
                        required property int index
                        width: index === root.currentPage ? 24 : 8
                        height: 8
                        radius: 4
                        color: index <= root.currentPage ? Theme.primary : Theme.surfaceContainerHighest
                        Behavior on width { NumberAnimation { duration: Theme.mediumDuration; easing.type: Theme.standardEasing } }
                        Behavior on color { ColorAnimation { duration: Theme.mediumDuration } }
                    }
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.currentPage

            // Page 0: Welcome
            Item {
                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width, 520)
                    spacing: Theme.spacingL

                    // The product logo (branding.logo, a path) in a
                    // primaryContainer disc; a glyph otherwise.
                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        width: 96; height: 96; radius: 48
                        color: Theme.primaryContainer
                        Image {
                            anchors.centerIn: parent
                            width: 56; height: 56
                            source: (root.branding.logo || "").startsWith("/") ? "file://" + root.branding.logo : ""
                            visible: source != ""
                            fillMode: Image.PreserveAspectFit
                        }
                        StyledText {
                            anchors.centerIn: parent
                            text: "⬢"
                            font.pixelSize: 40
                            color: Theme.primaryContainerText
                            visible: !(root.branding.logo || "").startsWith("/")
                        }
                    }
                    StyledText {
                        // "Welcome to <product>", matching the other frontends'
                        // welcome screen: the screen-parity contract keys the
                        // welcome screen off product-free words.
                        text: root.text("welcome_title")
                        font.pixelSize: Theme.fontSizeXXLarge
                        font.weight: Theme.fontWeightMedium
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                    }
                    StyledText {
                        text: root.text("welcome_subtitle")
                        visible: text !== ""
                        font.pixelSize: Theme.fontSizeLarge
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                    }
                    StyledText {
                        text: root.liveImage !== ""
                            ? "Install this system — no download required."
                            : "This wizard will guide you through installing " + root.productName + " onto your computer."
                        color: Theme.surfaceVariantText
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                    }
                    DankButton {
                        text: root.text("welcome_button")
                        buttonHeight: Theme.buttonHeightM
                        Layout.alignment: Qt.AlignHCenter
                        Layout.topMargin: Theme.spacingS
                        onClicked: root.advance()
                    }
                }
            }

            // Page 1: Disk selection — a grouped list of DankListItems.
            ColumnLayout {
                spacing: Theme.spacingM

                StyledText {
                    text: "Destination"
                    font.pixelSize: Theme.fontSizeXLarge
                    font.weight: Theme.fontWeightMedium
                }
                StyledText {
                    text: root.text("confirm_warning", { disk: root.selectedDisk.name !== undefined
                        ? "/dev/" + root.selectedDisk.name : "the selected disk" })
                    color: Theme.warning
                    Layout.fillWidth: true
                }

                ListView {
                    id: diskList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: root.disks
                    clip: true
                    spacing: Theme.groupedListGap
                    delegate: DankListItem {
                        required property var modelData
                        required property int index
                        width: diskList.width
                        firstInGroup: index === 0
                        lastInGroup: index === diskList.count - 1
                        primaryText: (modelData.model ? modelData.model + "  ·  " : "") + "/dev/" + modelData.name
                        secondaryText: (modelData.size || "?") + "  ·  " + (modelData.tran || "unknown bus")
                        isSelected: root.selectedDisk.name === modelData.name
                        onClicked: root.selectedDisk = modelData
                    }
                    StyledText {
                        anchors.centerIn: parent
                        visible: diskList.count === 0
                        text: "Scanning for disks…"
                        color: Theme.surfaceVariantText
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    DankButton { text: "Back"; tonal: true; onClicked: root.back() }
                    Item { Layout.fillWidth: true }
                    DankButton {
                        text: "Continue"
                        enabled: root.selectedDisk.name !== undefined
                        onClicked: root.advance()
                    }
                }
            }

            // Page 2: Encryption — a grouped list of choices, a card of fields.
            //
            // Options mirror tuna-installer-xfce's ENCRYPTION_CHOICES, which is
            // the reference implementation — same values, same wording, so the
            // frontends describe the same choice identically. The tpm2 options
            // are omitted entirely when the backend reports no TPM, rather than
            // shown and then failing at install time.
            ColumnLayout {
                id: encryptionPage
                spacing: Theme.spacingM

                function next() {
                    // fisherman rejects a *-passphrase type with an empty
                    // passphrase, but that only surfaces mid-install; catch it
                    // here where it can still be corrected.
                    if (root.encType.endsWith("passphrase")) {
                        if (passField.text === "") { passError.text = "Enter a passphrase."; return }
                        if (passField.text !== passConfirm.text) { passError.text = "Passphrases do not match."; return }
                    }
                    passError.text = ""
                    root.passphrase = passField.text
                    root.currentPage = 3
                }

                StyledText {
                    text: "Disk encryption"
                    font.pixelSize: Theme.fontSizeXLarge
                    font.weight: Theme.fontWeightMedium
                }
                StyledText {
                    text: "Encryption protects your files if the disk is lost or stolen. It cannot be turned on later without reinstalling."
                    color: Theme.surfaceVariantText
                    Layout.fillWidth: true
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.groupedListGap
                    Repeater {
                        model: [
                            { value: "none",                 label: "No encryption",    explain: "Anyone with the disk can read your files." },
                            { value: "luks-passphrase",      label: "Passphrase",       explain: "You'll type it at every boot." },
                            { value: "tpm2-luks",            label: "TPM",              explain: "Unlocks automatically on this hardware." },
                            { value: "tpm2-luks-passphrase", label: "TPM + passphrase", explain: "Automatic unlock, passphrase as fallback." }
                        ]
                        DankListItem {
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true
                            visible: !modelData.value.startsWith("tpm2") || root.hasTpm
                            firstInGroup: index === 0
                            lastInGroup: index === (root.hasTpm ? 3 : 1)
                            primaryText: modelData.label
                            secondaryText: modelData.explain
                            isSelected: root.encType === modelData.value
                            onClicked: root.encType = modelData.value
                        }
                    }
                }

                // Only meaningful for the *-passphrase modes.
                DankCard {
                    Layout.fillWidth: true
                    visible: root.encType.endsWith("passphrase")
                    title: "Passphrase"
                    Column {
                        width: parent.width
                        spacing: Theme.spacingS
                        DankTextField {
                            id: passField
                            placeholderText: "Enter passphrase"
                            echoMode: TextInput.Password
                            width: Math.min(parent.width, 360)
                            onTextChanged: root.passphrase = text
                        }
                        DankTextField {
                            id: passConfirm
                            placeholderText: "Confirm passphrase"
                            echoMode: TextInput.Password
                            width: Math.min(parent.width, 360)
                            isError: passError.text !== ""
                        }
                        StyledText {
                            id: passError
                            color: Theme.error
                            visible: text !== ""
                            font.pixelSize: Theme.fontSizeSmall
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.fillWidth: true
                    DankButton { text: "Back"; tonal: true; onClicked: root.back() }
                    Item { Layout.fillWidth: true }
                    DankButton { text: "Continue"; onClicked: encryptionPage.next() }
                }
            }

            // Page 3: Confirm — the summary on a card, the product's own lines
            // around it, Install in the error tone (it erases a disk).
            ColumnLayout {
                spacing: Theme.spacingM

                StyledText {
                    text: root.text("confirm_title")
                    font.pixelSize: Theme.fontSizeXLarge
                    font.weight: Theme.fontWeightMedium
                }
                StyledText {
                    text: root.text("confirm_subtitle")
                    visible: text !== ""
                    color: Theme.surfaceVariantText
                    font.italic: true
                    Layout.fillWidth: true
                }
                Rectangle {
                    Layout.fillWidth: true
                    radius: Theme.cornerRadiusM
                    color: Theme.withAlpha(Theme.warning, 0.12)
                    implicitHeight: warnText.implicitHeight + Theme.spacingM * 2
                    StyledText {
                        id: warnText
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: Theme.spacingM }
                        text: "⚠  " + root.text("confirm_warning", { disk: root.selectedDisk.name ? "/dev/" + root.selectedDisk.name : "the selected disk" })
                        color: Theme.warning
                    }
                }

                DankCard {
                    Layout.fillWidth: true
                    title: "Summary"
                    GridLayout {
                        width: parent.width
                        columns: 2
                        columnSpacing: Theme.spacingXL
                        rowSpacing: Theme.spacingS
                        StyledText { text: "Target disk"; color: Theme.surfaceVariantText }
                        StyledText { text: root.selectedDisk.name ? "/dev/" + root.selectedDisk.name : "—"; isMonospace: true }
                        StyledText { text: "Filesystem"; color: Theme.surfaceVariantText }
                        StyledText { text: "xfs"; isMonospace: true }
                        StyledText { text: "Encryption"; color: Theme.surfaceVariantText }
                        StyledText { text: root.encType; isMonospace: true }
                        StyledText { text: "Hostname"; color: Theme.surfaceVariantText }
                        DankTextField {
                            id: hostField
                            text: root.hostname
                            onTextEdited: root.hostname = text  // not onTextChanged: that fires at load and would pin the branding default
                            font.family: Theme.monoFontFamily
                            implicitWidth: 260
                        }
                        StyledText { text: "Image"; color: Theme.surfaceVariantText }
                        StyledText {
                            text: root.liveImage !== ""
                                ? root.liveImage + "  (this system, no download)"
                                : (root.defaultImage || "—")
                            isMonospace: true
                            font.pixelSize: Theme.fontSizeSmall
                            Layout.fillWidth: true
                        }
                    }
                }

                StyledText {
                    text: root.text("confirm_body")
                    visible: text !== ""
                    color: Theme.surfaceVariantText
                    horizontalAlignment: Text.AlignHCenter
                    Layout.fillWidth: true
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.fillWidth: true
                    DankButton { text: "Back"; tonal: true; onClicked: root.back() }
                    Item { Layout.fillWidth: true }
                    DankButton {
                        text: root.text("confirm_button")
                        destructive: true
                        enabled: root.selectedDisk.name !== undefined
                        onClicked: root.startInstall()
                    }
                }
            }

            // Page 4: Install progress — determinate bar from the [n/9] lines,
            // the log on a card.
            ColumnLayout {
                spacing: Theme.spacingM

                StyledText {
                    text: root.text("progress_title")
                    font.pixelSize: Theme.fontSizeXLarge
                    font.weight: Theme.fontWeightMedium
                }
                StyledText {
                    text: root.installStep > 0
                        ? "Step " + root.installStep + " of " + root.installSteps
                          + (root.installStepName ? " — " + root.installStepName : "")
                        : "Starting…"
                    color: Theme.surfaceVariantText
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: 8; radius: 4
                    color: Theme.surfaceContainerHighest
                    Rectangle {
                        width: parent.width * root.installFraction
                        height: parent.height; radius: 4
                        color: Theme.primary
                        Behavior on width { NumberAnimation { duration: Theme.mediumDuration; easing.type: Theme.standardEasing } }
                    }
                }

                DankCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    pad: Theme.spacingS
                    ScrollView {
                        anchors.fill: parent
                        clip: true
                        TextArea {
                            text: root.installLog === "" ? "Starting…" : root.installLog
                            font.family: Theme.monoFontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceText
                            readOnly: true
                            wrapMode: TextEdit.Wrap
                            background: null
                        }
                    }
                }
                StyledText {
                    text: root.text("progress_note")
                    color: Theme.warning
                    font.pixelSize: Theme.fontSizeSmall
                }
            }

            // Page 5: Done
            Item {
                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width, 520)
                    spacing: Theme.spacingL

                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        width: 96; height: 96; radius: 48
                        color: root.installSuccess ? Theme.withAlpha(Theme.success, 0.2) : Theme.withAlpha(Theme.error, 0.2)
                        StyledText {
                            anchors.centerIn: parent
                            text: root.installSuccess ? "✓" : "✗"
                            font.pixelSize: 48
                            color: root.installSuccess ? Theme.success : Theme.error
                        }
                    }
                    StyledText {
                        text: root.installSuccess ? root.text("done_title") : root.text("done_failed_title")
                        font.pixelSize: Theme.fontSizeXXLarge
                        font.weight: Theme.fontWeightMedium
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                    }
                    StyledText {
                        text: root.installSuccess
                            ? root.text("done_subtitle")
                            : "Check the installation log for details."
                        color: Theme.surfaceVariantText
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                    }
                    // store_label -> store_url: on every frontend when the
                    // branding sets a store (docs/PARITY.md).
                    StyledText {
                        visible: root.installSuccess && root.storeUrl !== ""
                        text: "<a href=\"" + root.storeUrl + "\">" + root.text("store_label") + "</a>"
                        textFormat: Text.RichText
                        linkColor: Theme.primary
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                        onLinkActivated: link => Qt.openUrlExternally(link)
                    }
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: Theme.spacingM
                        DankButton { text: "Close"; tonal: true; onClicked: Qt.quit() }
                        DankButton {
                            text: root.text("done_restart")
                            visible: root.installSuccess
                            onClicked: rebootProc.running = true
                        }
                    }
                }
            }
        }

        // Hint bar: the keybindings, the way a niri user expects from their bar.
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingL
            visible: root.currentPage <= 3
            Repeater {
                model: [
                    { key: "Enter", what: root.currentPage === 3 ? root.text("confirm_button") : "Continue" },
                    { key: "Shift+Enter", what: "Back" },
                    { key: "Tab", what: "Next field" }
                ]
                RowLayout {
                    required property var modelData
                    spacing: Theme.spacingXS
                    visible: !(modelData.key === "Shift+Enter" && root.currentPage === 0)
                    Rectangle {
                        radius: Theme.cornerRadiusXS
                        color: Theme.surfaceContainerHigh
                        implicitWidth: keyText.implicitWidth + Theme.spacingS * 2
                        implicitHeight: keyText.implicitHeight + Theme.spacingXS * 2
                        StyledText {
                            id: keyText
                            anchors.centerIn: parent
                            text: modelData.key
                            isMonospace: true
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                        }
                    }
                    StyledText {
                        text: modelData.what
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.surfaceVariantText
                    }
                }
            }
            Item { Layout.fillWidth: true }
        }
    }
}
