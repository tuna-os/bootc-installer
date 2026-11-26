# Installer walkthroughs

These tools take one picture of each page of each installer. Each picture
comes from the real installer as it ships. The installer talks to the mock
daemon (`fishermand --mock`), so no disk changes. Nothing draws or joins
pictures.

```bash
just walkthrough kde          # or gnome, cosmic, niri, xfce
```

The result goes to `docs/walkthrough/mock/<frontend>/`:

- `NN-<page>.png`: one picture for each page, in the order of
  `shared/flow/screens.yaml`. A state of a page has a name such as
  `done--device-lost`.
- `walkthrough.webp`: the main path as an animation.
- `README.md`: the pictures with captions from the flow spec.
- `manifest.json`: the page, the run, the mock scenario and the hash of
  each picture.

## How it works

1. `run.sh` builds a Fedora container (`Containerfile`) and builds the
   installer and the mock daemon in it (`build.sh`). `PINS` gives the
   commits of fisherman and of the gnome-setup build in tunaOS.
2. `walk.py` starts a session for each run of `runs.py`. A session has
   its own buses, AT-SPI and headless sway with a software renderer. It
   also has the mock daemon with the scenario of the run, and the
   installer. The container has no network.
3. The walk reads the headings of the window from the AT-SPI tree. For
   COSMIC and niri it also reads the screen with tesseract. `flows.py`
   maps the headings to the page ids of the flow spec. The walk takes a
   picture when the screen is still. Then it does what a person does. It
   selects the mock disk, types the account and pushes the main button.
4. `render.py` numbers the pictures, removes their metadata, makes the
   animation and writes the page.
5. `check.py` compares a new set with the committed set. It fails when a
   page has no picture, when a picture has one colour, or when a run
   stops. The check only reports a change of
   pixels.

The session sets the size (1000 x 700), the locale (`en_US.UTF-8`), the
time zone (UTC), the fonts, the theme and the host name. The disks, the
TPM and the recovery key come from the mock. `WALK_VARIANT=dark` and
`WALK_VARIANT=small` (1024 x 600) make the main path again.

The niri installer runs here in sway. niri itself needs hardware GL, but
this installer is a Quickshell app, and each wlroots compositor shows it
the same way.

## A new page

The walk finds a page by its heading. A frontend can add, remove or move a
page. When a new heading has no line in `flows.py`, the walk takes a
picture with the name `unknown` and the run stops. Add the heading to
`PAGES`, or to `OWN_PAGES` for a page that the flow spec does not have.
A frontend that does not have a page of the spec gives the reason in
`EXEMPT`.

## Pictures from a real install

The image-installer E2E test of tuna-os/tunaOS installs into a virtual
machine. It can write the same files: `<page>.png` and a `captures.json`
of this form. Then `render.py --source e2e` makes the same page from it.

```json
{"frontend": "kde", "pages": {"disk": {"page": "disk", "file": "disk.png", "run": "happy"}}}
```

## CI

`walkthrough-<frontend>.yml` calls `_walkthrough.yml` when the frontend,
these tools or the flow spec change, and once a week. A run uploads the
pictures as an artifact. On `dev`, new pictures go to a pull request, not
to `dev`.
