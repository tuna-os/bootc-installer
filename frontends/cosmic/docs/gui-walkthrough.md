# Installing TunaOS with the COSMIC installer — a walkthrough

This is what the installer looks like, screen by screen. Every image on this
page is generated in CI from the real libcosmic application by the capture mode
built into the binary (`TUNA_CAPTURE_DIR=... tuna-installer-cosmic`), so it
cannot drift from the app the way hand-taken screenshots do.

The capture runs headless with no desktop, no GPU and no real disks: Xvfb for a
display, Mesa's **lavapipe** for a software Vulkan adapter so wgpu has
something to render on, and fixture data in place of every hardware query. It
never touches a disk.

---

The pages are in the order of `shared/flow/screens.yaml`. The file name of
a frame is its place in the capture and the slug of its page. The capture
shows each page, also a page that a real run skips.

## 1. Requirements

![Requirements](screenshots/01-requirements.png)

The probe says which requirements the machine does not meet. The wizard
shows this page only while a gate stands. The capture shows the state with
no gate.

## 2. Try or install

![Welcome](screenshots/02-try-or-install.png)

**Try** quits the wizard and the live session continues. **Install**
goes on. The COSMIC header bar has the step counter and a progress bar for
the wizard. Nothing is written to a disk until you confirm.

## 3. Choose a system

![Choose a system](screenshots/03-image.png)

The image catalog as a flat list with a search box. A row shows the product
and the channel ("Capture Desktop › Stable"), not the channel alone. The
selection at the start is the `default_image` of the branding, then of the
catalog. With neither, nothing is selected and **Continue** is not there.
The last row takes a custom image reference. Live media skips this page.

## 4. Language, keyboard and time zone

![Language](screenshots/04-language.png)
![Keyboard](screenshots/05-keyboard.png)
![Time zone](screenshots/06-timezone.png)

A pick changes the live session, best effort, and goes to the installed
system. On the daemon backend the time zone page also has the **Location
services** switch. It starts off. The daemon gets the choice only after
you move the switch.

## 5. Network

![Network](screenshots/07-network.png)
![No connection](screenshots/24-offline.png)

The check tries the registry of the selected image on port 443 first.
**Continue** is there only when the check passes. With no connection,
**Network settings** opens the desktop's own tool and **Recheck** runs the
check again. Live media skips this page.

## 6. Disclaimer and terms of use

![Disclaimer](screenshots/08-prerelease.png)
![Terms of use](screenshots/09-eula.png)

The disclaimer shows for a pre-release or an experiment (`RELEASE_TYPE` of
os-release). The terms show when the medium has
`/usr/share/tuna-installer/eula.xml`. `TUNA_EULA_FILE` names another file.
The box holds **Continue**.

## 7. Intel RST

![Intel RST](screenshots/10-rst.png)

The daemon reports Intel RST, which hides the solid-state disk from Linux.
The page says why a disk can be absent from the list. It does not block.

## 8. Select a disk

![Select a disk](screenshots/11-disk.png)

The disks come from the probe (`shared/probe/README.md`). Each row has the
model, the device node, the size label of the backend and the bus.
**Continue** is not there until a disk is selected.

## 9. Existing data

![Existing data](screenshots/12-wipe-or-free.png)

Daemon backend only. When the disk has data and free space, you select the
free space or the whole disk. The free space is the default.

## 10. Disk encryption

![Disk encryption](screenshots/13-encryption.png)

An encryption type that needs a passphrase adds **Passphrase** and
**Confirm passphrase**. A mismatch shows under the second field and holds
**Continue**. The capture shows this state. On the daemon backend a
computer with a TPM 2.0 skips this page: the TPM locks the disk.

## 11. Options

![Options](screenshots/14-options.png)

Legacy backend only: the filesystem. The list is the list of the selected
image.

## 12. Account

![Account](screenshots/15-account.png)

The computer name and the account of the installed system. The password is
typed two times, and the eye button reveals it. **Continue** waits for a
username, for two passwords that are the same, and for the backend to
accept the username. The wizard skips this page when the catalog says that
the image makes its own first user. On the daemon backend it also skips
the page when `cosmic-initial-setup` is on the medium: that tool makes the
user at the first start.

## 13. Tour

![Tour](screenshots/16-tour.png)

The slides of the selected image, when its catalog entry has a `carousel`.

## 14. Confirm

![Confirm](screenshots/17-confirm.png)

All the choices, below a warning that names the disk. This is the last
screen before the installer writes to the disk, and the only screen with a
destructive button.

## 15. Installing

![Installing](screenshots/18-installing.png)
![Stop the installation?](screenshots/22-cancel.png)

The progress events of the backend move the bar and fill the log card.
**Cancel** asks first. The legacy backend then signals the whole install.
The daemon backend sends `Cancel` on a second connection.

The log here is fixture text. The capture harness sets this page directly
and never sends `StartInstall`, and the message handler refuses
`StartInstall` in capture mode.

## 16. Recovery key

![Recovery key](screenshots/19-recovery-key.png)
![No recovery key](screenshots/26-recovery-key-failed.png)

The key of an encrypted disk, with **Copy** and a QR code. **Done** is
not there until you tick the box. When the daemon gives no key, the page
offers **Try again** and no **Done**.

## 17. Handoff

![Handoff](screenshots/20-handoff.png)
![The handoff failed](screenshots/27-handoff-failed.png)

The page says what the daemon does next: the session becomes the installed
system, the system restarts into the copy, or the computer restarts.
**Continue** starts it. **Not now** goes to the last page. A failure
offers **Close** and **Restart**.

## 18. Finished

![Finished](screenshots/21-done.png)
![Cancelled](screenshots/23-cancelled.png)
![Failed](screenshots/25-failed.png)

Installed, cancelled or failed, in the colours of the COSMIC theme. A
cancelled install has its own heading: it is not a failure. A failed daemon
install says why, and whether the disk changed. **Try again** goes back to
Confirm.

---

## Regenerating these

```bash
sudo apt-get install -y mesa-vulkan-drivers xvfb imagemagick
just capture
```

The capture reads its own pixels back — it pulls the frame wgpu actually
presented via `iced::window::screenshot` and measures colour count, the share
of the frame taken by a single flat colour, and the share that is "ink". A page
that failed to render is a valid, non-empty PNG of nothing, so file existence
proves nothing; `bootc-installer-asahi` shipped a blank settings page behind
exactly that check. The thresholds are calibrated against measured output from
real renders and every run prints its numbers.

## What the first capture run caught

Two defects that no diff would have shown, found the first time these images
were rendered:

* **No icons at all.** Every `icon::from_name(...)` silently drew nothing,
  including the dropdown chevrons on the Options page and the window controls
  in the header bar — the controls were simply absent. libcosmic resolves icons
  through the freedesktop icon theme, and nothing had named one. Fixed by
  setting `default_icon_theme("Adwaita")`.
* **An unreadable warning banner.** `widget::warning::warning` on the Confirm
  page drew near-white body text on a light amber fill: legible in the light
  COSMIC theme, effectively invisible in the dark one. Replaced with a card and
  warning-coloured text.

Both were live in the code and both are exactly the class of problem this job
exists to surface.
