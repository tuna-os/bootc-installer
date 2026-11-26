"""What the walk knows about the pages of each installer.

PAGES gives each page id of shared/flow/screens.yaml the headings that show
it. The walk reads the headings from top to bottom: the first one that a
pattern matches in full decides. So a frontend can add, remove or move a
page, and only a new heading needs a new line here. A page that nothing
matches is kept in the pictures as `unknown` and makes the job report it.

ACTIONS says how to leave a page. The default is the primary button.
EXEMPT lists the spec pages that a frontend has not, with the reason.
"""

# Pages that cover the one below them, and the ends of the flow: matched
# before the others, on any line.
MODAL = {
    # A gate can cover the first page (niri draws it over Welcome).
    "requirements": [r"This computer does not meet.*", r"This computer is below the requirements",
                     r"This computer cannot run the installer", r"Not enough memory",
                     r"Unsupported firmware"],
    "install--cancel": [r"Stop the installation\?", r"Stop the installer\?",
                        r"Cancel the installation\?", r"Cancel (the )?installation\?",
                        r"Stop installing\?", r"Cancel the install\?",
                        r"Cancel this installation\?"],
    "confirm--dialog": [r"Begin Installation\?", r"Start the installation\?",
                        r"Erase .* and install\?"],
    "done--cancelled": [r"(The )?installation (was )?cancelled\.?", r"Cancelled",
                        r"Installation stopped\.?"],
    "done--failed": [r"(The )?installation failed\.?", r"Failed", r"Install(ation)? did not finish\.?"],
    "handoff--handoff-failed": [r"(The )?handoff failed\.?", r".*could not (start|hand over).*"],
    "recovery-key--recovery-key-failed": [
        r"(The|No) recovery key (could not be made|was made).*", r"No recovery key.*",
        r"The recovery key could not .*", r"Could not (make|save|set) (the|a) recovery key.*"],
}

PAGES = {
    "requirements": [r"Requirements", r"System requirements", r"This computer does not meet.*",
                     r".*(not enough|too little) memory.*", r"UEFI (firmware )?(is )?(required|missing).*",
                     r"Low memory.*"],
    "try-or-install": [r"Try or install", r"Welcome to TunaOS", r"Welcome TunaOS"],
    "language": [r"Language", r"Language and region"],
    "keyboard": [r"Keyboard( layout)?"],
    "timezone": [r"Time ?zone"],
    "network": [r"Network( connection)?"],
    "prerelease": [r"Disclaimer", r"Pre-?release.*"],
    "eula": [r"Terms of use", r"Terms", r"License( agreement)?"],
    "rst": [r"Intel RST.*", r"Intel Rapid Storage.*"],
    "disk": [r"Target disk", r"Disk( selection)?", r"Select a disk", r"Destination",
             r"Where should .* be installed\?"],
    "wipe-or-free": [r"Existing data( found)?", r"Existing systems?( found)?"],
    "encryption": [r"Disk encryption", r"Encryption", r"Disk passphrase"],
    "account": [r"User account", r"Account", r"Your account", r"Create (your|an) account", r"Name this computer"],
    "confirm": [r"Confirm( installation)?", r"Review.*", r"Ready to install.*", r"Summary"],
    "install": [r"Installing( .*)?", r"Installation", r"Progress"],
    "recovery-key": [r"Recovery key", r"Back up recovery key", r"Save your recovery key.*"],
    "handoff": [r"Handoff", r"Hand ?over", r"Start .* now"],
    "done": [r"Done", r"Installation complete[!.]?", r"Finished", r".* is installed[!.]?",
             r"Installed"],
}

# Pages of one frontend that the flow spec has no id for.
OWN_PAGES = {
    "niri": {"session": [r"Session"], "source": [r"Source", r"What do you want to install\?"],
             "tour": [r"Tour"]},
    "xfce": {"source": [r"What do you want to install\?", r"Source"]},
    "cosmic": {"image": [r"Image", r"Select an image", r"Choose a system"], "options": [r"Options", r"Computer name"],
               "tour": [r"Tour"], "try-or-install": [r"Welcome"]},
    "kde": {"image": [r"Image", r"System image"], "computer": [r"Computer name", r"Hostname"],
            "try-or-install": [r"Welcome"]},
    "gnome": {"try-or-install": [r"Welcome TunaOS", r"Welcome to TunaOS"]},
}

# A page of one frontend that shows the content of several spec pages.
COVERS = {"niri": {"session": ["language", "keyboard", "timezone"]}}

PRIMARY = [r"Install now", r"Get started", r"Next", r"Continue", r"Start installation",
           r"Install", r"Erase( disk)? and install", r"Done", r"Finish"]

DISK = r"(Mockware )?Mock NVMe 512.*"
ACCOUNT = {"full": "Alex Example", "user": "alex", "pass": "walkthrough-mock-1", "host": "tunaos"}

EXEMPT = {
    "kde": {},
    "cosmic": {},
    "niri": {"network": "The session page has the network card; there is no page of its own."},
    "xfce": {
        "done--cancelled": "The cancel dialog draws no buttons (gates.ConfirmCancelDialog has no "
                           "show_all), so the walk cannot confirm a cancel.",
    },
    "gnome": {
        "install--cancel": "gnome-setup has no Cancel during the install.",
        "done--cancelled": "gnome-setup has no Cancel during the install.",
        "requirements": "gnome-setup has no such page.",
        "timezone": "gnome-initial-setup asks for it on the first boot.",
        "network": "gnome-initial-setup asks for it on the first boot.",
        "account": "gnome-initial-setup makes the account on the first boot.",
        "handoff": "gnome-setup restarts from its last page.",
        "rst": "gnome-setup reads Intel RST from sysfs, not from the daemon, and the session "
               "cannot change sysfs.",
        "handoff--soft-reboot": "gnome-setup has no handoff page.",
        "handoff--handoff-failed": "gnome-setup has no handoff page.",
        "requirements--requirements-fatal": "gnome-setup has no requirements page.",
        "done--device-lost": "gnome-setup goes on to the next page when the install fails "
                             "(tuna-os/tunaOS#5017).",
        "recovery-key--recovery-key-failed": "gnome-setup shows no recovery-key page and no "
                                             "error when the daemon makes no key.",
        "encryption--passphrase-enroll-failed": "gnome-setup goes on when the daemon "
                                                "refuses the passphrase (tuna-os/tunaOS#5017).",
        "done--repart-error": "gnome-setup goes on to the next page when the install fails "
                              "(tuna-os/tunaOS#5017).",
    },
}

# Where the entry of a label is, for a frontend with no entries in its
# AT-SPI tree: "after" the label by so many pixels, or this far from the
# "right" edge of the window.
FIELD_AT = {"niri": ("after", 250), "cosmic": ("right", 200)}

# One frontend's name of a page that the spec has under another name.
SAME_PAGE = {"gnome": {"confirm--dialog": "confirm"}}

# The labels of the entries, read by OCR, and what goes in each.
OCR_LABELS = [(r"Username", "user"), (r"Full name", "full"), (r"Password", "pass"),
              (r"Password again", "pass"), (r"Confirm password", "pass"),
              (r"Passphrase", "pass"), (r"Confirm passphrase", "pass")]

# The variants of the main path that each frontend has. Only XFCE has a
# dark set: gnome-setup forces the light style, COSMIC and niri draw their
# own dark theme, and KDE takes its colours from the Plasma platform theme,
# which the session does not have.
VARIANTS = {"gnome": ("small",), "kde": ("small",), "cosmic": ("small",),
            "niri": ("small",), "xfce": ("dark", "small")}

# Headings that are also the words of a button. They name a page only when
# no other heading does.
WEAK = [r"Done", r"Finished", r"Installed", r"Installation", r"Progress", r"Confirm",
        r"Account", r"Encryption", r"Network", r"Terms", r"Summary"]

# Placeholders of empty entries, read by OCR (niri: Quickshell gives its
# entries no AT-SPI node), and what goes in each.
OCR_PLACEHOLDERS = [(r"Enter passphrase", "pass"), (r"Confirm passphrase", "pass")]

# The exemptions that a defect causes, not the design of the frontend: the
# pages come back when the fix lands. The rest of EXEMPT is by design.
BLOCKED_BY = {
    "xfce": {"done--cancelled": "tuna-os/installer#482"},
    "gnome": {"done--device-lost": "tuna-os/tunaOS#5017", "done--repart-error": "tuna-os/tunaOS#5017",
              "encryption--passphrase-enroll-failed": "tuna-os/tunaOS#5017",
              "recovery-key--recovery-key-failed": "tuna-os/tunaOS#5017"},
}
