# XFCE: installer walkthrough, 1024 x 600

Do not edit this page. `tools/walkthrough/render.py` makes it.

These pictures come from the real installer against the mock daemon (`fishermand --mock`). The mock writes to no disk. The machine, the disks and the recovery key are fixtures.

![The main path, animated](walkthrough.webp)

| # | Page | When it shows | Picture |
|---|---|---|---|
| 1 | Try or install | The wizard runs on live media. | [![try-or-install](01-try-or-install.png)](01-try-or-install.png) |
| 2 | Language | Always. | [![language](02-language.png)](02-language.png) |
| 3 | Keyboard layout | Always. | [![keyboard](03-keyboard.png)](03-keyboard.png) |
| 4 | Time zone | Always. | [![timezone](04-timezone.png)](04-timezone.png) |
| 5 | Disk | Always. | [![disk](05-disk.png)](05-disk.png) |
| 6 | Disk encryption | No TPM 2.0 is present. The page asks for a disk passphrase, twice. | [![encryption](06-encryption.png)](06-encryption.png) |
| 7 | Account | The desktop has no first-boot tool that creates the user, and the image does not make its own user. | [![account](07-account.png)](07-account.png) |
| 8 | Confirm | Always. | [![confirm](08-confirm.png)](08-confirm.png) |
| 9 | Recovery key | The disk is encrypted. | [![recovery-key](09-recovery-key.png)](09-recovery-key.png) |
| 10 | Handoff | After the install and the recovery key. | [![handoff](10-handoff.png)](10-handoff.png) |
| 11 | Done | The install ended. | [![done](11-done.png)](11-done.png) |
