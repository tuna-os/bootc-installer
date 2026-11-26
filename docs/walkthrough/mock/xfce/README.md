# XFCE: installer walkthrough

Do not edit this page. `tools/walkthrough/render.py` makes it.

These pictures come from the real installer against the mock daemon (`fishermand --mock`). The mock writes to no disk. The machine, the disks and the recovery key are fixtures.

The main path in other forms: [dark style](dark/README.md), [1024 x 600](small/README.md).

![The main path, animated](walkthrough.gif)

| # | Page | When it shows | Picture |
|---|---|---|---|
| 1 | Requirements | Requirements reports an unmet gate. | [![requirements](01-requirements.png)](01-requirements.png) |
| 2 | Requirements: requirements fatal | UEFI missing. | [![requirements--requirements-fatal](02-requirements--requirements-fatal.png)](02-requirements--requirements-fatal.png) |
| 3 | Try or install | The wizard runs on live media. | [![try-or-install](03-try-or-install.png)](03-try-or-install.png) |
| 4 | Language | Always. | [![language](04-language.png)](04-language.png) |
| 5 | Keyboard layout | Always. | [![keyboard](05-keyboard.png)](05-keyboard.png) |
| 6 | Time zone | Always. | [![timezone](06-timezone.png)](06-timezone.png) |
| 7 | Network | The image needs a download. | [![network](07-network.png)](07-network.png) |
| 8 | Disclaimer | os-release RELEASE_TYPE is `pre-release` or `experiment`. | [![prerelease](08-prerelease.png)](08-prerelease.png) |
| 9 | Terms of use | The image ships an AppStream component with an `agreement` of type `eula`. | [![eula](09-eula.png)](09-eula.png) |
| 10 | Intel RST | Probe reports Intel RST or VMD remapped NVMe. | [![rst](10-rst.png)](10-rst.png) |
| 11 | Disk | Always. | [![disk](11-disk.png)](11-disk.png) |
| 12 | Disk: no usable disk | No disk. | [![disk--no-usable-disk](12-disk--no-usable-disk.png)](12-disk--no-usable-disk.png) |
| 13 | Existing data found | The chosen disk has status data-detected. | [![wipe-or-free](13-wipe-or-free.png)](13-wipe-or-free.png) |
| 14 | Disk encryption | No TPM 2.0 is present. The page asks for a disk passphrase, twice. | [![encryption](14-encryption.png)](14-encryption.png) |
| 15 | Account | The desktop has no first-boot tool that creates the user, and the image does not make its own user. | [![account](15-account.png)](15-account.png) |
| 16 | Confirm | Always. | [![confirm](16-confirm.png)](16-confirm.png) |
| 17 | Installing | After confirm. | [![install](17-install.png)](17-install.png) |
| 18 | Installing: cancel | Cancel asks first. | [![install--cancel](18-install--cancel.png)](18-install--cancel.png) |
| 19 | Recovery key | The disk is encrypted. | [![recovery-key](19-recovery-key.png)](19-recovery-key.png) |
| 20 | Recovery key: recovery key failed | No key. Do not continue without one. | [![recovery-key--recovery-key-failed](20-recovery-key--recovery-key-failed.png)](20-recovery-key--recovery-key-failed.png) |
| 21 | Handoff | After the install and the recovery key. | [![handoff](21-handoff.png)](21-handoff.png) |
| 22 | Handoff: handoff failed | The handoff failed. | [![handoff--handoff-failed](22-handoff--handoff-failed.png)](22-handoff--handoff-failed.png) |
| 23 | Handoff: soft reboot | The daemon starts the installed system with a soft reboot. | [![handoff--soft-reboot](23-handoff--soft-reboot.png)](23-handoff--soft-reboot.png) |
| 24 | Done | The install ended. | [![done](24-done.png)](24-done.png) |
| 25 | Done: device lost | The disk went away. Says if it changed. | [![done--device-lost](25-done--device-lost.png)](25-done--device-lost.png) |
| 26 | Done: repart error | The partition step failed. Says if it changed. | [![done--repart-error](26-done--repart-error.png)](26-done--repart-error.png) |

## Pages with no picture of their own

| Page | Kind | Reason |
|---|---|---|
| `done--cancelled` | Defect (tuna-os/installer#482) | The cancel dialog draws no buttons (gates.ConfirmCancelDialog has no show_all), so the walk cannot confirm a cancel. |
