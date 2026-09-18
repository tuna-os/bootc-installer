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

`credits.json` is the Credits dialog's data (maintainers, artists, the
quote); `installer-video.webm` plays while fisherman writes the disk;
`welcome.png` and `complete.svg` are the tour artwork; `store-qr.svg`
encodes `store_url`.
