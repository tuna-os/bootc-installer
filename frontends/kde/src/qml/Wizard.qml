// The step runner.
//
// Modelled on KDE KISS's src/qml/Wizard.qml (https://github.com/KDE/kiss):
// each step is a self-contained SetupModule under modules/<name>/contents/ui,
// and the wizard slides between them with hand-rolled NumberAnimations rather
// than a SwipeView — KISS's comment is that a SwipeView is less performant and
// glitchy on window resize, and this inherits both the technique and the reason.
//
// SPDX-License-Identifier: GPL-3.0-only

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

import org.tunaos.installer
import org.tunaos.installer.components as TunaComponents

Kirigami.Page {
    id: root

    leftPadding: 0
    rightPadding: 0
    topPadding: 0
    bottomPadding: 0

    // Starts on the first step that has something to show (requirements
    // only while a gate is unmet), so the first frame, and the readiness
    // stamp taken from it, name a real screen. Assignments replace the
    // binding as soon as the wizard moves.
    property int currentIndex: firstStep()
    readonly property int stepCount: stepsRepeater.count
    readonly property string currentStepId: (currentIndex >= 0 && currentIndex < stepsModel.count)
        ? stepsModel.get(currentIndex).stepId : ""

    // Filled in by the delegates.
    property Control currentStepItem: null
    property Control nextStepItem: null
    property Control previousStepItem: null
    property TunaComponents.SetupModule currentModule: null

    readonly property bool onFinalPage: currentIndex === stepCount - 1

    // The heading over each step. The confirm step's is the branding
    // contract's confirm_title, so a product can word the last page before
    // the disk is written; the others are structural step names.
    function stepTitle(index) {
        const step = stepsModel.get(index)
        return step.stepId === "confirm" ? InstallerController.text("confirm_title") : step.name
    }

    ListModel {
        id: stepsModel

        // The eighteen screens of shared/flow/screens.yaml, in its order.
        ListElement { stepId: "requirements";   name: qsTr("Requirements");          url: "modules/requirements/main.qml" }
        ListElement { stepId: "try-or-install"; name: qsTr("Try or Install");        url: "modules/tryorinstall/main.qml" }
        ListElement { stepId: "language";       name: qsTr("Language");              url: "modules/language/main.qml" }
        ListElement { stepId: "keyboard";       name: qsTr("Keyboard Layout");       url: "modules/keyboard/main.qml" }
        ListElement { stepId: "timezone";       name: qsTr("Time Zone");             url: "modules/timezone/main.qml" }
        ListElement { stepId: "network";        name: qsTr("Network");               url: "modules/network/main.qml" }
        ListElement { stepId: "prerelease";     name: qsTr("Disclaimer");            url: "modules/prerelease/main.qml" }
        ListElement { stepId: "eula";           name: qsTr("Terms of Use");          url: "modules/eula/main.qml" }
        ListElement { stepId: "rst";            name: qsTr("Intel RST");             url: "modules/rst/main.qml" }
        ListElement { stepId: "disk";           name: qsTr("Target Disk");           url: "modules/disk/main.qml" }
        ListElement { stepId: "wipe-or-free";   name: qsTr("Existing Data");         url: "modules/wipefree/main.qml" }
        ListElement { stepId: "encryption";     name: qsTr("Disk Encryption");       url: "modules/encryption/main.qml" }
        ListElement { stepId: "account";        name: qsTr("User Account");          url: "modules/account/main.qml" }
        ListElement { stepId: "confirm";        name: qsTr("Confirm Installation");  url: "modules/confirm/main.qml" }
        ListElement { stepId: "install";        name: qsTr("Installing");            url: "modules/progress/main.qml" }
        ListElement { stepId: "recovery-key";   name: qsTr("Recovery Key");          url: "modules/recoverykey/main.qml" }
        ListElement { stepId: "handoff";        name: qsTr("Handoff");               url: "modules/handoff/main.qml" }
        ListElement { stepId: "done";           name: qsTr("Finished");              url: "modules/done/main.qml" }
    }

    // The index of a step id, or -1.
    function stepIndex(stepId: string): int {
        for (let i = 0; i < stepsModel.count; i++) {
            if (stepsModel.get(i).stepId === stepId) {
                return i;
            }
        }
        return -1;
    }

    // The first step the wizard lands on: the model's first that has
    // something to show (requirements only while a gate is unmet).
    function firstStep(): int {
        let index = 0;
        while (index < stepsModel.count - 1 && stepSkipped(index)) {
            index++;
        }
        return index;
    }

    // After a failure or a cancel: forget the result and go back to the
    // disk step. Nothing here starts an install.
    function retry(): void {
        InstallerController.resetForRetry();
        goToStep(stepIndex("disk"));
    }

    Component.onCompleted: stepHeading.text = stepTitle(currentIndex)

    // Step animation. Manually animating is more performant and less glitchy
    // with window resize than a SwipeView.
    property real previousStepItemX: 0
    property real currentStepItemX: 0
    property real nextStepItemX: 0

    NumberAnimation on previousStepItemX {
        id: previousStepAnim
        duration: Kirigami.Units.longDuration * 2
        easing.type: Easing.OutExpo
        onFinished: if (root.previousStepItemX !== 0 && root.previousStepItem) {
            root.previousStepItem.visible = false;
        }
    }

    NumberAnimation on currentStepItemX {
        id: currentStepAnim
        duration: Kirigami.Units.longDuration * 2
        easing.type: Easing.OutExpo
    }

    NumberAnimation on nextStepItemX {
        id: nextStepAnim
        duration: Kirigami.Units.longDuration * 2
        easing.type: Easing.OutExpo
        onFinished: if (root.nextStepItemX !== 0 && root.nextStepItem) {
            root.nextStepItem.visible = false;
        }
    }

    readonly property bool animating: previousStepAnim.running || currentStepAnim.running || nextStepAnim.running

    function activate(index: int): void {
        const item = stepsRepeater.itemAt(index);
        if (item && item.module && typeof item.module.onPageActivated === "function") {
            item.module.onPageActivated();
        }
    }

    // A step that has nothing to ask is never *landed on* by Next/Back, but
    // it stays in the model — and reachable by goToStep — so the step shape
    // and the harness walk survive. The rules live in the controller
    // (InstallerController.stepSkipped), where the backend tests pin them.
    function stepSkipped(index: int): bool {
        return InstallerController.stepSkipped(stepsModel.get(index).stepId);
    }

    function requestNextPage(): void {
        if (animating) {
            return;
        }
        let target = currentIndex + 1;
        while (target < stepCount && stepSkipped(target)) {
            target++;
        }
        if (target >= stepCount) {
            return;
        }
        if (target !== currentIndex + 1) {
            // A jump, not a slide: the slide animation below assumes
            // adjacent steps. Skips are rare (the account step only).
            goToStep(target);
            return;
        }

        previousStepItemX = 0;
        activate(currentIndex + 1);

        currentIndex++;
        stepHeading.changeText(stepTitle(currentIndex));

        currentStepItemX = root.width;
        currentStepItem.visible = true;

        previousStepAnim.to = -root.width;
        previousStepAnim.restart();
        currentStepAnim.to = 0;
        currentStepAnim.restart();
    }

    function requestPreviousPage(): void {
        if (animating) {
            return;
        }
        let target = currentIndex - 1;
        while (target >= 0 && stepSkipped(target)) {
            target--;
        }
        if (target < 0) {
            return;
        }
        if (target !== currentIndex - 1) {
            goToStep(target);
            return;
        }

        nextStepItemX = 0;
        activate(currentIndex - 1);

        currentIndex--;
        stepHeading.changeText(stepTitle(currentIndex));

        currentStepItemX = -root.width;
        currentStepItem.visible = true;

        nextStepAnim.to = root.width;
        nextStepAnim.restart();
        currentStepAnim.to = 0;
        currentStepAnim.restart();
    }

    /*!
     * Jump straight to a step, with no animation and no side effects beyond the
     * target module's onPageActivated().
     *
     * This exists for the screenshot harness. It is safe to walk every step
     * with it because nothing here — and nothing in any module's
     * onPageActivated() — can start an install: the only caller of
     * InstallerController.startInstall() is the Install button's onClicked
     * below. Worth stating, because the sibling XFCE installer *does* kick off
     * an install from its page-enter hook.
     */
    function goToStep(index: int): void {
        if (index < 0 || index >= stepCount) {
            return;
        }
        previousStepAnim.stop();
        currentStepAnim.stop();
        nextStepAnim.stop();

        activate(index);
        currentIndex = index;

        previousStepItemX = 0;
        nextStepItemX = 0;
        currentStepItemX = 0;

        for (let i = 0; i < stepsRepeater.count; ++i) {
            const item = stepsRepeater.itemAt(i);
            if (item) {
                item.visible = (i === index);
            }
        }
        stepHeading.text = stepTitle(index);
        stepHeading.opacity = 1;
    }

    // The install runs on the install step and the wizard leaves that step
    // by itself when the backend ends the install.
    //
    // This is a state, not a reaction to the installCompleted signal alone.
    // An install can end before the slide to the install step is over, or
    // before it starts (a refused configuration fails inside
    // startInstall()). The signal then arrived while the wizard could not
    // move, and the wizard stayed on the install step for ever. So: the
    // install that this wizard started is over, the install step is on
    // screen, and no slide runs.
    //
    // installStarted is set only by the Install button. The screenshot
    // harness loads a finished state and jumps to the install step, and
    // must stay there.
    property bool installStarted: false
    readonly property bool installOver: installStarted && currentStepId === "install"
        && InstallerController.installFinished && !animating
    onInstallOverChanged: if (installOver) {
        installStarted = false;
        Qt.callLater(root.requestNextPage);
    }

    // Try-or-install, requirements, network, recovery-key, handoff and done
    // are hero pages that carry their own
    // heading; a header title over them only repeated it. The step
    // indicator still names them.
    readonly property bool heroStep: currentStepId === "try-or-install" || currentStepId === "requirements"
        || currentStepId === "network" || currentStepId === "recovery-key" || currentStepId === "handoff"
        || currentStepId === "done"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Step indicator: "Step N of M · Name" and one dot per step, the
        // way COSMIC's header and Niri's dots show it. The count is the
        // model's, in the order of shared/flow/screens.yaml. Colours come
        // from Kirigami.Theme, sizes from Kirigami.Units.
        RowLayout {
            objectName: "stepIndicator"
            spacing: Kirigami.Units.largeSpacing

            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.largeSpacing
            Layout.leftMargin: Kirigami.Units.gridUnit
            Layout.rightMargin: Kirigami.Units.gridUnit

            Label {
                objectName: "stepCounter"
                text: qsTr("Step %1 of %2 · %3").arg(root.currentIndex + 1).arg(root.stepCount)
                    .arg(stepsModel.get(root.currentIndex).name)
                color: Kirigami.Theme.disabledTextColor
                elide: Text.ElideRight

                Layout.fillWidth: true
            }

            Row {
                spacing: Kirigami.Units.smallSpacing

                Accessible.role: Accessible.ProgressBar
                Accessible.name: qsTr("Step %1 of %2").arg(root.currentIndex + 1).arg(root.stepCount)

                Repeater {
                    model: root.stepCount

                    delegate: Rectangle {
                        required property int index

                        readonly property bool current: index === root.currentIndex

                        anchors.verticalCenter: parent.verticalCenter
                        width: current ? Kirigami.Units.gridUnit * 1.5 : Kirigami.Units.smallSpacing * 2
                        height: Kirigami.Units.smallSpacing * 2
                        radius: height / 2
                        color: index <= root.currentIndex
                            ? Kirigami.Theme.highlightColor
                            : Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                      Kirigami.Theme.textColor.b, 0.2)

                        Behavior on width {
                            NumberAnimation { duration: Kirigami.Units.shortDuration }
                        }
                    }
                }
            }
        }

        Label {
            id: stepHeading

            opacity: 0
            visible: !root.heroStep
            text: qsTr("Welcome")
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.6

            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.largeSpacing
            Layout.leftMargin: Kirigami.Units.gridUnit
            Layout.rightMargin: Kirigami.Units.gridUnit

            property string toText: ""

            function changeText(text: string): void {
                toText = text;
                toHidden.restart();
            }

            NumberAnimation on opacity {
                id: toHidden
                duration: Kirigami.Units.shortDuration
                to: 0
                onFinished: {
                    stepHeading.text = stepHeading.toText;
                    toShown.restart();
                }
            }

            NumberAnimation on opacity {
                id: toShown
                running: true
                duration: Kirigami.Units.shortDuration
                to: 1
            }
        }

        Item {
            id: stepsContainer

            // Looked up by the screenshot harness, which audits the pixels of
            // the step area specifically: the heading and the button row draw
            // on every step, so a whole-window audit would still find ink on a
            // step whose module rendered nothing at all.
            objectName: "stepsContainer"

            clip: true

            Layout.fillWidth: true
            Layout.fillHeight: true

            Repeater {
                id: stepsRepeater
                model: stepsModel
                delegate: PageDelegate {}
            }
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.gridUnit

            Button {
                objectName: "backButton"
                text: qsTr("Back")
                icon.name: "arrow-left-symbolic"

                topPadding: Kirigami.Units.largeSpacing
                bottomPadding: Kirigami.Units.largeSpacing
                leftPadding: Kirigami.Units.gridUnit
                rightPadding: Kirigami.Units.gridUnit

                // No going back once fisherman has been handed the disk, and
                // none on the first step either (Back is already hidden
                // there by currentIndex > 0).
                visible: root.currentIndex > root.firstStep()
                    && root.currentStepId !== "install"
                    && root.currentStepId !== "recovery-key"
                    && root.currentStepId !== "handoff"
                    && root.currentStepId !== "done"

                onClicked: root.requestPreviousPage()
            }

            Item {
                Layout.fillWidth: true
            }

            Button {
                id: nextButton
                objectName: "nextButton"

                readonly property bool isInstall: root.currentStepId === "confirm"
                readonly property bool isClose: root.currentStepId === "done"

                topPadding: Kirigami.Units.largeSpacing
                bottomPadding: Kirigami.Units.largeSpacing
                leftPadding: Kirigami.Units.gridUnit
                rightPadding: Kirigami.Units.gridUnit

                // Nicer to have the arrow on the side it's pointing to.
                LayoutMirroring.enabled: !isInstall && !isClose
                    && Qt.application.layoutDirection === Qt.LeftToRight

                // Hidden while fisherman runs (the install step advances
                // itself) and on steps whose content navigates: try-or-install
                // carries its own Try and Install now buttons, wipe-or-free
                // its own choice buttons.
                visible: root.currentStepId !== "install"
                    && root.currentStepId !== "try-or-install"
                    && root.currentStepId !== "wipe-or-free"
                    && root.currentStepId !== "recovery-key"
                    && root.currentStepId !== "handoff"

                // Branding copy on the two buttons that carry a product's voice:
                // leaving the welcome page and starting the install.
                text: isInstall ? InstallerController.text("confirm_button")
                    : (isClose ? qsTr("Close") : qsTr("Next"))
                icon.name: isInstall ? "install-symbolic"
                    : (isClose ? "window-close-symbolic" : "arrow-right-symbolic")

                enabled: root.currentModule ? root.currentModule.nextEnabled : false

                // The one and only place an install is started.
                onClicked: {
                    if (isClose) {
                        Qt.quit();
                    } else if (isInstall) {
                        root.installStarted = true;
                        InstallerController.startInstall();
                        root.requestNextPage();
                    } else {
                        root.requestNextPage();
                    }
                }
            }
        }
    }

    /*!
     * Delegate that represents each step in the wizard.
     */
    component PageDelegate: Control {
        id: item

        required property int index
        required property string url

        property TunaComponents.SetupModule module: null

        // Set once below, then by the wizard as it moves: not a binding,
        // so a step that slides out stays drawn until its slide ends.
        visible: false

        width: stepsContainer.width
        height: stepsContainer.height

        topPadding: Kirigami.Units.gridUnit
        bottomPadding: Kirigami.Units.gridUnit
        leftPadding: Kirigami.Units.gridUnit
        rightPadding: Kirigami.Units.gridUnit

        contentItem: module ? module.contentItem : null

        Component.onCompleted: {
            const component = Qt.createComponent(Qt.resolvedUrl(url));
            if (component.status === Component.Error) {
                console.error("failed to load step", url, component.errorString());
                return;
            }
            module = component.createObject(item) as TunaComponents.SetupModule;
            module.advanceRequested.connect(() => root.requestNextPage());
            module.retryRequested.connect(() => root.retry());
            visible = (index === root.currentIndex);
            updateRootItems();
        }

        Binding {
            target: item.module
            property: "cardWidth"
            value: Math.min(Kirigami.Units.gridUnit * 30,
                            item.width - Kirigami.Units.gridUnit * 4)
            when: item.module !== null
        }

        transform: Translate {
            x: {
                if (item.index === root.currentIndex - 1) {
                    return root.previousStepItemX;
                } else if (item.index === root.currentIndex + 1) {
                    return root.nextStepItemX;
                } else if (item.index === root.currentIndex) {
                    return root.currentStepItemX;
                }
                return 0;
            }
        }

        function updateRootItems(): void {
            if (index === root.currentIndex) {
                root.currentStepItem = item;
                root.currentModule = module;
            } else if (index === root.currentIndex - 1) {
                root.previousStepItem = item;
            } else if (index === root.currentIndex + 1) {
                root.nextStepItem = item;
            }
        }

        Connections {
            target: root

            function onCurrentIndexChanged(): void {
                item.updateRootItems();
            }
        }
    }
}
