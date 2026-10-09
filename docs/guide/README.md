# bootc-installer guidebook

This guidebook tells you how to use, configure and build bootc-installer.
The [project README](../../README.md) gives a short summary.
Read the pages in this order, or go to the page for your task.

| Page | Read it when you want to |
|---|---|
| [Install and use the installer](installing.md) | Get the Flatpak, run the wizard and know what each screen does. |
| [How an install works](how-it-works.md) | Know which steps fisherman does, how it encrypts the disk and what it copies to the new system. |
| [Recipes and autoinstall](recipes.md) | Write a recipe by hand, or install with no wizard. |
| [Customise the installer for your image](customising.md) | Ship the installer in your own image or live ISO with your own catalog and defaults. |
| [Build, test and release](developing.md) | Change the code, run the tests and know how a release gets out. |

## Screenshots

CI renders each screen of each installer frontend from the real code.
The images are in two places:

- [GNOME walkthrough](../gui-walkthrough.md): the GNOME frontend, screen by screen.
- [All frontends](../walkthrough/README.md): GNOME, KDE, COSMIC, Niri and XFCE side by side, with the parity matrix.

You do not edit these images by hand.
A CI job makes them again after each change to `dev`.

## Other documents

- [Live ISO](../live-iso.md): build a live ISO that starts the installer.
- [Release flow](../RELEASE.md): how `dev` gets to `prod`.
- [Monorepo migration](../MIGRATION.md): how the five frontend repositories became one.
- [Contribution guide](../../CONTRIBUTING.md): branch rules and commit format.
