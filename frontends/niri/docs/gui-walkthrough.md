# The TunaOS niri installer — a walkthrough

Every image here is rendered in CI from the real `ui/installer.qml` by
`tests/gui/capture-screens.py`, so it cannot drift from the app.

**How this is possible without a compositor.** The installer normally runs under
[Quickshell](https://quickshell.org/) on niri, which is why it has been so hard
to look at. The capture loads the *same, unmodified* `installer.qml` under a
plain Qt Quick runtime by supplying local stub implementations of the two
Quickshell modules it imports (`tests/qml-stubs/`). The UI is real; only the
process-spawning backend is canned.

That stub is also a safety boundary: the real backend runs fisherman, which
partitions a disk. A stub that actually executed `command` would repartition
whatever machine rendered the docs.

---

## 1. Welcome

![Welcome](screenshots/01-welcome.png)

The capture shows the requirements gate. It stops the wizard until you
accept it.

## 2. Session

![Session](screenshots/02-session.png)

The keyboard, language and time zone of the live session. The wizard sends
only the fields that you changed. Off live media the fields are read-only,
as in this capture.

## 3. Source

![Source](screenshots/03-source.png)

Each row shows the product and the channel. The search box filters the list.

## 4. Disk

![Disk](screenshots/04-disk.png)

The disks come from `tuna-installer-niri discover-disks`, which reads
`fisherman probe --json`.

## 5. Encryption

![Encryption](screenshots/05-encryption.png)

The filesystem choices under Advanced come from the selected image.

## 6. Account

![Account](screenshots/06-account.png)

The first user. Continue stays off until fisherman accepts the username
(`validate --json --partial`) and the two passwords are the same.

## 7. Confirm

![Confirm](screenshots/07-confirm.png)

The last screen before the install writes to the disk.

## 8. Install

![Progress](screenshots/08-progress.png)

The output of the backend goes into the log.

## 9. Done

![Done](screenshots/09-done.png)

## 10. Recovery key

![Recovery](screenshots/10-recovery.png)

A TPM install shows the recovery key. Restart stays off until you confirm
that you saved the key.

## 11. Tour

![Tour](screenshots/11-tour.png)

## 12. Cancel asks first

![Cancel](screenshots/12-cancel-confirm.png)

Cancel and the window close button open this dialog. The install continues
until you confirm.

## 13. Cancelled

![Cancelled](screenshots/13-cancelled.png)

## 14. Offline

![Offline](screenshots/14-offline.png)

The selected image needs a download and the network check failed. Continue
stays off.

---

## Running the UI yourself, without niri

```sh
pip install PyQt6
python3 tests/gui/capture-screens.py /tmp/shots
```

Or load it interactively with the same stubs on `QML2_IMPORT_PATH`.
