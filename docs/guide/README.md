# Installer guidebook

This guidebook tells you how to use, configure and build the installer.
The [project README](../../README.md) tells you what the installer is, why you need it and who it is for.
Read the pages in this order, or go to the page for your task.

| Page | Read it when you want to |
|---|---|
| [Install and use the installer](installing.md) | Get the Flatpak, run the wizard and know what each screen does. |
| [Architecture](../architecture.md) | Know which programs install the system, and which parts are legacy. |
| [The image-based medium](../image-medium.md) | Know what the new medium is, and what its tests show. |
| [How a recipe install works](how-it-works.md) | Know which steps fisherman does, how it encrypts the disk and what it copies to the new system. |
| [Recipes and autoinstall](recipes.md) | Write a recipe by hand, or install with no wizard. |
| [Customise the installer for your image](customising.md) | Ship the installer in your own image or live ISO with your own catalog and defaults. |
| [Build, test and release](developing.md) | Change the code, run the tests and know how a release gets out. |

## Screenshots

CI renders each screen of each frontend from the real code.
The images are in two places:

- [GNOME walkthrough](../gui-walkthrough.md): the GNOME frontend, screen by screen.
- [All frontends](../walkthrough/README.md): GNOME (legacy), KDE, COSMIC, niri and XFCE side by side, with the parity matrix.

[The image-based medium](../image-medium.md) has screenshots from real runs of the medium.

You do not edit the CI images by hand.
A CI job makes them again after each change to `dev`.

## Other documents

- [Live ISO](../live-iso.md): build a live ISO that starts the installer.
- [Release flow](../RELEASE.md): how `dev` gets to `prod`.
- [Monorepo migration](../MIGRATION.md): how one repository replaced five.
- [Contribution guide](../../CONTRIBUTING.md): branch rules and commit format.
