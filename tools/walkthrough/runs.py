"""The runs of each installer, and what a person does on each page.

A run is one session: a mock scenario, an environment, and the pages it
pictures. `happy` pictures every page that it passes. The other runs each
reach one conditional page, failure page or state, and picture only that.
"""

import os
import time
from dataclasses import dataclass, field

import flows
from walk_errors import Stuck

HERE = os.path.dirname(os.path.abspath(__file__))
ONLINE = {"TUNA_INSTALLER_SKIP_CONN_CHECK": "1", "VANILLA_SKIP_CONN_CHECK": "1"}
# Pages that change by themselves: the walk waits on them, unless the run
# says what to do there.
WAIT_PAGES = ("install", "done--cancelled")


@dataclass
class Action:
    prepare: object = None  # before the picture: the choices a person makes
    leave: object = None    # after the picture: how to go on; default primary


@dataclass
class Run:
    name: str
    scenario: str
    until: tuple = ("done",)
    env: dict = field(default_factory=dict)
    only: tuple = ()        # the pages to picture; empty is each page
    skip: tuple = ()        # pages not to picture
    alias: dict = field(default_factory=dict)  # in this run, page X is state Y
    # In this run, page X is state Y once the walk has pressed on X: an
    # error that shows inside the page, not as a page of its own.
    after_press: dict = field(default_factory=dict)
    rename: dict = field(default_factory=dict)
    actions: dict = field(default_factory=dict)
    step_delay: str = "40ms"
    max_steps: int = 90

    def name_of(self, frontend, page):
        if page == "unknown" or page in self.skip or (self.only and page not in self.only):
            return None
        name = self.rename.get(page, page)
        return flows.SAME_PAGE.get(frontend, {}).get(name, name)

    def done(self, found, frontend):
        return bool(self.only) and all(self.name_of(frontend, p) in found for p in self.only)


# -- what a person does ------------------------------------------------------

def choose_disk(w):
    if not w.choose(flows.DISK):
        raise Stuck("the mock disk is not on the page")
    time.sleep(0.6)


def fill_fields(w, values):
    """Each entry of the AT-SPI tree, by its name; or, with no entries in the
    tree, the entry beside each label that OCR finds."""
    fields = w.fields()
    if fields:
        for n in fields:
            key = (n["name"] + " " + n.get("description", "")).lower()
            for words, value in values:
                if any(word in key for word in words):
                    box = n["box"]
                    w.type_into(box[0] + min(box[2] - 8, 60), box[1] + box[3] / 2, value)
                    break
    else:
        wanted = {v for _words, v in values}
        # An empty entry that shows its placeholder: click the placeholder.
        for text, key in flows.OCR_PLACEHOLDERS:
            box = w.find_text(text)
            if box and flows.ACCOUNT[key] in wanted:
                w.type_into(box[0] + box[2] / 2, box[1] + box[3] / 2, flows.ACCOUNT[key])
        w.read()
        how, dx = flows.FIELD_AT.get(w.fe, ("after", 260))
        for label, key in flows.OCR_LABELS:
            value = flows.ACCOUNT[key]
            box = w.find_text(label)
            if box and value in wanted:
                x = box[0] + box[2] + dx if how == "after" else w.s.width - dx
                w.type_into(x, box[1] + box[3] / 2, value)
    time.sleep(0.4)
    w.read()


ACCOUNT_FIELDS = [
    (("confirm", "again", "repeat", "retype"), flows.ACCOUNT["pass"]),
    (("password", "passphrase"), flows.ACCOUNT["pass"]),
    (("full name", "full"), flows.ACCOUNT["full"]),
    (("username", "user name", "user"), flows.ACCOUNT["user"]),
]
PASSPHRASE_FIELDS = [(("confirm", "again", "passphrase", "password"), flows.ACCOUNT["pass"])]


def account(w):
    fill_fields(w, ACCOUNT_FIELDS)


def passphrase(w):
    # With a TPM the default needs no passphrase. A click by OCR on the
    # "Passphrase" choice would change the choice (seen on niri).
    if not w.fields() and "no-tpm" not in w.s.scenario:
        return
    fill_fields(w, PASSPHRASE_FIELDS)


def tick(pattern):
    def act(w):
        # Once per page: a second click would clear the tick again.
        done = w.__dict__.setdefault("ticked", set())
        if pattern in done:
            return
        done.add(pattern)
        boxes = [n for n in w.nodes if "check" in n["role"] and "checked" not in n["states"]
                 and "sensitive" in n["states"]]
        if boxes:
            if not (boxes[-1].get("actions") and w.do("press", boxes[-1])):
                w.click_box(boxes[-1].get("box"))
        elif w.ocr_on and w.find_text(pattern):
            # The box sits left of its label: a click on the words alone
            # does not tick it in every toolkit.
            box = w.find_text(pattern)
            w.s.click(box[0] - 14, box[1] + box[3] / 2)
        elif not w.press(pattern, roles=None, must=False):
            w.choose(pattern)
        time.sleep(0.5)
    return act


def press(*patterns):
    def act(w):
        for p in patterns:
            if w.press(p, must=False, ocr=False):
                return
        for p in patterns:
            if w.press(p, must=False):
                return
        raise Stuck(f"none of {patterns}")
    return act


def choose(pattern):
    def act(w):
        if not w.choose(pattern):
            raise Stuck(f"no {pattern}")
        time.sleep(0.5)
    return act


ACTIONS = {
    ("*", "disk"): Action(prepare=choose_disk),
    # A row of gnome-setup's disk list goes on at once.
    ("gnome", "disk"): Action(leave=choose_disk),
    ("*", "account"): Action(prepare=account),
    ("*", "eula"): Action(prepare=tick(r"(I )?(have read and )?(accept|agree).*")),
    ("*", "recovery-key"): Action(leave=lambda w: (tick(
        r"(I )?(have )?(saved|wrote|stored|written|backed up).*")(w), w.read(), w.primary())),
    ("*", "encryption"): Action(prepare=passphrase),
    ("*", "wipe-or-free"): Action(leave=lambda w: (choose(
        r"(Erase|Use) (the )?(whole|entire) disk.*|Erase( the)?( whole)?( disk)?")(w), w.read(), w.primary())),
    ("*", "confirm--dialog"): Action(leave=press(r"Install", r"Start( installation)?",
                                                 r"Erase( and install)?")),
}

CANCEL = press(r"Cancel( installation| install)?", r"Stop( installation)?")
CANCEL_YES = press(r"Stop and discard", r"Stop( the)? install(ation)?", r"Cancel( the)? install(ation)?", r"Yes.*",
                   r"Stop", r"Cancel install")


def action(run, frontend, page):
    return run.actions.get(page) or ACTIONS.get((frontend, page)) \
        or ACTIONS.get(("*", page)) or Action()


def for_frontend(frontend, variant=""):
    key = "fixed-key"
    happy = Run("happy", f"happy,{key}", env=dict(ONLINE), skip=("install",),
                # "Not now" leads to the done page; a restart ends the session.
                actions={"handoff": Action(leave=press(r"Not now", r"Later", r"Continue"))})
    if variant:
        return [happy]
    eula = os.path.join(HERE, "fixtures/eula.xml")
    out = [
        happy,
        Run("install", f"cancel,{key}", until=("done--cancelled",), env=dict(ONLINE),
            only=("install", "install--cancel", "done--cancelled"),
            actions={"install": Action(leave=CANCEL), "install--cancel": Action(leave=CANCEL_YES)},
            step_delay="20ms"),
        Run("no-tpm", f"no-tpm,{key}", until=("recovery-key",), env=dict(ONLINE),
            only=("encryption",)),
        Run("existing-data", f"existing-data,{key}", until=("wipe-or-free", "confirm"),
            env=dict(ONLINE), only=("wipe-or-free",)),
        Run("rst", f"rst,{key}", until=("disk",), env=dict(ONLINE), only=("rst",)),
        Run("terms", f"happy,{key}", until=("disk",),
            env={**ONLINE, "SETUP_OVERRIDE_OS_RELEASE_TYPE": "pre-release",
                 "TUNA_EULA_FILE": eula, "WALK_EULA": eula,
                 "TUNA_OS_RELEASE": os.path.join(HERE, "fixtures/os-release-prerelease"),
                 "TUNA_OS_RELEASE_FILE": os.path.join(HERE, "fixtures/os-release-prerelease")},
            only=("prerelease", "eula")),
        # On an installed system (not live media) the image list offers images
        # that need a download; with no network the network page shows.
        Run("offline", f"not-live,{key}", until=("disk",), only=("network",),
            actions={p: Action(prepare=choose(r"Capture Desktop.*Edge.*"))
                     for p in ("source", "image")}),
        Run("low-ram", f"low-ram,{key}", until=("requirements",), env=dict(ONLINE),
            only=("requirements",)),
        Run("no-uefi", f"no-uefi,{key}", until=("requirements",), env=dict(ONLINE),
            only=("requirements",), rename={"requirements": "requirements--requirements-fatal"}),
        Run("no-disks", f"no-disks,{key}", until=("disk",), env=dict(ONLINE), only=("disk",),
            rename={"disk": "disk--no-usable-disk"}, actions={"disk": Action(leave=lambda w: None)}),
        Run("device-lost", f"device-lost,{key}", until=("done--failed",), env=dict(ONLINE),
            only=("done--failed",), rename={"done--failed": "done--device-lost"}),
        Run("repart-error", f"repart-error,{key}", until=("done--failed",), env=dict(ONLINE),
            only=("done--failed",), rename={"done--failed": "done--repart-error"}),
        Run("recovery-key-error", "recovery-key-error", env=dict(ONLINE),
            until=("recovery-key--recovery-key-failed",),
            only=("recovery-key--recovery-key-failed",),
            # Without a key the page is the failure state, whatever it says.
            alias={"recovery-key": "recovery-key--recovery-key-failed"}),
        Run("enroll-error", f"no-tpm,enroll-error,{key}", env=dict(ONLINE),
            until=("encryption--passphrase-enroll-failed",),
            only=("encryption--passphrase-enroll-failed",)),
        Run("handoff-soft-reboot", f"handoff-soft-reboot,{key}", env=dict(ONLINE),
            until=("done",), only=("handoff",), rename={"handoff": "handoff--soft-reboot"}),
        # With a reboot, a frontend calls Shutdown, not Handoff.
        Run("handoff-error", f"handoff-soft-reboot,handoff-error,{key}", env=dict(ONLINE),
            until=("handoff--handoff-failed",), only=("handoff--handoff-failed",),
            actions={"handoff": Action(leave=press(r"Continue", r"Restart.*", r"Start .*"))},
            after_press={"handoff": "handoff--handoff-failed"}),
    ]
    if frontend != "gnome":
        # Only gnome-setup sets the passphrase with CryptEnroll.Enroll; the
        # native installers send it with Install.
        out = [r for r in out if r.name != "enroll-error"]
    exempt = flows.EXEMPT.get(frontend, {})
    for run in out:
        run.only = tuple(p for p in run.only if run.name_of(frontend, p) not in exempt)
    return [r for r in out if r.only or r.name == "happy"]
