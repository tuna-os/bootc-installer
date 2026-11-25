# Installer frontends: walkthrough and parity

`shared/walkthrough/aggregate.py` makes this page from the screenshot job
of each frontend. CI renders each frame from the real UI, so this page
cannot drift from the apps. Do not edit this page by hand.

## Parity matrix

The matrix shows the screens of the shared contract that each frontend
reaches. Each harness reads the visible widget text of each page that it
captures. `shared/walkthrough/parity_report.py` compares that text with
the contract. For a strict report, the aggregator does a second check
against the frames. An advisory report is not a pass.

| Mark | Meaning |
|---|---|
| ✅ | The frontend reaches the screen. |
| ❌ | The frontend does not reach a required screen. |
| ⚠️ | The frontend does not reach an optional screen. |
| ➖ | No measurement: the harness of this frontend does not read its widget text. |
| ⚪ | The `screen_exemptions` of the frontend exempt the screen. |
| ⏳ | No capture is on record. |

| Screen | GNOME | KDE Plasma | COSMIC | Niri | XFCE |
|---|---|---|---|---|---|
| `welcome` (required) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `disk` (required) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `encryption` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `summary` (required) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `install` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `done` | ✅ | ✅ | ✅ | ✅ | ✅ |

| Frontend | Pages | Rendered | Transitions | Report | Harness |
|---|---|---|---|---|---|
| GNOME | 13 | 13 | 12 | strict, passed | tests/gui/capture-screens.py (GTK4/libadwaita under Xvfb) |
| KDE Plasma | 15 | 15 | 14 | strict, passed | tests/capture.cpp (Kirigami/QML, offscreen) |
| COSMIC | 39 | 39 | 38 | strict, passed | src/capture.rs (libcosmic on lavapipe under Xvfb) |
| Niri | 21 | 21 | 20 | strict, passed | tests/gui/capture-screens.py (QML via PyQt6, offscreen) |
| XFCE | 20 | 20 | 19 | strict, passed | tests/gui/capture-screens.py (GTK3 under Xvfb) |

## GNOME

GTK4 / libadwaita (Python). Source: `bootc_installer/`.

<p align="center"><img src="gnome/walkthrough.gif" alt="GNOME installer walkthrough" width="640"></p>

| | |
|---|---|
| <img src="gnome/01-welcome.png" width="360"> | **welcome** What the installer is about to do. <br><sub>Welcome to TunaOS Install TunaOS Installs to your internal disk. Install TunaOS Installs to your internal disk. Power Off Power Off Press Su</sub> |
| <img src="gnome/02-language.png" width="360"> | **language** The language of the installed system. <br><sub>Language Select your language Search languages aa_DJ.UTF-8 aa_DJ.UTF-8 aa_DJ.UTF-8 ab_GE.UTF-8 ab_GE.UTF-8 ab_GE.UTF-8 af_ZA.UTF-8 af_ZA.UTF</sub> |
| <img src="gnome/03-keyboard.png" width="360"> | **keyboard** The keyboard layout, for this session and the installed system. <br><sub>Keyboard Layout Select your preferred keyboard layout Search keyboard layouts Abkhazian (Russia) Abkhazian Abkhazian (Russia) Abkhazian ru+a</sub> |
| <img src="gnome/04-timezone.png" width="360"> | **timezone** The time zone of the installed system. <br><sub>Date &amp; Time Select your preferred timezone Search timezones Afghanistan Afghanistan Asia Afghanistan Asia Kabul Kabul Asia/Kabul Albania Alb</sub> |
| <img src="gnome/05-image.png" width="360"> | **image** Choose the image to install from the catalog. <br><sub>Choose an Image Select a BootcOS image to install, or enter a custom bootc-compatible image URL. Search images… Capture Desktop Capture Desk</sub> |
| <img src="gnome/06-qr_companion.png" width="360"> | **qr companion** Optional: scan a QR code and type your account details on your phone. <br><sub>Set Up From Your Phone Type your account details on your phone instead of this keyboard. Both devices need to be on the same network. No QR</sub> |
| <img src="gnome/07-disk.png" width="360"> | **disk** Choose the disk. Nothing is written yet. <br><sub>Computer is not plugged in — connect power before installing Install Location Select the disk where you want to install. All data on the sel</sub> |
| <img src="gnome/08-encryption.png" width="360"> | **encryption** Full-disk encryption, with or without TPM2. <br><sub>Disk Encryption Choose how to protect the data on your disk. Encrypt this disk You'll type it at every boot. Encrypt this disk You'll type i</sub> |
| <img src="gnome/09-user.png" width="360"> | **user** Your account and password. <br><sub>Create User Provide details for your user account Name Name Name Username Username Username Password Password Password Confirm Password Conf</sub> |
| <img src="gnome/10-confirm.png" width="360"> | **confirm** The last screen before anything is written. <br><sub>Confirm installation Everything on /dev/sda will be erased. This cannot be undone. Everything on /dev/sda will be erased. This cannot be und</sub> |
| <img src="gnome/11-progress.png" width="360"> | **progress** The install, step by step. <br><sub>Installing TunaOS… Downloading… (47 of 71 parts) 0:00 elapsed 35% Do not power off the computer. Cancel Cancel</sub> |
| <img src="gnome/12-recovery-key.png" width="360"> | **recovery key** The LUKS recovery key, shown once after an encrypted install. <br><sub>Save your recovery key If your disk fails to unlock automatically, you will need this recovery key to access your data. Save it somewhere sa</sub> |
| <img src="gnome/13-done.png" width="360"> | **done** Finished. Restart into the new system. <br><sub>Capture Desktop is installed Remove the installation media and restart the computer. The new system has not started yet, so nothing has chec</sub> |

## KDE Plasma

Qt 6 / Kirigami (C++ + QML). Source: `frontends/kde/`.

<p align="center"><img src="kde/walkthrough.gif" alt="KDE Plasma installer walkthrough" width="640"></p>

| | |
|---|---|
| <img src="kde/01-tryorinstall.png" width="360"> | **tryorinstall**  <br><sub>Step 1 of 12 · Try or Install TunaOS Try TunaOS without changing this computer, or install it. Try TunaOS &amp;Try TunaOS Install now &amp;Install n</sub> |
| <img src="kde/02-welcome.png" width="360"> | **welcome**  <br><sub>Step 2 of 12 · Welcome Welcome to TunaOS This wizard will guide you through installing TunaOS onto this computer. You will choose a disk and</sub> |
| <img src="kde/03-prerelease.png" width="360"> | **prerelease**  <br><sub>Step 3 of 12 · Disclaimer Disclaimer Disclaimer TunaOS 99 is an experiment. Nothing here is stable, and the installer says so. Back &amp;Back Ne</sub> |
| <img src="kde/04-eula.png" width="360"> | **eula**  <br><sub>Step 4 of 12 · Terms of Use Terms of Use Terms of use Use of this system Do not use this experiment for anything important. You agree to the</sub> |
| <img src="kde/05-rst.png" width="360"> | **rst**  <br><sub>Step 5 of 12 · Intel RST Intel RST Intel RST is on This computer hides its NVMe disk behind Intel RST. The disk list on the next step cannot</sub> |
| <img src="kde/06-disk.png" width="360"> | **disk**  <br><sub>Step 6 of 12 · Target Disk Target Disk Choose the disk where TunaOS will be installed. Everything on the selected disk will be erased. Every</sub> |
| <img src="kde/07-wipefree.png" width="360"> | **wipefree**  <br><sub>Step 7 of 12 · Existing Data Existing Data Existing data found /dev/nvme0n1 already holds data. Install to Free Space &amp;Install to Free Space</sub> |
| <img src="kde/08-encryption.png" width="360"> | **encryption**  <br><sub>Step 8 of 12 · Disk Encryption Disk Encryption Encryption protects your files if the disk is lost or stolen. It cannot be turned on later wi</sub> |
| <img src="kde/09-account.png" width="360"> | **account**  <br><sub>Step 9 of 12 · User Account User Account Create the account you will sign in with. It can also administer this computer. Alex Example Full n</sub> |
| <img src="kde/10-confirm.png" width="360"> | **confirm**  <br><sub>Step 10 of 12 · Confirm Installation Confirm installation Everything on /dev/nvme0n1 will be erased. This cannot be undone. Everything on /d</sub> |
| <img src="kde/11-install.png" width="360"> | **install**  <br><sub>Step 11 of 12 · Installing Installing Installing TunaOS… /dev/nvme0n1. Do not power off the computer. Step 5 of 8 — Installing TunaOS… [1/8]</sub> |
| <img src="kde/12-recovery.png" width="360"> | **recovery**  <br><sub>Step 12 of 12 · Finished TunaOS is installed Remove the installation media and restart the computer. The new system has not started yet, so</sub> |
| <img src="kde/14-done.png" width="360"> | **done**  <br><sub>Step 12 of 12 · Finished TunaOS is installed Remove the installation media and restart the computer. The new system has not started yet, so</sub> |
| <img src="kde/15-cancel-confirm.png" width="360"> | **cancel confirm**  <br><sub>Step 11 of 12 · Installing Installing Installing TunaOS… /dev/nvme0n1. Do not power off the computer. Step 5 of 8 — Installing TunaOS… [1/8]</sub> |
| <img src="kde/16-cancelled.png" width="360"> | **cancelled**  <br><sub>Step 12 of 12 · Finished Installation cancelled You stopped the installation. The selected disk is erased and has no complete system. Start</sub> |

## COSMIC

libcosmic / iced (Rust). Source: `frontends/cosmic/`.

<p align="center"><img src="cosmic/walkthrough.gif" alt="COSMIC installer walkthrough" width="640"></p>

| | |
|---|---|
| <img src="cosmic/01-requirements.png" width="360"> | **requirements**  <br><sub>Requirements met Firmware setup Power off Continue</sub> |
| <img src="cosmic/02-try-or-install.png" width="360"> | **try or install**  <br><sub>Welcome to TunaOS Welcome. This assistant will guide you through installing TunaOS onto this computer. You will choose a target disk and a f</sub> |
| <img src="cosmic/02-welcome.png" width="360"> | **welcome**  |
| <img src="cosmic/03-image.png" width="360"> | **image**  <br><sub>Choose a system What to install onto the disk. Search systems Capture Desktop › Stable The photographed system. Everything is where you left</sub> |
| <img src="cosmic/04-language.png" width="360"> | **language**  <br><sub>Language Changes this session and the installed system. en_US.UTF-8 en_GB.UTF-8 fr_FR.UTF-8 de_DE.UTF-8 es_ES.UTF-8 it_IT.UTF-8 pt_BR.UTF-8</sub> |
| <img src="cosmic/05-keyboard.png" width="360"> | **keyboard**  <br><sub>Keyboard Changes this session and the installed system. us gb fr de es it br jp ru cn Back Continue</sub> |
| <img src="cosmic/06-timezone.png" width="360"> | **timezone**  <br><sub>Time zone Search, then pick where you are. Changes this session and the installed system. Search time zones Europe/Berlin Europe/Paris Europ</sub> |
| <img src="cosmic/07-network.png" width="360"> | **network**  <br><sub>Network The installer needs the network to fetch images. Connected. Recheck Back Continue</sub> |
| <img src="cosmic/08-disk.png" width="360"> | **disk**  <br><sub>Select a disk Everything on the disk you pick will be erased. Samsung SSD 870 EVO 500GB /dev/sda · 465.8 GiB · SATA Extreme SSD /dev/sdc · 9</sub> |
| <img src="cosmic/08-prerelease.png" width="360"> | **prerelease**  <br><sub>Disclaimer This image is not a final release. Do not use it for important data. Back Continue</sub> |
| <img src="cosmic/09-eula.png" width="360"> | **eula**  <br><sub>Terms of use Read and accept the terms to continue. I have read and accept the Terms of Use Back</sub> |
| <img src="cosmic/09-options.png" width="360"> | **options**  <br><sub>Options Sensible defaults are already chosen. Change them only if you need to. System Filesystem btrfs Back Continue</sub> |
| <img src="cosmic/10-account.png" width="360"> | **account**  <br><sub>Create your account You will sign in with this account. It can administer the computer. Account Username alex System Computer name example F</sub> |
| <img src="cosmic/10-rst.png" width="360"> | **rst**  <br><sub>Intel RST A disk may be missing from the list. This computer uses Intel RST (RAID mode). Linux cannot see the solid-state disk until the fir</sub> |
| <img src="cosmic/11-disk.png" width="360"> | **disk**  <br><sub>Select a disk Everything on the disk you pick will be erased. Samsung SSD 870 EVO 500GB /dev/sda · 465.8 GiB · SATA Extreme SSD /dev/sdc · 9</sub> |
| <img src="cosmic/11-tour.png" width="360"> | **tour**  <br><sub>Tour Capture at a glance Everything is where you left it. Back Continue</sub> |
| <img src="cosmic/12-confirm.png" width="360"> | **confirm**  <br><sub>Confirm installation The last screen before anything is written. Everything on /dev/sda will be erased. This cannot be undone. Summary Targe</sub> |
| <img src="cosmic/12-wipe-or-free.png" width="360"> | **wipe or free**  <br><sub>Existing data found This disk already holds data. Install to Free Space Keeps what is there and uses the free space. Use Entire Disk Erases</sub> |
| <img src="cosmic/13-encryption.png" width="360"> | **encryption**  <br><sub>Disk encryption Choose how the disk is locked. Encryption Disk encryption Passphrase You'll type it at every boot. Passphrase Required to un</sub> |
| <img src="cosmic/13-installing.png" width="360"> | **installing**  <br><sub>Installing TunaOS… fisherman is writing the image to disk. [1/8] Partitioning disk [2/8] Formatting EFI partition [3/8] Formatting root file</sub> |
| <img src="cosmic/14-done.png" width="360"> | **done**  <br><sub>TunaOS is installed Remove the installation media and restart the computer. The new system has not started yet, so nothing has checked it. f</sub> |
| <img src="cosmic/14-options.png" width="360"> | **options**  <br><sub>Options Sensible defaults are already chosen. Change them only if you need to. System Filesystem btrfs Back Continue</sub> |
| <img src="cosmic/15-account.png" width="360"> | **account**  <br><sub>Create your account You will sign in with this account. It can administer the computer. Account Username alex System Computer name example F</sub> |
| <img src="cosmic/15-recovery.png" width="360"> | **recovery**  |
| <img src="cosmic/16-cancel.png" width="360"> | **cancel**  <br><sub>Stop the installation? The disk is already changed. If you stop now, it has no system that can start. You can run the installer again. Keep</sub> |
| <img src="cosmic/16-tour.png" width="360"> | **tour**  <br><sub>Tour Capture at a glance Everything is where you left it. Back Continue</sub> |
| <img src="cosmic/17-cancelled.png" width="360"> | **cancelled**  <br><sub>Installation cancelled You stopped the installation. The disk has no system that can start. Run the installer again to finish. Try again Cop</sub> |
| <img src="cosmic/17-confirm.png" width="360"> | **confirm**  <br><sub>Confirm installation The last screen before anything is written. Everything on /dev/sda will be erased. This cannot be undone. Summary Targe</sub> |
| <img src="cosmic/18-installing.png" width="360"> | **installing**  <br><sub>Installing TunaOS… fisherman is writing the image to disk. [1/8] Partitioning disk [2/8] Formatting EFI partition [3/8] Formatting root file</sub> |
| <img src="cosmic/18-offline.png" width="360"> | **offline**  <br><sub>Network The installer needs the network to fetch images. No internet connection. The installer requires an active internet connection. Netwo</sub> |
| <img src="cosmic/19-recovery-key.png" width="360"> | **recovery key**  <br><sub>Recovery key Write it down now. The installer will not show it again. Save your recovery key If your disk fails to unlock automatically, you</sub> |
| <img src="cosmic/20-handoff.png" width="360"> | **handoff**  <br><sub>Handoff The installation is complete. The computer restarts into the installed system. Not now Continue</sub> |
| <img src="cosmic/21-done.png" width="360"> | **done**  <br><sub>TunaOS is installed Remove the installation media and restart the computer. The new system has not started yet, so nothing has checked it. f</sub> |
| <img src="cosmic/22-cancel.png" width="360"> | **cancel**  <br><sub>Stop the installation? The disk is already changed. If you stop now, it has no system that can start. You can run the installer again. Keep</sub> |
| <img src="cosmic/23-cancelled.png" width="360"> | **cancelled**  <br><sub>Installation cancelled You stopped the installation. The disk has no system that can start. Run the installer again to finish. Try again Cop</sub> |
| <img src="cosmic/24-offline.png" width="360"> | **offline**  <br><sub>Network The installer needs the network to fetch images. No internet connection. The installer requires an active internet connection. Netwo</sub> |
| <img src="cosmic/25-failed.png" width="360"> | **failed**  <br><sub>Installation failed The install log above has the details. The disk went away during the installation. Connect it again, or choose another d</sub> |
| <img src="cosmic/26-recovery-key-failed.png" width="360"> | **recovery key failed**  <br><sub>Recovery key Write it down now. The installer will not show it again. Save your recovery key If your disk fails to unlock automatically, you</sub> |
| <img src="cosmic/27-handoff-failed.png" width="360"> | **handoff failed**  <br><sub>Handoff The installation is complete. The handoff failed. io.tunaos.Fisherman.NotInstalled Close Restart now</sub> |

## Niri

Quickshell QML + Go backend. Source: `frontends/niri/`.

<p align="center"><img src="niri/walkthrough.gif" alt="Niri installer walkthrough" width="640"></p>

| | |
|---|---|
| <img src="niri/01-welcome.png" width="360"> | **welcome**  <br><sub>Step 1 of 9 · Welcome ⬢ Welcome to TunaOS Install this system — no download required. Try TunaOS Try TunaOS Install now Install now Enter Co</sub> |
| <img src="niri/02-session.png" width="360"> | **session**  <br><sub>Step 2 of 9 · Session Session Keyboard, language and time zone for this live session and for the installed system, and the network. Keyboard</sub> |
| <img src="niri/03-source.png" width="360"> | **source**  <br><sub>Step 3 of 9 · Source What do you want to install? Search images Install TunaOS Installs to your internal disk. Capture Desktop › Stable ghcr</sub> |
| <img src="niri/04-disk.png" width="360"> | **disk**  <br><sub>Step 4 of 9 · Disk Destination Everything on /dev/sda will be erased. This cannot be undone. Samsung SSD 870 EVO 500GB /dev/sda · 465.8 GiB</sub> |
| <img src="niri/05-encryption.png" width="360"> | **encryption**  <br><sub>Step 5 of 9 · Encryption Disk encryption Encryption protects your files if the disk is lost or stolen. It cannot be turned on later without</sub> |
| <img src="niri/06-account.png" width="360"> | **account**  <br><sub>Step 6 of 9 · Account Your account The account you sign in with. It can administer this computer. Account Username alex Full name Alex Examp</sub> |
| <img src="niri/07-confirm.png" width="360"> | **confirm**  <br><sub>Step 7 of 9 · Confirm Confirm installation ⚠ Everything on /dev/sda will be erased. This cannot be undone. Summary Target disk /dev/sda Imag</sub> |
| <img src="niri/08-progress.png" width="360"> | **progress**  <br><sub>Step 8 of 9 · Installing Installing TunaOS… Step 5 of 8 — Installing OS [1/8] Partitioning disk [2/8] Formatting EFI partition [3/8] Formatt</sub> |
| <img src="niri/09-done.png" width="360"> | **done**  <br><sub>Step 9 of 9 · Done ✓ TunaOS is installed Remove the installation media and restart the computer. The new system has not started yet, so noth</sub> |
| <img src="niri/10-recovery.png" width="360"> | **recovery**  <br><sub>Step 9 of 10 · Recovery key Back Up Recovery Key Save your recovery key If your disk fails to unlock automatically, you will need this recov</sub> |
| <img src="niri/11-tour.png" width="360"> | **tour**  <br><sub>Step 10 of 10 · Done ✓ TunaOS is installed Remove the installation media and restart the computer. The new system has not started yet, so no</sub> |
| <img src="niri/12-cancel-confirm.png" width="360"> | **cancel confirm**  <br><sub>Step 8 of 10 · Installing Installing TunaOS… Step 5 of 8 — Installing OS [1/8] Partitioning disk [2/8] Formatting EFI partition [3/8] Format</sub> |
| <img src="niri/13-cancelled.png" width="360"> | **cancelled**  <br><sub>Step 9 of 9 · Done – Installation cancelled You stopped the installer. The disk can be in an incomplete state: start the installer again bef</sub> |
| <img src="niri/14-offline.png" width="360"> | **offline**  <br><sub>Step 3 of 9 · Source What do you want to install? Search images Install TunaOS Installs to your internal disk. Capture Desktop › Stable ghcr</sub> |
| <img src="niri/15-rst.png" width="360"> | **rst**  <br><sub>Step 4 of 10 · Intel RST Intel RST is on Some disks may be missing This computer uses Intel RST (RAID or VMD mode), which hides NVMe disks f</sub> |
| <img src="niri/16-wipe.png" width="360"> | **wipe**  <br><sub>Step 6 of 11 · Existing data Existing data found /dev/sda holds data with room to spare. Install into the free space, or use the entire disk</sub> |
| <img src="niri/17-prerelease.png" width="360"> | **prerelease**  <br><sub>Step 4 of 12 · Disclaimer Disclaimer Before you install This image is a pre-release. It can break, and it can lose data. Back Back Continue</sub> |
| <img src="niri/18-eula.png" width="360"> | **eula**  <br><sub>Step 5 of 13 · Terms of use Terms of use License agreement Example Terms of Use. These terms govern the trial of this image. I have read and</sub> |
| <img src="niri/19-recovery.png" width="360"> | **recovery**  <br><sub>Step 13 of 14 · Recovery key Back Up Recovery Key Save your recovery key If your disk fails to unlock automatically, you will need this reco</sub> |
| <img src="niri/20-handoff.png" width="360"> | **handoff**  <br><sub>Step 14 of 15 · Handoff Welcome to your new system The live session has become the installed system. Data from this session carries over. Co</sub> |
| <img src="niri/21-qr.png" width="360"> | **qr**  <br><sub>Step 13 of 15 · Recovery key Back Up Recovery Key Save your recovery key If your disk fails to unlock automatically, you will need this reco</sub> |

## XFCE

GTK3 / PyGObject. Source: `frontends/xfce/`.

<p align="center"><img src="xfce/walkthrough.gif" alt="XFCE installer walkthrough" width="640"></p>

| | |
|---|---|
| <img src="xfce/01-welcome.png" width="360"> | **welcome**  <br><sub>Welcome to TunaOS This assistant installs TunaOS on this computer. You'll choose what to install and where; nothing is written to any disk u</sub> |
| <img src="xfce/02-language.png" width="360"> | **language**  <br><sub>Language C.UTF-8 en_US.UTF-8</sub> |
| <img src="xfce/03-keyboard.png" width="360"> | **keyboard**  <br><sub>Keyboard layout af al am ara at au az ba bd be bg br brai bt bw by ca cd ch cm cn custom cz de dk dz ee eg epo es et fi fo fr gb ge gh gn gr</sub> |
| <img src="xfce/04-timezone.png" width="360"> | **timezone**  <br><sub>Time zone Africa/Abidjan Africa/Accra Africa/Addis_Ababa Africa/Algiers Africa/Asmara Africa/Asmera Africa/Bamako Africa/Bangui Africa/Banju</sub> |
| <img src="xfce/05-network.png" width="360"> | **network**  <br><sub>Network Network settings Network settings Recheck Recheck</sub> |
| <img src="xfce/06-prerelease.png" width="360"> | **prerelease**  <br><sub>Disclaimer This is pre-release software. It may break, and it may lose data. Do not install it on a computer that matters.</sub> |
| <img src="xfce/07-eula.png" width="360"> | **eula**  <br><sub>Terms of use The terms could not be loaded. I have read and accept the Terms of Use I have read and accept the Terms of Use Power off Power</sub> |
| <img src="xfce/08-source.png" width="360"> | **source**  <br><sub>What do you want to install? Capture Desktop › Beta Capture Desktop › Beta ghcr.io/example/os:beta Capture Desktop › Edge Capture Desktop ›</sub> |
| <img src="xfce/09-rst.png" width="360"> | **rst**  <br><sub>Intel RST This computer uses Intel RST (RAID mode). Linux cannot see disks behind it. Switch the storage to AHCI in the firmware settings, t</sub> |
| <img src="xfce/10-destination.png" width="360"> | **destination**  <br><sub>Where should TunaOS be installed? Samsung SSD 870 EVO 500GB /dev/sda 465.8 GiB SATA Samsung SSD 870 EVO 500GB /dev/sda 465.8 GiB SATA Extrem</sub> |
| <img src="xfce/11-wipe.png" width="360"> | **wipe**  <br><sub>Existing data found Samsung SSD 870 EVO 500GB holds a partitioned disk. Keep it and install into the free space, or erase the whole disk. In</sub> |
| <img src="xfce/12-setup.png" width="360"> | **setup**  <br><sub>Disk encryption No encryption No encryption Anyone with the disk can read your files. Passphrase Passphrase You'll type it at every boot. TP</sub> |
| <img src="xfce/13-identity.png" width="360"> | **identity**  <br><sub>Name this computer Hostname Confirm password Password Full name Username Your account Language: C.UTF-8; Keyboard: us; Time zone: Etc/UTC</sub> |
| <img src="xfce/14-confirm.png" width="360"> | **confirm**  <br><sub>Confirm installation Target disk: /dev/sda Filesystem: btrfs Encryption: No encryption Hostname: example Image: ghcr.io/example/os:stable Us</sub> |
| <img src="xfce/15-progress.png" width="360"> | **progress**  <br><sub>Installing TunaOS… Do not power off the computer. [1/8] Partitioning disk [2/8] Formatting EFI partition [3/8] Formatting root filesystem [4</sub> |
| <img src="xfce/16-recovery.png" width="360"> | **recovery**  <br><sub>Save your recovery key If your disk fails to unlock automatically, you will need this recovery key to access your data. Save it somewhere sa</sub> |
| <img src="xfce/17-handoff.png" width="360"> | **handoff**  <br><sub>Handoff The system is installed. Continuing restarts the computer into it; remove the install media when asked. Not now Not now Continue Con</sub> |
| <img src="xfce/18-done.png" width="360"> | **done**  <br><sub>TunaOS is installed Remove the installation media and restart the computer. The new system has not started yet, so nothing has checked it. f</sub> |
| <img src="xfce/19-recovery.png" width="360"> | **recovery**  <br><sub>Save your recovery key If your disk fails to unlock automatically, you will need this recovery key to access your data. Save it somewhere sa</sub> |
| <img src="xfce/20-cancelled.png" width="360"> | **cancelled**  <br><sub>Installation cancelled You stopped the installation. The target disk holds an incomplete system: start the installer again to use it. Full l</sub> |

