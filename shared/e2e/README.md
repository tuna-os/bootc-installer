# End-to-end gate

`.github/workflows/e2e.yml` proves the installers work, not only that they
render. `promote.yml` requires every job here, so nothing reaches `prod`
until all five frontends have produced a recipe that the real fisherman
installed and booted.

## Layer 1: the frontend drives its real backend path

| Job | What runs |
|---|---|
| `E2E (gnome)` | `tests/e2e/run_gnome.py`: the wizard from Welcome to Done under Xvfb, `BootcProgress.start()` launches fisherman through `pkexec` |
| `E2E (xfce)` | `frontends/xfce/tests/e2e/run.py`: the wizard from Welcome to Done under Xvfb, `start_install()` launches `pkexec /usr/local/bin/fisherman -` in a bash and pipes the recipe |
| `E2E (niri)` | `frontends/niri/tests/e2e/run.py`: the QML writes its recipe to the stub Process, the same bytes go to the real Go backend on stdin, which launches fisherman |
| `E2E (kde)` | `frontends/kde/tests/e2e.cpp`: `InstallerController::startInstall()` launches `fisherman -` and writes the recipe to its stdin, waits for `installCompleted` |
| `E2E (cosmic)` | the ignored test `e2e_install_path_reaches_fisherman`: `TunaInstaller::stream_fisherman()` launches `fisherman -` and writes the recipe to its stdin |

`setup.sh` prepares the runner:

- builds the real fisherman from the submodule to `/usr/local/lib/tuna-e2e/fisherman.real`;
- installs `fisherman-shim.sh` at `/usr/local/bin/fisherman`, the path all frontends run. Every frontend runs `fisherman -` and pipes the recipe on stdin. The shim refuses an install that is not root, with the code `not_root`, as fisherman does. It keeps what it reads and runs the real `fisherman validate --json` on it. A recipe that fisherman rejects (an unknown key, a disk that is not eligible, a field rule) ends as the real install ends: one `error` event with the `code` and the `field` of the first problem, and exit 1. For a valid recipe the shim then streams fisherman's real progress protocol — newline-delimited JSON, `total_steps` computed from the recipe (`shared/progress/README.md`). It used to stream nine invented `[n/9] ` lines, which is how two frontends could parse a format fisherman never emits and still pass this gate. It never partitions the runner;
- creates a loop disk and writes `/tmp/tuna-e2e/probe.json`, which offers that disk and nothing else. The shim prints this file for `fisherman probe --json`, which every frontend reads its disk list from (`shared/probe/README.md`). The real probe would exclude the loop disk, because it is a loop device and smaller than 50 GiB. It would also offer the runner's own disk. `setup.sh` stops when `lsblk` is missing (package `util-linux`): the real `fisherman validate` asks `lsblk` about the disk and refuses the recipe without it (`disk_unverified`). The disk is always a loop device: fisherman refuses a regular file as `disk` (`disk_not_disk`). With no loop device, `setup.sh` stops with an error. The KDE job runs in a container, so that container is privileged;
- puts `fake-bin/` first on `PATH`: `bootc` (fails), `pkexec` (`sudo -n`, there is no polkit agent). Live media is the probe's answer (`live.is_live` is false in `probe.json`), so no frontend sends an empty image. The shim hands `fisherman validate --json --partial -`, which the frontends run while the user types, to the real fisherman, stdin included.

`check-recipe.py` then judges the recipe the frontend handed over: the real
fisherman accepts it (`fisherman validate --json -`, each problem reported
with its code), it conforms to `shared/recipe/fisherman-recipe.schema.json`,
and it targets the disk the job set up.

It also judges the account against `shared/catalog/README.md`. The recipe
must create a user in `wheel` when the image needs an account, and must
create no user when the catalog says `needs_user_creation` is `false`. The
recipe must also have the `extras` object of the catalog leaf, or no
`extras` key when the leaf has none. The shim has no catalog, as a fisherman
that a Flatpak stages has none. For
that, the driver writes the catalog that it gave the frontend to
`/tmp/tuna-e2e/catalog.json` (or the job passes `--catalog <file>`). An
image that is not in that catalog needs an account.

### The catalog

`catalog.json` here is the one catalog of the five drivers. Each driver
gives it to its frontend and writes it to `/tmp/tuna-e2e/catalog.json`.
`check-recipe.py` fails when that file has other content. The catalog has
these leaves:

| Leaf | Account | What it tests |
|---|---|---|
| `ghcr.io/tuna-os/fisherman/centos-bootc:ssh-enabled` (`default_image`) | yes | the install that the VM job boots with an account; `flatpaks: []` |
| `ghcr.io/tuna-os/fisherman/centos-bootc:ssh-enabled-5c26969…` | no | the same canary at one fixed build, booted with no account; no `flatpaks` key |
| `registry.example/os/composefs:1` | no | a composefs leaf with a choice of filesystems; no VM job installs it |

The two canary leaves are the SSH-enabled CentOS Stream 10 image that
fisherman's `build-ssh-images.yml` builds, with `bootloader: grub2`. Thus
the VM job can install the recipe of the frontend as it is and reach the
result over SSH. The second leaf has a fixed build tag because two leaves
must have different references. The `extras` object is on the parent of
the two canary leaves. The
`fallback_flatpaks` list is not empty, so a frontend that sends it fails.

| Driver | Leaf that it installs | Account in the VM |
|---|---|---|
| GNOME (`tests/e2e/run_gnome.py`) | `default_image` | yes: the driver types `e2euser` on the user step |
| XFCE (`frontends/xfce/tests/e2e/run.py`) | `default_image` | yes: the driver types `e2euser` on the identity page |
| KDE (`frontends/kde/tests/e2e.cpp`) | `default_image` | yes. Also German locale and keyboard, `Europe/Berlin` and LUKS (#325) |
| Niri (`frontends/niri/tests/e2e/run.py`) | `default_image` (the branding's) | yes |
| COSMIC (`e2e_install_path_reaches_fisherman`) | the leaf of the same product with no account | no |

No driver names an image of its own: each one gets its leaf from the
catalog.

The KDE and Niri drivers also select a leaf with no account first, and
make sure that the account step goes away.

## Layer 2: the recipe is installed and booted

`E2E (install <frontend>)` downloads that recipe and runs `vm-install.sh`:
fisherman's own bootcrew tooling installs it onto a loop disk, enables SSH
in the result, verifies the layout and boots it in QEMU until `bootc status`
answers over SSH.

The VM job installs the recipe of the frontend as it is (#322). The image,
the bootloader and the Flatpak list come from the catalog leaf. Only
`disk` can change. The frontend wrote the loop device of the runner of the
first job. `vm-install.sh` attaches its disk at the same path when that
device is free here, and then the two recipes are byte for byte the same.
When another device has the path, the disk is the next free loop device.

`check-recipe.py --vm` writes the copy and fails when the copy is more
than the frontend's bytes with that one value replaced. A leaf with no
`flatpaks` key gives a recipe with no key, and fisherman copies the system
Flatpaks of the runner, as on a real machine. The runner has none.

When the recipe has `locale`, `keyboard`, `timezone` or encryption, the
boot runs the guest check `vm-checks/region.sh` through fisherman's
`BOOTCREW_GUEST_CHECKS`. The check reads `/etc/locale.conf`,
`/etc/vconsole.conf`, `/etc/localtime`, `localectl status` and
`timedatectl` in the booted system, and compares them with the recipe. For
an encrypted root it finds `rd.vconsole.keymap=` on the kernel command
line and the root on an open LUKS device. fisherman's `luks-unlock.py`
types the passphrase at the prompt, as in fisherman's own LUKS VM entries.
It sends US key codes, so the KDE passphrase has only keys that are the
same on a US and a German layout. `E2E (install kde)` runs this check
(#325).

The SSH-enable step is fisherman's `scripts/enable-ssh-installed.sh` and
needs the submodule at `7c3c738` or later: that revision writes root's
`authorized_keys` into the stateroot `var/` the guest mounts (older ones
wrote it into the deployment's own `var/`, which the guest never sees, so
sshd rejected every probe) and adds an `sshd_config.d` drop-in. The BLS
entries are then patched like fisherman's `bootcrew-ci-test` does
(`console=ttyS0` so the serial log in the artifact shows the boot,
`enforcing=0` because the injected files carry no SELinux labels). The
artifact `e2e-install-<frontend>` holds the recipe that the VM job
installed, the install log and the boot log.

## Run it locally

```bash
bash shared/e2e/setup.sh                       # needs go, sudo, losetup
export PATH=$PWD/shared/e2e/fake-bin:$PATH
xvfb-run -a python3 tests/e2e/run_gnome.py     # after a meson build
python3 shared/e2e/check-recipe.py gnome
```
