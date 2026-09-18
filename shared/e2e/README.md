# End-to-end gate

`.github/workflows/e2e.yml` proves the installers work, not only that they
render. `promote.yml` requires every job here, so nothing reaches `prod`
until all five frontends have produced a recipe that the real fisherman
installed and booted.

## Layer 1: the frontend drives its real backend path

| Job | What runs |
|---|---|
| `E2E (gnome)` | `tests/e2e/run_gnome.py`: the wizard from Welcome to Done under Xvfb, `BootcProgress.start()` launches fisherman through `pkexec` |
| `E2E (xfce)` | `frontends/xfce/tests/e2e/run.py`: the wizard from Welcome to Done under Xvfb, `start_install()` launches `sudo /usr/local/bin/fisherman` |
| `E2E (niri)` | `frontends/niri/tests/e2e/run.py`: the QML writes its recipe to the stub Process, the same bytes go to the real Go backend on stdin, which launches fisherman |
| `E2E (kde)` | `frontends/kde/tests/e2e.cpp`: `InstallerController::startInstall()` writes the recipe and launches fisherman, waits for `installCompleted` |
| `E2E (cosmic)` | the ignored test `e2e_install_path_reaches_fisherman`: `TunaInstaller::run_fisherman()` writes the recipe and launches fisherman |

`setup.sh` prepares the runner:

- builds the real fisherman from the submodule to `/usr/local/lib/tuna-e2e/fisherman.real`;
- installs `fisherman-shim.sh` at `/usr/local/bin/fisherman`, the path all frontends run. The shim keeps the recipe, runs the real `fisherman validate` on it, then streams the nine `[n/9]` step lines. It never partitions the runner;
- creates a loop disk and writes the `lsblk` fixture that names it;
- puts `fake-bin/` first on `PATH`: `lsblk` (one disk, the loop device), `bootc` (fails, so no live-ISO mode), `pkexec` (`sudo -n`, there is no polkit agent).

`check-recipe.py` then judges the recipe the frontend handed over: the real
fisherman accepts it, it conforms to `shared/recipe/fisherman-recipe.schema.json`,
and it targets the disk the job set up.

## Layer 2: the recipe is installed and booted

`E2E (install <frontend>)` downloads that recipe and runs `vm-install.sh`:
fisherman's own bootcrew tooling installs it onto a loop disk, enables SSH
in the result, verifies the layout and boots it in QEMU until `bootc status`
answers over SSH. Only `disk` and `image` are rewritten (the loop device and
the SSH-enabled canary that matches the recipe's boot stack).

## Run it locally

```bash
bash shared/e2e/setup.sh                       # needs go, sudo, losetup
export PATH=$PWD/shared/e2e/fake-bin:$PATH
xvfb-run -a python3 tests/e2e/run_gnome.py     # after a meson build
python3 shared/e2e/check-recipe.py gnome
```
