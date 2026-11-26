# niri: installer walkthrough

Do not edit this page. `tools/walkthrough/render.py` makes it.

These pictures come from the real installer against the mock daemon (`fishermand --mock`). The mock writes to no disk. The machine, the disks and the recovery key are fixtures.

The niri installer runs here in sway with a software renderer. niri itself needs hardware GL, but this installer is a Quickshell app that any wlroots compositor shows the same way.

The main path in other forms: [1024 x 600](small/README.md).

![The main path, animated](walkthrough.webp)

| # | Page | When it shows | Picture |
|---|---|---|---|
| 1 | Requirements | Requirements reports an unmet gate. | [![requirements](01-requirements.png)](01-requirements.png) |
| 2 | Requirements: requirements fatal | UEFI missing. | [![requirements--requirements-fatal](02-requirements--requirements-fatal.png)](02-requirements--requirements-fatal.png) |
| 3 | Try or install | The wizard runs on live media. | [![try-or-install](03-try-or-install.png)](03-try-or-install.png) |
| 4 | Session | Keyboard, language, time zone and network, on one page. | [![session](04-session.png)](04-session.png) |
| 5 | Source | The image to install. | [![source](05-source.png)](05-source.png) |
| 6 | Disclaimer | os-release RELEASE_TYPE is `pre-release` or `experiment`. | [![prerelease](06-prerelease.png)](06-prerelease.png) |
| 7 | Terms of use | The image ships an AppStream component with an `agreement` of type `eula`. | [![eula](07-eula.png)](07-eula.png) |
| 8 | Intel RST | Probe reports Intel RST or VMD remapped NVMe. | [![rst](08-rst.png)](08-rst.png) |
| 9 | Disk | Always. | [![disk](09-disk.png)](09-disk.png) |
| 10 | Disk: no usable disk | No disk. | [![disk--no-usable-disk](10-disk--no-usable-disk.png)](10-disk--no-usable-disk.png) |
| 11 | Existing data found | The chosen disk has status data-detected. | [![wipe-or-free](11-wipe-or-free.png)](11-wipe-or-free.png) |
| 12 | Disk encryption | No TPM 2.0 is present. The page asks for a disk passphrase, twice. | [![encryption](12-encryption.png)](12-encryption.png) |
| 13 | Account | The desktop has no first-boot tool that creates the user, and the image does not make its own user. | [![account](13-account.png)](13-account.png) |
| 14 | Confirm | Always. | [![confirm](14-confirm.png)](14-confirm.png) |
| 15 | Installing | After confirm. | [![install](15-install.png)](15-install.png) |
| 16 | Installing: cancel | Cancel asks first. | [![install--cancel](16-install--cancel.png)](16-install--cancel.png) |
| 17 | Recovery key | The disk is encrypted. | [![recovery-key](17-recovery-key.png)](17-recovery-key.png) |
| 18 | Recovery key: recovery key failed | No key. Do not continue without one. | [![recovery-key--recovery-key-failed](18-recovery-key--recovery-key-failed.png)](18-recovery-key--recovery-key-failed.png) |
| 19 | Handoff | After the install and the recovery key. | [![handoff](19-handoff.png)](19-handoff.png) |
| 20 | Handoff: handoff failed | The handoff failed. | [![handoff--handoff-failed](20-handoff--handoff-failed.png)](20-handoff--handoff-failed.png) |
| 21 | Handoff: soft reboot | The daemon starts the installed system with a soft reboot. | [![handoff--soft-reboot](21-handoff--soft-reboot.png)](21-handoff--soft-reboot.png) |
| 22 | Done | The install ended. | [![done](22-done.png)](22-done.png) |
| 23 | Done: cancelled | Cancelled. Says if the disk changed. | [![done--cancelled](23-done--cancelled.png)](23-done--cancelled.png) |
| 24 | Done: device lost | The disk went away. Says if it changed. | [![done--device-lost](24-done--device-lost.png)](24-done--device-lost.png) |
| 25 | Done: repart error | The partition step failed. Says if it changed. | [![done--repart-error](25-done--repart-error.png)](25-done--repart-error.png) |

## Pages with no picture of their own

| Page | Reason |
|---|---|
| `language` | It is on the `session` page. |
| `keyboard` | It is on the `session` page. |
| `timezone` | It is on the `session` page. |
| `network` | The session page has the network card; there is no page of its own. |
