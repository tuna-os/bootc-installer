# Frontend parity

The GNOME frontend is the reference: it is the one that shipped and has
end-to-end tests. This page records what each of the other four renders
of the same contract. Each gap then shows as a line here, not as a surprise on an
ISO. `docs/DESIGN-AUDIT.md` covers how each looks against its desktop;
this page covers what each does.

## Branding copy keys

Every key in `shared/branding/copy-defaults.json` is a line a product may
rebrand. A frontend "renders" a key when the line appears where the table
says. "Hidden" means the frontend shows nothing for an empty value. "No"
means the frontend shows its own hardcoded text, so a product cannot
rebrand that line.

`tests/unit/test_copy_coverage.py` enforces the "no" cells. It scans each
frontend for every key and compares what it finds against its own
`KNOWN_GAPS` table. An unlisted gap fails the test. So does a listed gap
that the frontend has since closed. Before that check, four cells here
claimed a render that nobody had wired up.

| Key | GNOME | KDE | COSMIC | Niri | XFCE |
|---|---|---|---|---|---|
| `welcome_title` | page header | heading | title1 | heading | page title |
| `welcome_subtitle` | header subtitle, hidden | label, hidden | body, hidden | label, hidden | label, hidden |
| `welcome_install` | install row title | no (own body text) | no (no install row) | live-system row | live-system radio |
| `welcome_install_subtitle` | install row subtitle | no | no | live-system row subtitle | live-system radio subtitle |
| `welcome_button` | no (row activates, own label) | Next button on welcome | forward button | button | Next button on welcome |
| `requirements_title` | gate window text (blocks) | welcome inline message | welcome warning row | gate dialog (blocks) | welcome warning row |
| `requirements_ram` | RAM gate window text | welcome inline message line | welcome warning row line | welcome warning line | welcome warning row line |
| `requirements_cpu` | CPU gate window text | welcome inline message line | welcome warning row line | welcome warning line | welcome warning row line |
| `requirements_uefi` | UEFI gate window text | welcome inline message line | welcome warning row line | welcome warning line | welcome warning row line |
| `encryption_none_label` | confirm summary row | radio row, confirm row | dropdown entry, confirm row | list row, confirm row | radio, confirm summary |
| `encryption_none_description` | no (an on/off switch, no row for this choice) | radio row description | dropdown description | list row subtitle | caption under the radio |
| `encryption_luks_passphrase_label` | confirm summary row | radio row, confirm row | dropdown entry, confirm row | list row, confirm row | radio, confirm summary |
| `encryption_luks_passphrase_description` | subtitle of the encrypt switch | radio row description | dropdown description | list row subtitle | caption under the radio |
| `encryption_tpm2_luks_label` | confirm summary row | radio row, confirm row | dropdown entry, confirm row | list row, confirm row | radio, confirm summary |
| `encryption_tpm2_luks_description` | no (the page cannot select this type) | radio row description | dropdown description | list row subtitle | caption under the radio |
| `encryption_tpm2_luks_passphrase_label` | confirm summary row | radio row, confirm row | dropdown entry, confirm row | list row, confirm row | radio, confirm summary |
| `encryption_tpm2_luks_passphrase_description` | subtitle of the TPM switch | radio row description | dropdown description | list row subtitle | caption under the radio |
| `confirm_title` | page header | step heading | page title | heading | page title |
| `confirm_subtitle` | header subtitle | italic label, hidden | page subtitle | label, hidden | label, hidden |
| `confirm_body` | dim label, hidden | label, hidden | body, hidden | label, hidden | label, hidden |
| `confirm_warning` | summary warning row (own group above the summary, `{disk}` filled) | inline message | warning card | warning line | warning row naming the selected disk |
| `confirm_warning_removable` | summary warning row (replaces `confirm_warning` when the target disk is removable, `{disk}` filled) | inline message (replaces `confirm_warning`) | warning card (replaces `confirm_warning`) | warning line (replaces `confirm_warning`) | warning row (replaces `confirm_warning`) |
| `confirm_button` | pill button | Next button | forward button | button | Next button |
| `confirm_quotes` | random line per language | no | no | no | no |
| `progress_title` | image-writing step label (centred title) | label | page title | heading | page title |
| `progress_note` | dim caption under the bar | label | warning caption | caption | dim label under the bar |
| `step_prepare_disk` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_partition` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_format_efi` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_luks` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_format_root` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_mount` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_format_var` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_install_os` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_tpm2_enroll` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_flatpaks` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_configure` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `step_finalize` | step label on the progress page | "Step N of M" caption | "Step N of M" caption | "Step N of M" caption | step label under the title |
| `recovery_key_title` | page heading | heading | heading | heading | heading |
| `recovery_key_body` | label | label | body | label | label |
| `recovery_key_copy` | copy button tooltip | copy button | copy button | copy button | copy button |
| `recovery_key_ack` | checkbox | checkbox | checkbox | checkbox | checkbox |
| `done_title` | page header | heading | title2 | heading | headline |
| `done_subtitle` | header subtitle (+ elapsed time) | label | body | label | label |
| `done_restart` | Reboot Now button | Restart button | suggested button | button | suggested button beside Close |
| `done_failed_title` | page header | heading | title2 | heading | headline |
| `done_cancelled_title` | page header, after a confirmed Cancel or fisherman exit code 130 | heading | no (failure page, #299) | no (failure page, #299) | headline, after a confirmed Cancel or fisherman exit code 130 |
| `validate_*` | error line under the hostname (disk and confirm pages) and the username | inline message on the encryption step (passphrase) and the confirm step (hostname) | hostname row description; encryption row description | line under the hostname (confirm) and under the passphrase | line under the hostname, the username and the encryption choice |
| `store_label` | done page link to `store_url` (+ QR from `assets.store_qr`, US locale) | done page link | done page link | done page link | done page link |
| `logo` | product icon (GNOME file adapter tracked separately) | theme/file on welcome and successful done, after the asset; else `system-software-install` / `checkmark` | theme/file on welcome and successful done, after the asset; else `computer-symbolic` in an accent disc / the check | theme/file on welcome and successful done | theme/file/resource on welcome and successful done |
| `assets.welcome_image`, `assets.complete_image` | tour pages | welcome / successful done artwork, before `logo` | welcome / successful done artwork, before `logo` | welcome logo disc (`logo`) | no |

The eight `encryption_*` keys name the four types of encryption in the
recipe. The order of the types is the `encryption.type` enum in
`shared/recipe/fisherman-recipe.schema.json`. All five frontends use the same
words on the encryption page and on the confirm page.
`tests/unit/test_encryption_choices.py` makes sure that each frontend offers
those types in that order.

The confirm pages used to disagree. KDE showed "None" and "Passphrase
(LUKS)". GNOME showed its own phrases. COSMIC, Niri and Xfce showed the
recipe id, for example `luks-passphrase`. GNOME has a switch and a TPM
switch, not a list. Thus it shows only the two descriptions that its
switches can select.

The twelve `step_*` keys label the install step that runs. fisherman puts a
stable `step_id` on each step event, and each frontend reads the key
`step_<step_id>`. An event without a `step_id`, or an id with no copy line,
shows fisherman's `step_name`.

Before this, Niri showed the raw step name.
GNOME, Xfce, KDE and COSMIC each had their own table of the same words, so a
product could not change them. Those tables stay only as the fallback for a
fisherman without `step_id`. All five also draw the bar from fisherman's
`overall_pct` (`shared/progress/README.md`). Thus the bar now moves during
the Flatpak copy, where the old calculation in each frontend stopped.
XFCE hides its step label when it repeats the page title, which is the case
for `step_install_os` with the default copy.

The `validate_*` keys word fisherman's problems. Each frontend sends its
fields to `fisherman validate --json --partial -` while the user types and
shows each problem through the key `validate_<code>`
(`shared/recipe/README.md`). The codes are fisherman's
(`fisherman/docs/VALIDATE.md`), so the table has one row for the family. A
code with no copy line shows fisherman's own message. Before this, only
XFCE checked the hostname, and a username such as `root` failed after the
OS was on disk.

Outside the contract, under `extensions.gnome`: the tour page text, the
install video and the credits file. They are the last GNOME-only features.
The plan is to port the tour artwork (welcome and complete images) to the
other four. Video and credits then leave the contract; nothing else gets
them.

All five render the identity keys (`name`, `id`, `default_hostname`, URLs);
see `shared/branding/README.md`. Off live media, COSMIC, Niri and XFCE do
not use `default_image` yet (#289).

## Features

<!-- features:begin (generated by shared/walkthrough/features.py; edit the manifests) -->

| Feature | GNOME | KDE | COSMIC | Niri | XFCE |
|---|---|---|---|---|---|
| Image catalog choice (fisherman `images.json`) | yes (tree, search) | yes (disk step, breadcrumb rows, search) | yes (and a custom URL row) | yes (flat list) | yes (flat list, product and channel in each row, search) |
| Image selected at start, off live media | catalog `default_image`, then branding `default_image` if the catalog has it; else you must pick | branding `default_image`, then the catalog's; else you must pick | first row of the catalog (#289) | first name in the alphabet (#289) | branding `default_image`, then catalog `default_image`; else you must pick |
| Catalog fields that reach the recipe | all | all of the contract (shared/catalog) | image and Flatpaks only (#286) | image, filesystem, bootloader, composefs, hostname | all |
| Live-ISO install without download (live media from `fisherman probe --json`) | yes | yes | yes | yes | yes |
| Offline image stores (found by fisherman on the host) | yes | yes | yes | yes | yes |
| Recipe on fisherman's stdin, no recipe file | yes | yes | yes | yes | yes |
| fisherman staged from the Flatpak, with a SHA256 check | yes | yes (probe, validate and install) | no (#290) | no (#290) | yes |
| Fields checked by `fisherman validate --json --partial` | hostname, username | hostname, username, passphrase, filesystem with composefs | hostname, passphrase, username | hostname, username, passphrase, filesystem | hostname, username, passphrase, filesystem |
| Disk choice with erase warning | yes | yes | yes | yes | yes |
| Disk list from `fisherman probe --json` (`shared/probe/`) | yes | yes | yes | yes | yes |
| Disk row: model (path when unknown), path, size label, bus | yes | yes | yes | yes | yes |
| Disk probe failure shown on the disk page | yes | yes | yes | yes | yes |
| RAM / CPU / UEFI check (fisherman's `system.unmet`) | blocks (gate window) | holds Next; override for RAM and CPU | blocks (requirements page) | blocks (gate dialog) | blocks (gate window) |
| Connectivity check | blocks (connection-check step); the Wi-Fi page is not in the bundled recipe | blocks on welcome and confirm; image registry first; Network settings action | blocks (network page) | status line, does not block (#301) | blocks on confirm; probes the image's registry first; Network settings button |
| Filesystem choice | yes (list from the image) | yes (the choices of the image) | xfs or btrfs | yes (Advanced) | yes (Advanced, list from the image) |
| Encryption: none / passphrase | yes | yes | yes | yes | yes |
| Passphrase typed twice, Next held on a mismatch | yes | yes | yes | yes | yes |
| Encryption: TPM / TPM + passphrase | yes | yes | yes | yes | yes |
| Recovery key shown after a `tpm2-luks` install | yes | yes | yes | yes | yes |
| Hostname | generated, editable on confirm | no (branding default, shown on confirm) | field | field on confirm | field, first value from the image |
| User account, when the image needs one | yes | yes | yes | yes | yes |
| Default when the catalog does not set `needs_user_creation` (#288) | no account | account | no account | account | account |
| Account password | twice, reveal, strength | twice, reveal, strength | twice, reveal | twice, no reveal (#295) | twice, reveal |
| Account groups | wheel and developer groups, operator override | shared list, operator override | wheel (#302) | wheel (#302) | wheel, sudo and developer groups, operator override |
| Phone companion (QR) | yes (TLS on the LAN address only); shows when the image needs an account, and fills the account page | no | yes (plain HTTP, #293) | no | no |
| Keyboard / language / timezone (#292) | pages exist; not in the bundled recipe | pickers on welcome, marked as not applied (#292) | applied to the live session | applied to the live session (#291) | keyboard only, for this session; says so |
| Keyboard / language / timezone in the installed system | no | no | no | no | no |
| Cancel a running install (#299) | Cancel button, window close and Ctrl+Q: each asks first; a cancelled page follows | Cancel button, asks first; cancelled page | quit dialog | Cancel button, does not ask | Cancel button and window close: each asks first; a cancelled page follows |
| `--autoinstall` | yes (the recipe is validated first) | no | no | no | yes (the recipe is validated first) |
| Translatable UI | gettext, one domain (`bootc-installer`); branding copy stays in one language (#311) | strings marked (qsTr, tr); no catalog ships (#300) | no (#300) | no (#300) | gettext, one domain (`tuna-installer-xfce`), lint test; no translation ships yet; branding copy stays in one language (#311) |
| Progress bar from fisherman's protocol | yes | yes | yes | yes | yes |
| Restart from the done page | yes | yes | yes | yes | yes |
| Show log after failure | yes (recovery key redacted) | log path | log in page | log in page | log tail |
| Recovery key kept out of log files (#337) | yes (log file scrubbed; dialog and clipboard redacted) | yes (log file and clipboard copy redacted) | no log file | no (#337) | no (#337) |
| Screenshot walkthrough + parity report | yes | yes | yes | yes | yes |
| End-to-end gate (real install and boot) | yes | yes | yes | yes | yes |

<!-- features:end -->

`shared/walkthrough/features.py` writes this table. Do not edit it here.
Each frontend has a manifest with one cell for each row:
`frontends/<name>/features.json`, and `shared/walkthrough/features-gnome.json`
for GNOME. `shared/walkthrough/feature-rows.json` has the rows.

To change a cell, edit the manifest of that frontend and run
`python3 shared/walkthrough/features.py`.
`tests/unit/test_parity_features.py` fails when the table and the manifests
do not agree. Some rows have evidence: a walkthrough screen or an E2E job.
For those rows, the test also fails when a cell says "yes" and the evidence
is not there.

The cells were read from the code on 2026-11-10, after #280 gave the other
four frontends a catalog, gates, locale pages and a companion.

## Closing the gaps, in order

1. ~~**Encryption set** (KDE, XFCE)~~ — **not a gap.** Both offer TPM and
   TPM + passphrase today. Each hides the two choices when fisherman's
   `tpm.usable` is false. No CI runner has a TPM. The capture thus showed
   only two of the choices, and this table copied it. The captures now read
   `shared/probe/fixtures/laptop.json`, which has a usable TPM, so they show
   all four.
2. ~~**Progress bar**~~ — **closed.** All five read
   `shared/progress/README.md` now. This entry said that fisherman emits
   `[n/9]`. It does not. Three frontends used that claim, so their bars
   stayed at zero. Their fixtures used the same shape, so the pictures
   showed a bar that moved. Drive the bar from `cumulative_pct`, not from
   `step / total_steps`: `total_steps` changes with the recipe, and one
   step takes 87% of the time.
3. ~~**Recovery key page**~~ — closed. fisherman prints the key after TPM
   enrolment. GNOME shows a page. The other four show a panel on the done
   screen. Each holds the restart button until the user acknowledges the
   key (#129).
4. **User account**: all five have the step, and each shows it only when
   the image needs an account. Three things are still open. The frontends
   do not agree on the default when the catalog does not set
   `needs_user_creation` (#288). Four of them put the account only in
   `wheel` (#302). XFCE asks for the password once (#295).
5. **Store and tour assets**: only worth it where the desktop has a place
   for artwork. Every resolver already resolves the keys, so this is view
   work only. KDE and COSMIC now show `welcome_image` and
   `complete_image` as the welcome and done artwork, ahead of `logo`.
6. **Companion and locale steps**: no longer GNOME-only. COSMIC and XFCE
   have a companion, over plain HTTP (#293). All five have locale pages, and
   they mean five different things (#292). No frontend sends a locale, a
   keymap or a time zone to the installed system: the recipe has no field
   for them (tuna-os/fisherman#405). Windows data migration (slurp) is not
   an installer feature at all: it belongs to wootc, and no frontend here
   offers it.
