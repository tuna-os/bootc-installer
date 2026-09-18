# Bluefin branding for the bootc installers

Everything the GNOME installer used to say and show as Bluefin, moved out of
the installer and into the branding contract (`shared/branding/README.md`):
the Destiny lines on the confirm page, the "Become Legend" button, the
Ayrton Senna quotes for pt_BR, the welcome subtitle, the store link and QR,
the install video, the credits and the tour artwork.

This directory is the drop-in for the live ISO (projectbluefin/dakota-iso).
Ship it as:

```
/etc/bootc-installer/branding.json            <- branding.json
/usr/share/bootc-installer/branding/          <- assets/*
```

Every installer frontend reads the file from the host (through
`/run/host` inside its Flatpak). The four asset paths in `branding.json`
point at `/usr/share/bootc-installer/branding/`; change both if the ISO
keeps them elsewhere. `name`, `id` and the URLs may be left out entirely:
the installer then takes them from the image's `os-release`, and only the
copy, quotes, store and assets remain Bluefin's.

`welcome.png`, `complete.svg` and `store-qr.svg` are the common assets
every frontend may show. `extensions.gnome` carries what only the GNOME
frontend renders: the tour page text, `installer-video.webm` (plays while
fisherman writes the disk) and `credits.json` (the Credits dialog).

`test_bluefin_branding.py` next to this file is the pin test for this
branding: it validates the JSON against the schema and checks the lines
Bluefin cares about resolve as written. It belongs with the branding, in
dakota-iso, not in the installer repository; run it there with the shared
resolver on the path (`python3 -m pytest shared/branding/examples/bluefin`
works in the monorepo).
