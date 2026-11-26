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
        how, dx = flows.FIELD_AT.get(w.fe, ("after", 260))
        wanted = {v for _words, v in values}
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
    fill_fields(w, PASSPHRASE_FIELDS)


def tick(pattern):
    def act(w):
        boxes = [n for n in w.nodes if "check" in n["role"] and "checked" not in n["states"]
                 and "sensitive" in n["states"]]
        if boxes:
            if not (boxes[-1].get("actions") and w.do("press", boxes[-1])):
                w.click_box(boxes[-1].get("box"))
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
    ("*", "account"): Action(prepare=account),
    ("*", "eula"): Action(prepare=tick(r"(I )?(have read and )?(accept|agree).*")),
    ("*", "recovery-key"): Action(leave=lambda w: (tick(
        r"(I )?(have )?(saved|wrote|stored|written|backed up).*")(w), w.read(), w.primary())),
    ("gnome", "encryption"): Action(prepare=passphrase),
    ("*", "wipe-or-free"): Action(prepare=choose(r"(Erase|Use) (the )?(whole|entire) disk.*|Erase.*")),
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
    happy = Run("happy", f"happy,{key}", env=dict(ONLINE), skip=("install",))
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
                 "TUNA_EULA_FILE": eula, "WALK_EULA": eula},
            only=("prerelease", "eula")),
        Run("offline", f"happy,{key}", until=("disk",), only=("network",)),
        Run("low-ram", f"low-ram,{key}", until=("requirements",), env=dict(ONLINE),
            only=("requirements",)),
        Run("no-uefi", f"no-uefi,{key}", until=("requirements",), env=dict(ONLINE),
            only=("requirements",), rename={"requirements": "requirements--requirements-fatal"}),
        Run("no-disks", f"no-disks,{key}", until=("disk",), env=dict(ONLINE), only=("disk",),
            rename={"disk": "disk--no-usable-disk"}),
        Run("device-lost", f"device-lost,{key}", until=("done--failed",), env=dict(ONLINE),
            only=("done--failed",), rename={"done--failed": "done--device-lost"}),
        Run("repart-error", f"repart-error,{key}", until=("done--failed",), env=dict(ONLINE),
            only=("done--failed",), rename={"done--failed": "done--repart-error"}),
        Run("recovery-key-error", "recovery-key-error", env=dict(ONLINE),
            until=("recovery-key--recovery-key-failed",),
            only=("recovery-key--recovery-key-failed",)),
        Run("enroll-error", f"no-tpm,enroll-error,{key}", env=dict(ONLINE),
            until=("encryption--passphrase-enroll-failed",),
            only=("encryption--passphrase-enroll-failed",)),
        Run("handoff-soft-reboot", f"handoff-soft-reboot,{key}", env=dict(ONLINE),
            until=("done",), only=("handoff",), rename={"handoff": "handoff--soft-reboot"}),
        Run("handoff-error", f"handoff-error,{key}", env=dict(ONLINE),
            until=("handoff--handoff-failed",), only=("handoff--handoff-failed",)),
    ]
    exempt = flows.EXEMPT.get(frontend, {})
    for run in out:
        run.only = tuple(p for p in run.only if run.name_of(frontend, p) not in exempt)
    return [r for r in out if r.only or r.name == "happy"]
