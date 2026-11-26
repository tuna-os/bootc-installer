# niri: installer walkthrough, 1024 x 600

Do not edit this page. `tools/walkthrough/render.py` makes it.

These pictures come from the real installer against the mock daemon (`fishermand --mock`). The mock writes to no disk. The machine, the disks and the recovery key are fixtures.

The niri installer runs here in sway with a software renderer. niri itself needs hardware GL, but this installer is a Quickshell app that any wlroots compositor shows the same way.

![The main path, animated](walkthrough.gif)

| # | Page | When it shows | Picture |
|---|---|---|---|
| 1 | Try or install | The wizard runs on live media. | [![try-or-install](01-try-or-install.png)](01-try-or-install.png) |
| 2 | Session | Keyboard, language, time zone and network, on one page. | [![session](02-session.png)](02-session.png) |
| 3 | Source | The image to install. | [![source](03-source.png)](03-source.png) |
| 4 | Disk | Always. | [![disk](04-disk.png)](04-disk.png) |
| 5 | Disk encryption | No TPM 2.0 is present. The page asks for a disk passphrase, twice. | [![encryption](05-encryption.png)](05-encryption.png) |
| 6 | Account | The desktop has no first-boot tool that creates the user, and the image does not make its own user. | [![account](06-account.png)](06-account.png) |
| 7 | Confirm | Always. | [![confirm](07-confirm.png)](07-confirm.png) |
| 8 | Recovery key | The disk is encrypted. | [![recovery-key](08-recovery-key.png)](08-recovery-key.png) |
| 9 | Handoff | After the install and the recovery key. | [![handoff](09-handoff.png)](09-handoff.png) |
| 10 | Done | The install ended. | [![done](10-done.png)](10-done.png) |
