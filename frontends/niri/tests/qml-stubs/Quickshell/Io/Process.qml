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
    // lands in /proc/PID/cmdline; here it is simply discarded.
    function write(data) { }

    // Canned backend output. Shapes match installer/main.go: `detect` returns
    // offline facts, `discover-disks` returns parsed lsblk.
    readonly property var fixtures: ({
        "detect": JSON.stringify({
            liveImage: "",
            hasTpm: true,
            offlineStores: []
        }),
        "discover-disks": JSON.stringify([
            { name: "nvme0n1", size: "476.9G", type: "disk", tran: "nvme" },
            { name: "sda", size: "1.8T", type: "disk", tran: "sata" }
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
            proc.exited(0, 0)
        })
    }
}
