# GNOME (gnome-setup): installer walkthrough, 1024 x 600

Do not edit this page. `tools/walkthrough/render.py` makes it.

These pictures come from the real installer against the mock daemon (`fishermand --mock`). The mock writes to no disk. The machine, the disks and the recovery key are fixtures.

![The main path, animated](walkthrough.gif)

| # | Page | When it shows | Picture |
|---|---|---|---|
| 1 | Try or install | The wizard runs on live media. | [![try-or-install](01-try-or-install.png)](01-try-or-install.png) |
| 2 | Language | Always. | [![language](02-language.png)](02-language.png) |
| 3 | Keyboard layout | Always. | [![keyboard](03-keyboard.png)](03-keyboard.png) |
| 4 | Disk | Always. | [![disk](04-disk.png)](04-disk.png) |
| 5 | Disk encryption | No TPM 2.0 is present. The page asks for a disk passphrase, twice. | [![encryption](05-encryption.png)](05-encryption.png) |
| 6 | Confirm | Always. | [![confirm](06-confirm.png)](06-confirm.png) |
| 7 | Recovery key | The disk is encrypted. | [![recovery-key](07-recovery-key.png)](07-recovery-key.png) |
| 8 | Done | The install ended. | [![done](08-done.png)](08-done.png) |
