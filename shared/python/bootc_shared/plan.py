"""Reader for `fisherman plan --json -` (fisherman/docs/PLAN.md).

The one copy: GNOME imports it as `bootc_shared.plan`; XFCE can import it
the same way. tests/unit/test_shared_plan.py covers it against the golden
files of the pinned fisherman.

A plan says what an install of a recipe would do, before anything is
written: the target disk and what it reports about itself, and every
device whose data the install destroys. `plan` needs no root, so it runs
like `validate`: unprivileged, on the host, with the recipe on stdin (`-`),
never on argv. The recipe can hold the LUKS passphrase, and argv is
world-readable in /proc. The plan itself holds no secret.

A plan is not a permission. The install checks the device again. To make
it refuse a disk that is not the one the user confirmed, a frontend copies
the plan's identity into the recipe as `diskIdentity`; to make it refuse a
machine that no longer gives the plan the user confirmed, it copies
`plan.binding` as `planBinding` (bind()). A frontend that cannot get a plan
(an older fisherman, a timeout) installs as before, with neither. A plan
from a fisherman without `plan.binding` binds the disk only.
"""

import copy
import json
import re
import subprocess

from .probe import format_size

# The schema version this reader understands (PLAN.md, "Output").
PROTOCOL_VERSION = 1

# How long one plan may take. It reads the target disk's facts (one lsblk
# call) and the TPM; this bounds a hung flatpak-spawn or a slow udev.
TIMEOUT_SECONDS = 20

# The value of a field that only the install can resolve.
UNKNOWN = "unknown"

# The shape of `plan.binding.digest` that fisherman accepts back in
# `planBinding.digest` (VALIDATE.md, `plan_binding_invalid`).
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")

# The copy keys of the confirmation page (shared/branding/copy-defaults.json).
COPY_PREFIX = "confirm_plan_"
EFFECTS = ("wipe_disk", "format", "mkswap")


class PlanError(Exception):
    """fisherman could not be asked, or its answer was unreadable.

    This is not "the recipe is invalid". A frontend shows no plan and binds
    nothing: the install runs its own checks before it touches a disk.
    """


def argv(fisherman):
    """The command for one plan. `fisherman` is the frontend's own,
    unprivileged way of reaching fisherman (a list), as for validate.
    Never through pkexec or sudo."""
    return list(fisherman) + ["plan", "--json", "-"]


def parse(text):
    """The plan result in `text`, or PlanError.

    An older fisherman has no `plan` command. Whatever it prints instead
    has no protocol_version and is refused here.
    """
    try:
        result = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise PlanError(f"fisherman plan printed invalid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise PlanError("fisherman plan did not print a JSON object")
    version = result.get("protocol_version")
    if version != PROTOCOL_VERSION:
        raise PlanError(f"fisherman plan protocol_version {version!r} is not {PROTOCOL_VERSION}")
    if not isinstance(result.get("valid"), bool) or not isinstance(result.get("errors"), list):
        raise PlanError("fisherman plan printed no valid flag or errors list")
    plan = result.get("plan")
    if result["valid"] and not isinstance(plan, dict):
        raise PlanError("fisherman plan is valid but printed no plan")
    if not result["valid"]:
        result["plan"] = None
    return result


def run(command, recipe, timeout=TIMEOUT_SECONDS):
    """Write `recipe` (a dict) to `command`'s stdin and return the parsed
    result. Exit 0 is a plan, 1 an invalid recipe; anything else, or no
    answer within `timeout`, is PlanError. The error names no part of the
    recipe."""
    try:
        proc = subprocess.run(command, input=json.dumps(recipe), capture_output=True,
                              text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise PlanError(f"cannot run {command[0]}: not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise PlanError(f"fisherman plan gave no answer in {timeout} s") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise PlanError(f"cannot run fisherman plan: {type(exc).__name__}") from exc
    if proc.returncode not in (0, 1):
        reason = (proc.stderr or "").strip().splitlines()
        detail = reason[0] if reason else "no message"
        raise PlanError(f"fisherman plan failed (exit {proc.returncode}): {detail}")
    return parse(proc.stdout)


def known(value):
    """`value` is a value the plan knows: not "unknown", not empty."""
    return value not in (None, "", UNKNOWN)


def _target(plan):
    target = (plan or {}).get("target")
    return target if isinstance(target, dict) else {}


def identity(plan):
    """`plan.target.identity`, or {} for a manual layout or no plan."""
    ident = _target(plan).get("identity")
    return ident if isinstance(ident, dict) else {}


def disk_identity(plan):
    """The recipe's `diskIdentity` for `plan`: `serial`, `wwn` and
    `sizeBytes` of `plan.target.identity`, each only when the plan knows
    it. {} when it knows none (PLAN.md, "Binding the install")."""
    ident = identity(plan)
    out = {}
    for src, dst in (("serial", "serial"), ("wwn", "wwn")):
        if isinstance(ident.get(src), str) and known(ident[src]):
            out[dst] = ident[src]
    size = ident.get("size_bytes")
    if isinstance(size, int) and not isinstance(size, bool) and size > 0:
        out["sizeBytes"] = size
    return out


def plan_binding(plan):
    """The recipe's `planBinding` for `plan`: `plan.binding.digest`, and
    `read_image` as `readImage` when it is a boolean (PLAN.md,
    "plan.binding"). {} when the plan has no binding (a fisherman before
    it) or its digest is not `sha256:` and 64 lowercase hex digits."""
    binding = (plan or {}).get("binding")
    if not isinstance(binding, dict):
        return {}
    digest = binding.get("digest")
    if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
        return {}
    out = {"digest": digest}
    if isinstance(binding.get("read_image"), bool):
        out["readImage"] = binding["read_image"]
    return out


def bind(recipe, plan):
    """A copy of `recipe` bound to `plan`, or `recipe` itself when the plan
    cannot bind it.

    `diskIdentity` is set when the plan knows an identity of the recipe's
    `disk` (not for a manual layout, an unknown identity or a plan for
    another disk). `planBinding` is set when the plan has a binding and
    is not for another disk than the recipe's `disk`."""
    if not plan:
        return recipe
    disk = _target(plan).get("disk")
    recipe_disk = (recipe or {}).get("disk")
    fields = {}
    identity_of_disk = disk_identity(plan)
    if identity_of_disk and disk and disk == recipe_disk:
        fields["diskIdentity"] = identity_of_disk
    saved = plan_binding(plan)
    if saved and (not disk or disk == recipe_disk):
        fields["planBinding"] = saved
    if not fields:
        return recipe
    bound = copy.deepcopy(recipe)
    bound.update(fields)
    return bound


def destroys(plan):
    """[(device, effect)] of `plan.destroys`, in fisherman's order. An
    effect this reader does not know is kept: the device is still lost."""
    out = []
    for entry in (plan or {}).get("destroys") or []:
        if isinstance(entry, dict) and entry.get("device"):
            out.append((str(entry["device"]), str(entry.get("effect") or "")))
    return out


def target_rows(plan, text):
    """[(title, detail)] of the target disk for a confirmation page, in
    the words of the copy keys read through `text(key, **values)`: the
    model, size and serial, each "unknown" when the disk does not report
    it, and whether the install is bound to it. [] for a manual layout."""
    ident = identity(plan)
    if not ident:
        return []
    unknown = text(COPY_PREFIX + "unknown") or UNKNOWN
    size = ident.get("size_bytes")
    values = {
        "disk": _target(plan).get("disk") or unknown,
        "model": ident["model"] if known(ident.get("model")) else unknown,
        "size": format_size(size) if isinstance(size, int) and size > 0 else unknown,
        "serial": ident["serial"] if known(ident.get("serial")) else unknown,
    }
    rows = [(text(COPY_PREFIX + "target", **values),
             text(COPY_PREFIX + "target_detail", **values))]
    binding = disk_identity(plan)
    if "serial" in binding or "wwn" in binding:
        rows.append((text(COPY_PREFIX + "bound", **values), ""))
    else:
        rows.append((text(COPY_PREFIX + "unbound", **values), ""))
    return [(title, detail) for title, detail in rows if title]


def destroy_rows(plan, text):
    """[(title, "")] for each device the install destroys: the copy key
    `confirm_plan_<effect>` with {disk} filled, or `confirm_plan_format`
    for an effect this build has no line for."""
    rows = []
    for device, effect in destroys(plan):
        key = COPY_PREFIX + (effect if effect in EFFECTS else "format")
        line = text(key, disk=device)
        if line:
            rows.append((line, ""))
    return rows


def rows(plan, text):
    """Every row of a plan, target first."""
    return target_rows(plan, text) + destroy_rows(plan, text)
