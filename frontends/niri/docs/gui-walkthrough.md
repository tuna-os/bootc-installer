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

On live media the page offers Try (quits into the live session) and
Install now. The capture shows the requirements gate. It stops the wizard
until you accept it.

## 2. Session

![Session](screenshots/02-session.png)

The keyboard, language and time zone of the live session. The wizard sends
only the fields that you changed. Off live media the fields are read-only,
as in this capture. The Privacy card sets location services for the
installed system. On the daemon path, the session and account steps store
their picks with ConfigureTarget.

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

An encrypted install lands here after the install: the key on its own
screen, with a copy button, an acknowledgement tick, and a QR dialog.
Restart stays off until you confirm that you saved the key. The daemon
path fetches the key after the install; a failed fetch offers a retry.
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

## 15. Intel RST

![RST](screenshots/15-rst.png)

The firmware hides an NVMe disk behind Intel RST. The page warns and
continues to the disk list; it never blocks.

## 16. Existing data found

![Wipe](screenshots/16-wipe.png)

The chosen disk holds data with room to spare: install into the free space
or erase the whole disk. Below the minimum free space, the page offers
only the whole disk, behind a three second countdown.

## 17. Disclaimer

![Prerelease](screenshots/17-prerelease.png)

Shown when os-release calls the image a pre-release or an experiment.

## 18. Terms of use

![EULA](screenshots/18-eula.png)

The image's terms from `/usr/share/tuna-installer/eula.xml`. Continue
stays off until you tick the box; an unreadable file offers only power
off. No file skips the page.

## 19. Recovery key

![Recovery screen](screenshots/19-recovery.png)

The same screen as 10, photographed on its own page.

## 20. Handoff

![Handoff](screenshots/20-handoff.png)

After the install the daemon hands the new system over. A kept session
offers Continue; otherwise Restart boots the new system and Not now
drops to done.

## 21. Recovery QR code

![QR](screenshots/21-qr.png)

The Show QR Code dialog: scan the key with a phone camera. The matrix is
the backend's `recovery-key` answer, drawn as a grid with its quiet zone.

---

## Running the UI yourself, without niri

```sh
pip install PyQt6
python3 tests/gui/capture-screens.py /tmp/shots
```

Or load it interactively with the same stubs on `QML2_IMPORT_PATH`.
