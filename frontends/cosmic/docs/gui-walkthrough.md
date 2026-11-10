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

## 1. Requirements

![Requirements](screenshots/01-requirements.png)

fisherman's probe says which requirements the machine does not meet. The
wizard shows this page only while a gate stands. The capture shows the
state with no gate.

## 2. Welcome

![Welcome](screenshots/02-welcome.png)

The COSMIC header bar has the step counter and a progress bar for the whole
wizard. Nothing is written to a disk until you confirm on the last step.

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

A pick changes the live session, best effort. Each page says that it
changes this session only: the installed system keeps the values of its
image.

## 5. Network

![Network](screenshots/07-network.png)
![No connection](screenshots/18-offline.png)

The check tries the registry of the selected image on port 443 first.
**Continue** is there only when the check passes. With no connection,
**Network settings** opens the desktop's own tool and **Recheck** runs the
check again. Live media skips this page.

## 6. Select a disk

![Select a disk](screenshots/08-disk.png)

Disks come from `fisherman probe --json` (`shared/probe/README.md`). Each
row has the model, the device node, fisherman's size label and the bus.
**Continue** is not there until a disk is selected.

## 7. Options

![Options](screenshots/09-options.png)

The computer name, the filesystem and the encryption. The filesystem list
is the list of the selected image. An encryption type that needs a
passphrase adds **Passphrase** and **Confirm passphrase**; a mismatch shows
under the second field and holds **Continue**. The capture shows this state.

## 8. Account

![Account](screenshots/10-account.png)

The account of the installed system: the recipe's `user` block (username,
full name, password and the groups of `shared/account/groups.json`). The
password is typed two times, and the eye button reveals it. **Continue**
waits for a username, for two passwords that are the same, and for
fisherman to accept the username. The wizard skips this page only when the
catalog says that the image makes its own first user.

## 9. Tour

![Tour](screenshots/11-tour.png)

The slides of the selected image, when its catalog entry has a `carousel`.

## 10. Confirm

![Confirm](screenshots/12-confirm.png)

All the choices, below a warning that names the disk. This is the last
screen before the installer writes to the disk, and the only screen with a
destructive button.

## 11. Installing

![Installing](screenshots/13-installing.png)
![Stop the installation?](screenshots/16-cancel.png)

`fisherman` reads the recipe JSON on stdin, never from a file (it has the
passphrase and the account password). Its progress events move the bar and
fill the log card. **Cancel** asks first. "Stop the installation" then
signals the whole install, and fisherman cleans up.

The log here is fixture text. The capture harness sets this page directly
and never sends `StartInstall`, and the message handler refuses
`StartInstall` in capture mode.

## 12. Finished

![Finished](screenshots/14-done.png)
![Recovery key](screenshots/15-recovery.png)
![Cancelled](screenshots/17-cancelled.png)

Installed, cancelled or failed, in the colours of the COSMIC theme. After
a TPM install the page shows the recovery key and holds **Restart now**
until you tick the box. A cancelled install has its own heading: it is not
a failure.

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
