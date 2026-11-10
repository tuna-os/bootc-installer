"""The contract code that the Python frontends (GNOME, XFCE) share.

One copy, imported by both. The GNOME build installs this package beside
`bootc_installer` (root meson.build); the XFCE Flatpak copies it beside
`tuna_installer_xfce` (its manifest). In a checkout it is on `sys.path` as
`shared/python`. The data files that the modules read stay in their contract
directories (`shared/<contract>/`), because the other three frontends read
them there; `_data.py` finds them in a checkout and in an installed tree.

No GTK, no gettext, nothing but the standard library.
"""
