"""Reader for `fisherman verify --json` results (#269, tuna-os/fisherman#385).

An install that exits 0 has written a disk. It has not shown that the disk
starts, or that the system that starts is the image that the user chose.
fisherman keeps the two claims apart (fisherman/docs/RECEIPT.md):

  installed, restart required   the install exited 0 (the done page)
  boot verified                 `fisherman verify` on the installed system
                                compared its own `bootc status` with the
                                installation receipt

The live installer never has the second: the result is made on the
installed system, after its first start. So no done page shows a
verification state today. This reader is the shared contract for a viewer
that runs there; shared/completion/README.md says what it shows.
shared/completion/verification-cases.json holds the five readers to the
same answers.

States: verified, mismatch, unsupported, unavailable, pending. Only a
version-1 result whose outcome is `verified`, whose evidence is the
installed system's own status, whose checks have no mismatch and (when the
caller knows it) whose install id is the expected one is `verified`.
"""

import json
import re

SCHEMA = "fisherman.boot-verification"
VERSION = 1

OUTCOMES = {
    "verified": "verified",
    "mismatch": "mismatch",
    "unsupported": "unsupported",
    "unavailable": "unavailable",
    "not-yet-run": "pending",
}

EVIDENCE = ("live_status", "collected_status")

_TOKEN = re.compile(r"^[a-z0-9_]{1,64}$")


def _view(state, reason):
    return {"state": state, "reason": reason}


def verification(data, expected_install_id=""):
    """The view of one result. `data` is the text fisherman printed (or
    the parsed object). `expected_install_id` binds the result to the
    install the caller knows of; "" when it knows of none."""
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data)
        except ValueError:
            return _view("unavailable", "result_malformed")
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return _view("unavailable", "result_malformed")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        return _view("unavailable", "result_malformed")
    if version != VERSION:
        return _view("unsupported", "result_version_unsupported")
    install_id = data.get("install_id")
    if expected_install_id and install_id != expected_install_id:
        return _view("unavailable", "other_install")
    outcome = data.get("outcome")
    reason = data.get("reason")
    if not isinstance(reason, str) or not _TOKEN.match(reason):
        reason = "unknown"
    if not isinstance(outcome, str) or outcome not in OUTCOMES:
        return _view("unavailable", "outcome_unknown")
    state = OUTCOMES[outcome]
    if state == "verified":
        if data.get("evidence") not in EVIDENCE:
            return _view("unavailable", "wrong_execution_context")
        checks = data.get("checks")
        if not isinstance(checks, dict) or any(
                v == "mismatch" for v in checks.values()):
            return _view("unavailable", "result_inconsistent")
    return _view(state, reason)
