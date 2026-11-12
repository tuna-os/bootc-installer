import QtQuick

// Stub of Quickshell.Io.Process that NEVER SPAWNS ANYTHING.
//
// This matters beyond convenience. The installer's third Process runs the real
// backend, which runs fisherman, which partitions a disk. A stub that actually
// executed `command` would repartition whatever machine rendered the docs. So
// this one serves canned output per backend subcommand and exits 0.
QtObject {
    id: proc

    property var command: []
    property bool running: false
    property bool stdinEnabled: false
    property var stdout: null
    property var stderr: null
    signal exited(int code, int status)
    signal started()

    // Mirror the real Process: write() is fed on started(). The real
    // backend reads the recipe from stdin so the LUKS passphrase never
    // lands in /proc/PID/cmdline. It is kept in `written` so the end-to-end
    // driver (tests/e2e/run.py) can hand exactly what the QML wrote to the
    // real backend; nothing here executes it.
    property string written: ""
    function write(data) { written = data }

    // The exit code the next run reports: 0, or what a harness sets to play
    // a failed or cancelled (130) backend.
    property int exitCode: 0

    // Canned backend output. Shapes match installer/main.go: `detect` returns
    // live facts, TPM and requirements (the harnesses set encryptionChoices
    // from installer/encryption-choices.json); `validate` answers "valid";
    // `discover-disks` returns the disks
    // fisherman's probe offers (installer/probe.go, ProbeDisk). The capture
    // harness replaces the disks with shared/probe/fixtures/laptop.expected.json.
    // Not readonly: a harness replaces one Process's answers to play a
    // different machine (an offline one, for the Source step's gate).
    property var fixtures: ({
        "detect": JSON.stringify({
            isLive: false,
            liveImage: "",
            offlineImages: [],
            hasTpm: true,
            unmet: [],
            // What a branding.json on the docs product would yield; the
            // walkthrough is captured with this, not with the runner's
            // os-release.
            branding: {
                name: "TunaOS", id: "tunaos", defaultHostname: "tunaos",
                defaultImage: "ghcr.io/tuna-os/albacore:gnome"
            }
        }),
        "validate": JSON.stringify({ protocol_version: 1, valid: true, errors: [] }),
        // `netcheck <image>`: the registry answers, so the Source step's
        // Continue is not held by the offline gate.
        "netcheck": JSON.stringify({ connected: true, target: "registry.example:443", tried: [] }),
        // `session-get`: one current value per setting, each in its list.
        "session-get": JSON.stringify({
            keyboard: { current: "us", available: ["us", "de"] },
            locale: { current: "en_US.UTF-8", available: ["en_US.UTF-8", "de_DE.UTF-8"] },
            timezone: { current: "UTC", available: ["UTC", "Europe/Berlin"] },
            connected: true
        }),
        // `source-check`: the answer for an image in a registry, which the
        // probe does not contact (shared/probe/capabilities-cases.json,
        // remote-source), and a host that is not bootc-booted.
        "source-check": JSON.stringify({
            check: { state: "unavailable", reason: "remote_metadata_unavailable",
                     reason_key: "source_check_reason_remote_metadata_unavailable",
                     install_from: "ghcr.io/example/os:stable",
                     update_ref: "ghcr.io/example/os:stable", live_host_image: "",
                     source_digest: "", defaults: [], blockers: [] },
            store: { state: "unavailable", reason: "not_bootc_booted", items: [], hidden: 0 },
            blocks_install: false
        }),
        // `plan`: the view of installer/plan.go for the disk that the
        // capture selects (shared/probe/fixtures/laptop, /dev/sda), with
        // the serial and size of fisherman's grub2-plain golden plan.
        "plan": JSON.stringify({
            valid: true, errors: [], disk: "/dev/sda",
            rows: [
                { kind: "target", values: { disk: "/dev/sda", model: "Samsung SSD 870 EVO 500GB",
                                            size: "465.8 GiB", serial: "FIXTURE-SDA-SERIAL" } },
                { kind: "bound", values: {} },
                { kind: "wipe_disk", values: { disk: "/dev/sda" } }
            ],
            diskIdentity: { serial: "FIXTURE-SDA-SERIAL", sizeBytes: 500107862016 }
        }),
        // `catalog`: no catalog file, as on a machine that ships none.
        "catalog": JSON.stringify({ path: "", skipped: [], default_image: "", selected: "", leaves: [],
            machine: { has_nvidia: false, is_live: false, offline_images: [] },
            live_leaf: null, live_needs_user_creation: true }),
        "discover-disks": JSON.stringify([
            { path: "/dev/nvme0n1", title: "WD_BLACK SN850X 1000GB", model: "WD_BLACK SN850X 1000GB",
              size_label: "953.9 GiB", transport_label: "NVMe", removable: false }
        ])
    })

    onRunningChanged: {
        if (!running) return
        started()
        const sub = command.length > 1 ? command[1] : ""
        const payload = fixtures[sub] !== undefined ? fixtures[sub] : ""
        if (stdout && stdout.feed) stdout.feed(payload)
        Qt.callLater(function () {
            proc.running = false
            proc.exited(proc.exitCode, 0)
        })
    }
}
