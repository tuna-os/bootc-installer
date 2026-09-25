# Frontend parity

The GNOME frontend is the reference: it is the one that shipped and has
end-to-end tests. This page records what each of the other four renders
of the same contract. A gap is then a line here, not a surprise on an
ISO. `docs/DESIGN-AUDIT.md` covers how each looks against its desktop;
this page covers what each does.

## Branding copy keys

Every key in `shared/branding/copy-defaults.json` is a line a product may
rebrand. A frontend "renders" a key when the line appears where the table
says; "hidden" means the frontend shows nothing for an empty value.

| Key | GNOME | KDE | COSMIC | Niri | XFCE |
|---|---|---|---|---|---|
| `welcome_title` | page header | heading | title1 | heading | page title |
| `welcome_subtitle` | header subtitle, hidden | label, hidden | body, hidden | label, hidden | label, hidden |
| `welcome_install` | install row title | live-system radio | (no row: single image) | (no row) | live-system radio |
| `welcome_install_subtitle` | install row subtitle | no | no | no | no |
| `welcome_button` | (row activates) | Next | forward button | button | Next |
| `confirm_title` | page header | step heading unchanged; body heading | page title | heading | page title |
| `confirm_subtitle` | header subtitle | italic label, hidden | page subtitle | label, hidden | label, hidden |
| `confirm_body` | dim label, hidden | label, hidden | body, hidden | label, hidden | label, hidden |
| `confirm_warning` | (summary warning row, own text) | inline message | warning card | warning line | warning row |
| `confirm_button` | pill button | Next button | forward button | button | Next button |
| `confirm_quotes` | random line per language | no | no | no | no |
| `progress_title` | step label via `{product}` | label | page title | heading | page title |
| `progress_note` | no | label | warning caption | no | no |
| `done_title` | page header | heading | title2 | heading | headline |
| `done_subtitle` | header subtitle (+ elapsed time) | label | body | label | label |
| `done_restart` | Reboot Now button | Restart button | suggested button | button | Reboot button |
| `done_failed_title` | page header | heading | title2 | heading | headline |
| `store_label` + `store_url` | done page link (+ QR from `assets.store_qr`, US locale) | done page link | done page link | done page link | done page link |
| `assets.welcome_image`, `assets.complete_image` | tour pages | no | no | welcome logo disc (`logo`) | no |

Outside the contract, under `extensions.gnome`: the tour page text, the
install video and the credits file. They are the last GNOME-only features.
The plan is to port the tour artwork (welcome and complete images) to the
other four. Video and credits then leave the contract; nothing else gets
them.

All five render the identity keys (`name`, `id`, `default_hostname`,
`default_image`, URLs); see `shared/branding/README.md`.

## Features

| Feature | GNOME | KDE | COSMIC | Niri | XFCE |
|---|---|---|---|---|---|
| Image catalog choice | yes (fisherman `images.json`) | no (live or `default_image`) | no (live or `default_image`) | no (live or `default_image`) | yes |
| Live-ISO install without download | yes | yes | yes | yes | yes |
| Offline image stores | yes | yes | yes | yes | yes |
| Disk choice with erase warning | yes | yes | yes | yes | yes |
| Filesystem choice | yes | yes | yes | no (xfs) | yes (Advanced) |
| Encryption: none / passphrase | yes | yes | yes | yes | yes |
| Encryption: TPM / TPM + passphrase | yes | yes | yes | yes | yes |
| Recovery key page after TPM enrolment | yes | no | no | no | no |
| Hostname | generated, editable on confirm | field | field | field on confirm | field |
| User account | yes (companion or wizard) | no | no | no | yes |
| Phone companion (QR) | yes | no | no | no | no |
| Windows data migration (slurp) | yes | no | no | no | no |
| Keyboard / language / timezone | yes | no | no | no | no |
| Progress bar from fisherman's protocol | yes | yes | yes | yes | yes |
| Restart from the done page | yes | yes | yes | yes | yes |
| Show log after failure | yes | log path | log in page | log in page | log tail |
| Screenshot walkthrough + parity report | yes | yes | yes | yes | yes |
| End-to-end gate (real install and boot) | yes | yes | yes | yes | yes |

## Closing the gaps, in order

1. ~~**Encryption set** (KDE, XFCE)~~ — **not a gap.** Both offer TPM and
   TPM + passphrase today. Each hides the two choices when
   `/sys/class/tpm/tpm0` is missing. No CI runner has a TPM, so the capture
   showed two choices and this table copied it. Set
   `BOOTC_INSTALLER_FAKE_TPM=1` to capture all four.
2. ~~**Progress bar**~~ — **closed.** All five read
   `shared/progress/README.md` now. This entry used to say fisherman emits
   `[n/9]`, which it never has: three frontends were built on that claim and
   their bars sat at zero for every real install, while fixtures written in
   the same invented shape photographed one moving. Drive the bar from
   `cumulative_pct`, never `step / total_steps` — `total_steps` varies with
   the recipe and one step carries 87% of the time.
3. **Recovery key page** (all four): fisherman prints the key after TPM
   enrolment; GNOME's `views/recovery_key.py` is the reference.
4. **User account** (KDE, COSMIC, Niri): a username, full name and
   password step that writes the recipe's `user` block, as XFCE does.
5. **Store and tour assets** (all four): only worth it where the desktop
   has a place for artwork. Every resolver already resolves the keys, so
   this is view work only.
6. **Companion, slurp, locale steps**: GNOME-only by design for now. The
   contract keeps their copy keys out of `copy-defaults.json`, so nothing
   else pretends to have them.
