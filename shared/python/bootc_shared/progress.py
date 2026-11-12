"""Pure fisherman progress-event parser.

The one copy: GNOME and XFCE import it as `bootc_shared.progress`.
tests/unit/test_shared_progress.py runs it against the case files in
shared/progress/. The wire protocol it parses is documented in
shared/progress/README.md.

No GTK, no product names: importable on its own by any frontend and by unit
tests. Provides apply_progress_event() and new_progress_state(). The parser
reads no file; transcript_path() only says where the dry-run transcript is.

fisherman computes the bar and names each step itself: every step, substep
and complete event carries `overall_pct`, and every step event a stable
`step_id`. Those are authoritative. The bar maths and the step-name table
below are only the fallback for a fisherman that predates them, and go when
that support does (ROADMAP.md, consolidation step F1).
"""

import json
import re

from . import _data

# Human-friendly labels for each fisherman step name: the fallback for a
# step event without a step_id (a fisherman older than overall_pct/step_id).
# A step_id is labelled by the frontend's branding copy instead, through
# set_step_label_resolver(); these labels match the step_<id> defaults in
# shared/branding/copy-defaults.json. Keys must match the step_name strings
# fisherman emits exactly. Unknown step names fall back to the raw step_name.
_FRIENDLY_STEP_LABELS: dict[str, str] = {
    "Preparing disk":               "Checking your drive…",
    "Partitioning disk":            "Setting up your drive…",
    "Formatting EFI partition":     "Preparing the boot system…",
    "Setting up disk encryption":   "Securing your drive…",
    "Formatting root filesystem":   "Formatting your drive…",
    "Mounting filesystem":          "Almost ready…",
    "Formatting data disk (/var)":  "Preparing data storage…",
    # {product} is substituted at lookup with the recipe's distro_name. This
    # label used to read "Installing Bluefin…" literally, so every downstream
    # that rebrands this installer still told its users it was installing
    # Bluefin — on the progress screen, which is the one they watch for the
    # whole install.
    "Installing OS":                "Installing {product}…",
    "Enrolling TPM2 auto-unlock":   "Setting up auto-unlock…",
    "Copying system Flatpaks":      "Installing your apps…",
    "Configuring installed system": "Configuring your system…",
    "Finalizing installation":      "Finishing up…",
}

# The product being installed, for labels that name it.
#
# A module-level value with a setter rather than a recipe import, to keep this
# module what its docstring says it is: a pure parser with no GTK and no file
# IO, importable by unit tests on its own. The default is deliberately neutral
# rather than any distro's name — an unset product must read as generic, not
# as somebody else's brand.
_PRODUCT_NAME = "the OS"


def set_product_name(name: str) -> None:
    """Set the product name used in step labels. Empty values are ignored."""
    global _PRODUCT_NAME
    if name:
        _PRODUCT_NAME = name


def get_product_name() -> str:
    """The product name step labels use; "the OS" until set_product_name()."""
    return _PRODUCT_NAME


def set_install_label(label: str) -> None:
    """Replace the label for the step that writes the OS image.

    That step is the one a user watches for most of the install, and its
    label is the branding contract's `progress_title` ("Installing {name}…"),
    so a frontend passes that line here to make it rebrandable. `{product}`
    and `{name}` are both filled with the product name. Empty values are
    ignored, keeping the neutral default.
    """
    if label:
        _FRIENDLY_STEP_LABELS["Installing OS"] = label.replace("{name}", "{product}")


def _friendly_label(step_name: str) -> str:
    """Human label for a fisherman step, with {product} filled in.

    Falls back to the raw step name, which is what unknown steps already did.
    A plain replace, not str.format: set_install_label() takes a line from a
    product's branding file, and a stray brace in it must not raise here.
    """
    label = _FRIENDLY_STEP_LABELS.get(step_name, step_name)
    return label.replace("{product}", _PRODUCT_NAME)


# Labels a step_id: a function from a step_id ("install_os") to the line to
# show, normally the branding copy key "step_" + step_id. None until a
# frontend sets one, so a bare parser falls back to the step-name table.
_STEP_LABEL_RESOLVER = None


def set_step_label_resolver(resolve) -> None:
    """Label steps by fisherman's step_id through `resolve(step_id) -> str`.

    A frontend passes a function that reads its branding copy key
    "step_" + step_id, so every step label is a rebrandable copy line
    (shared/branding/README.md). An empty result -- an id the copy does not
    know, or a line a product blanked -- falls back to the step name.
    """
    global _STEP_LABEL_RESOLVER
    _STEP_LABEL_RESOLVER = resolve


def _step_label(step_id: str, step_name: str) -> str:
    """The label for a step: the copy line for its step_id when there is one,
    else the step-name fallback (and, for an unknown name, the raw name)."""
    if step_id and _STEP_LABEL_RESOLVER is not None:
        label = _STEP_LABEL_RESOLVER(step_id)
        if label:
            return label
    return _friendly_label(step_name)


def _overall_fraction(event: dict) -> float | None:
    """fisherman's own bar position as a fraction, or None if the event has no
    overall_pct (an older fisherman)."""
    pct = event.get("overall_pct")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return None
    return min(max(pct / 100.0, 0.0), 1.0)


def _settle(state: dict, event: dict, derived: float | None) -> float | None:
    """The bar after `event`: its overall_pct when it carries one, else the
    fraction derived here (None means no change).

    overall_pct is authoritative. It never decreases on the wire; the max()
    keeps the bar from moving back even if it did.
    """
    overall = _overall_fraction(event)
    fraction = max(state["fraction"], overall) if overall is not None else derived
    if fraction is not None:
        state["fraction"] = fraction
    return fraction


# Matches "Pulling image: layer 23/71" substep messages from fisherman.
_RE_LAYER_PROGRESS = re.compile(r"Pulling image: layer (\d+)/(\d+)")

# Share of a step's weight that the layer pull covers. The rest is left for
# the export, deploy and bootloader phases that follow it, which have no
# counter of their own.
_PULL_SHARE = 0.6

# Bar positions for the silent phases after the pull, as a share of what is
# left of the step once the pull is over (all of it on an offline install,
# where nothing is pulled). Matched as message prefixes, in fisherman's order.
#
# Without these, an offline install sat at 1% from the start of "Installing
# OS" until the Flatpak copy: about ten minutes of export and deploy with no
# movement at all (#115). The deploy phase itself is still one long silence
# in bootc; these only make sure each phase fisherman does report moves the
# bar.
_PHASE_MILESTONES: tuple[tuple[str, float], ...] = (
    ("Exporting image to OCI layout", 0.05),
    ("OCI export complete", 0.30),
    ("Using ", 0.32),                     # "Using overlay storage driver ..."
    ("Initializing ostree layout", 0.35),
    ("Writing ", 0.35),                   # "Writing 64 (3.7 GB) to disk ..."
    ("Deploying image", 0.35),
    ("OS deployed, installing bootloader", 0.90),
    ("Detected bootloader", 0.92),
    ("Installing bootloader", 0.92),
    ("Configuring EFI boot entry", 0.95),
    ("Configuring GRUB", 0.95),
    ("Configuring SELinux", 0.95),
    ("Generating initramfs", 0.95),
    ("bootc installation complete", 1.0),
)


def _milestone(msg: str) -> float | None:
    """Position of a post-pull phase message within its share, or None."""
    for prefix, share in _PHASE_MILESTONES:
        if msg.startswith(prefix):
            return share
    return None


def new_progress_state() -> dict:
    """Return a fresh progress state dict (no GTK types)."""
    return {
        "pulse_active": True,
        "current_step": 0,
        "current_total": 0,
        "current_step_name": "",
        "current_step_id": "",
        "current_weight_pct": 0,
        "current_cumulative_pct": 0,
        "step_frac": 0.0,
        "post_pull_base": None,
        "seen_substeps": set(),
        "fraction": 0.0,
        "boot_id": "",
        "recovery_key": "",
        "error": None,
        "receipt": None,
        "source_reuse": None,
    }


RECEIPT_VERSION = 1
_RECEIPT_REASON = re.compile(r"^[a-z0-9_]{1,64}$")
_INSTALL_ID = re.compile(r"^[0-9a-f]{32}$")


def receipt_of(event: dict) -> dict:
    """What a frontend keeps of fisherman's `receipt` event (#269,
    tuna-os/fisherman#441): {"state", "install_id", "reason"}.

    state:
      check_set_up      `written` and `first_boot_check`: the receipt is on
                        the new system and its first start is recorded
      written_no_check  `written`, but the first-boot check is not staged
      not_written       no receipt is on the new system
      unreadable        a `version` other than 1, or a `written` that is
                        not a boolean, or a written receipt without a
                        32-hex install id

    `install_id` is set only when the receipt is written. `reason` is
    fisherman's code ("" when absent or not a code); a code that the copy
    does not know falls back to the unknown line, never the raw code.
    No state says that the new system started: only `fisherman verify` on
    that system can say so.
    """
    def view(state, install_id="", reason=""):
        return {"state": state, "install_id": install_id, "reason": reason}

    version = event.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != RECEIPT_VERSION:
        return view("unreadable")
    written = event.get("written")
    if not isinstance(written, bool):
        return view("unreadable")
    reason = event.get("reason")
    reason = reason if isinstance(reason, str) and _RECEIPT_REASON.match(reason) else ""
    if not written:
        return view("not_written", reason=reason)
    install_id = event.get("install_id")
    if not isinstance(install_id, str) or not _INSTALL_ID.match(install_id):
        return view("unreadable")
    if event.get("first_boot_check") is True:
        return view("check_set_up", install_id)
    return view("written_no_check", install_id, reason)


SOURCE_REUSE_VERSION = 1
SOURCE_REUSE_PHASES = ("planned", "copying", "verified", "failed", "released")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIB = 1 << 30


def _count(value):
    """A byte count or a time in ms: a whole number >= 0, else None."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _code(value) -> str:
    return value if isinstance(value, str) and _RECEIPT_REASON.match(value) else ""


def source_reuse_of(event: dict, view: dict | None) -> dict | None:
    """What a frontend keeps of fisherman's `source_reuse` events (#267,
    fisherman docs/SOURCE-REUSE.md): the copy of this computer's system
    before the first step. `view` is the one before this event, or None.

    {"phase", "required_bytes", "destination_digest", "copy_ms",
     "used_bytes", "code", "released", "destination"}

    phase: planned, copying, verified or failed, the last of them; or
    unreadable, for a `version` other than the number 1. `released` (the
    teardown removed the copy, before or after `failed`) sets only
    `released`: removed, remove_failed, or unknown for another reason.
    A phase that this parser does not know leaves the view as it was.
    Counts that are not whole numbers >= 0 are None. `used_bytes` is the
    largest drop in free space during the copy: the larger peak on one
    filesystem, the sum of both on two. shared/progress/source-reuse-cases.json.
    """
    out = dict(view) if view else {
        "phase": "", "required_bytes": None, "destination_digest": "", "copy_ms": None,
        "used_bytes": None, "code": "", "released": "", "destination": ""}
    version = event.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != SOURCE_REUSE_VERSION:
        out["phase"] = "unreadable"
        return out
    phase = event.get("phase")
    if phase not in SOURCE_REUSE_PHASES:
        return view
    destination = event.get("destination")
    if isinstance(destination, str) and destination:
        out["destination"] = destination
    if phase == "released":
        reason = _code(event.get("reason"))
        out["released"] = reason if reason in ("removed", "remove_failed") else "unknown"
        return out
    out["phase"] = phase
    estimate = event.get("estimate")
    estimate = estimate if isinstance(estimate, dict) else {}
    if "required_bytes" in estimate:
        out["required_bytes"] = _count(estimate.get("required_bytes"))
    if phase == "verified":
        digest = event.get("destination_digest")
        out["destination_digest"] = digest if isinstance(digest, str) and _DIGEST.match(digest) else ""
        measured = event.get("measured")
        measured = measured if isinstance(measured, dict) else {}
        out["copy_ms"] = _count(measured.get("copy_ms"))
        scratch = _count(measured.get("scratch_peak_bytes"))
        store = _count(measured.get("store_peak_bytes"))
        if scratch is None or store is None:
            out["used_bytes"] = None
        elif estimate.get("same_filesystem") is False:
            out["used_bytes"] = scratch + store
        else:
            out["used_bytes"] = max(scratch, store)
    if phase == "failed":
        out["code"] = _code(event.get("code"))
    return out


REUSE_PREFIX = "progress_reuse_"
REUSE_FAILED_PREFIX = REUSE_PREFIX + "failed_"
REUSE_FAILED_UNKNOWN = REUSE_FAILED_PREFIX + "unknown"


def gib(count: int) -> str:
    """Bytes as GiB with one decimal: the {value} of the space lines."""
    return f"{count / _GIB:.1f}"


def source_reuse_lines(view, has_copy=None):
    """The progress page's copy lines for the copy of this computer's
    system, in order: [(key, value)]; [] without a `source_reuse` event.

    planned: the space the copy needs (`progress_reuse_planned`, GiB), or
    `progress_reuse_planned_unknown`. copying: that line, then
    `progress_reuse_copying`. verified: `progress_reuse_verified`, the copy's
    digest, the time (whole seconds) and the space it used. failed: the
    space line when the estimate is known, then
    `progress_reuse_failed_<code without source_reuse_>`, or the unknown line
    for a code that the copy does not know. Then the release line.
    """
    if has_copy is None:
        from bootc_shared import _data
        keys = frozenset(k for k in _data.load_json("branding/copy-defaults.json")
                         if not k.startswith("_"))
        has_copy = keys.__contains__
    if not isinstance(view, dict):
        return []
    lines = []
    phase = view.get("phase")
    required = view.get("required_bytes")
    space = (REUSE_PREFIX + "planned", gib(required)) if required is not None else None
    if phase == "unreadable":
        lines.append((REUSE_PREFIX + "unreadable", ""))
    elif phase in ("planned", "copying"):
        lines.append(space or (REUSE_PREFIX + "planned_unknown", ""))
        if phase == "copying":
            lines.append((REUSE_PREFIX + "copying", ""))
    elif phase == "verified":
        lines.append((REUSE_PREFIX + "verified", ""))
        if view.get("destination_digest"):
            lines.append((REUSE_PREFIX + "verified_digest", view["destination_digest"]))
        if view.get("copy_ms") is not None:
            lines.append((REUSE_PREFIX + "measured_time", str((view["copy_ms"] + 500) // 1000)))
        if view.get("used_bytes") is not None:
            lines.append((REUSE_PREFIX + "measured_space", gib(view["used_bytes"])))
    elif phase == "failed":
        if space:
            lines.append(space)
        code = view.get("code") or ""
        key = REUSE_FAILED_PREFIX + code[len("source_reuse_"):] if code.startswith("source_reuse_") else ""
        lines.append((key if key and has_copy(key) else REUSE_FAILED_UNKNOWN, ""))
    released = view.get("released")
    if released:
        destination = view.get("destination") or ""
        if destination.startswith("containers-storage:"):
            destination = destination[len("containers-storage:"):]
        lines.append((REUSE_PREFIX + "released_" + released,
                      destination if released == "remove_failed" else ""))
    return lines


def source_reuse_text(view, text):
    """source_reuse_lines() as the strings to show: `text(key)` is the
    frontend's copy resolver. An empty line (a product hid it) is left
    out."""
    out = []
    for key, value in source_reuse_lines(view):
        line = text(key).replace("{value}", value)
        if line:
            out.append(line)
    return out


def copy_cancel(state: dict) -> bool:
    """Whether a cancel now stops the copy of this computer's system and
    leaves the disk as it was: a `source_reuse` event came, the copy has
    not failed and is not released, and no step has started. The cancel question then says
    `progress_reuse_cancel` instead of the warning about the disk."""
    view = state.get("source_reuse")
    return (isinstance(view, dict) and view.get("phase") in ("planned", "copying", "verified")
            and not view.get("released") and not state.get("current_step"))


CLEANUP_STATUSES = ("ok", "failed", "timed_out")


def _error_of(event: dict) -> dict:
    """The parts of an `error` event a frontend shows or logs
    (fisherman docs/JSON-PROGRESS-FORMAT.md, tuna-os/fisherman#449):

      message, code, field, step_id
                    strings; "" when missing or not a string (an older
                    fisherman sends only `message`)
      disk_changed  True or False as fisherman sent it; None when it is
                    missing or not a boolean: then nothing is said about
                    the disk
      cleanup       {"status", "message"}, or None when it is missing or
                    not an object. `status` is ok, failed or timed_out,
                    "" for any other value
    """
    def text(source, key):
        value = source.get(key, "")
        return value if isinstance(value, str) else ""
    disk_changed = event.get("disk_changed")
    cleanup = event.get("cleanup")
    if isinstance(cleanup, dict):
        status = text(cleanup, "status")
        cleanup = {"status": status if status in CLEANUP_STATUSES else "",
                   "message": text(cleanup, "message")}
    else:
        cleanup = None
    return {"message": text(event, "message"), "code": text(event, "code"),
            "field": text(event, "field"), "step_id": text(event, "step_id"),
            "disk_changed": disk_changed if isinstance(disk_changed, bool) else None,
            "cleanup": cleanup}


# The failure page's lines for the `error` event, as copy keys
# (shared/branding/copy-defaults.json).
FAILURE_DISK_CHANGED = "done_failed_disk_changed"
FAILURE_DISK_UNCHANGED = "done_failed_disk_unchanged"
FAILURE_CLEANUP = {"failed": "done_failed_cleanup_failed",
                   "timed_out": "done_failed_cleanup_timed_out"}


def failure_lines(error) -> list:
    """The copy keys the failure page shows for fisherman's last `error`
    event (`_error_of`), in order: whether the disk changed, then a
    cleanup that failed or timed out. A part fisherman did not send adds
    no line: an older fisherman's page says nothing about the disk."""
    if not isinstance(error, dict):
        return []
    lines = []
    if error.get("disk_changed") is True:
        lines.append(FAILURE_DISK_CHANGED)
    elif error.get("disk_changed") is False:
        lines.append(FAILURE_DISK_UNCHANGED)
    cleanup = error.get("cleanup")
    if isinstance(cleanup, dict) and cleanup.get("status") in FAILURE_CLEANUP:
        lines.append(FAILURE_CLEANUP[cleanup["status"]])
    return lines


def failure_text(error, text) -> list:
    """failure_lines() as the strings to show: `text(key)` is the
    frontend's copy resolver. An empty line (a product hid it) is left
    out."""
    return [line for line in (text(key) for key in failure_lines(error)) if line]


def apply_progress_event(line: str, state: dict) -> dict | None:
    """Parse one fisherman log line and return a UI-update dict, or None.

    Pure function — no GTK, no I/O.  The returned dict has:
      "fraction"  — float 0-1 for progressbar.set_fraction(): the event's
                    overall_pct when it has one, else derived (None = no change)
      "label"     — str for progressbar_text.set_label() (None = no change)
      "pulse"     — bool; True means switch bar to pulse mode
      "complete"  — bool; True means install finished
    An `error` event returns the same dict with no change in it, plus
      "error"     — {"message", "code", "field", "step_id", "disk_changed",
                    "cleanup"}: why fisherman failed (`_error_of`)
    ``state`` is mutated in-place to track multi-line context.
    Returns None for non-JSON lines or events that require no UI change.
    """
    if not line.startswith("{"):
        return None
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    event_type = event.get("type", "")

    if event_type == "step":
        step = event.get("step", 0)
        total = event.get("total_steps", 1)
        name = event.get("step_name", "Installing")
        if step <= state["current_step"] and state["current_step"] > 0:
            return None
        cumulative_pct = event.get("cumulative_pct", 0)
        state["current_weight_pct"] = event.get("weight_pct", 0)
        state["current_cumulative_pct"] = cumulative_pct
        state["current_step"] = step
        state["current_total"] = total
        state["current_step_name"] = name
        state["current_step_id"] = event.get("step_id") or ""
        state["step_frac"] = 0.0
        state["post_pull_base"] = None
        state["seen_substeps"].clear()
        state["pulse_active"] = False
        return {
            "fraction": _settle(state, event, cumulative_pct / 100.0),
            "label": _step_label(state["current_step_id"], name),
            "pulse": False,
            "complete": False,
        }

    if event_type == "substep":
        msg = event.get("message", "")
        if not msg:
            return None
        derived = None
        if state["current_weight_pct"] > 0:
            step_frac = None
            m = _RE_LAYER_PROGRESS.match(msg)
            if m:
                done = int(m.group(1))
                total_layers = int(m.group(2))
                if total_layers > 0:
                    step_frac = min(done / total_layers, 1.0) * _PULL_SHARE
            else:
                share = _milestone(msg)
                if share is not None:
                    if state["post_pull_base"] is None:
                        state["post_pull_base"] = state["step_frac"]
                    base = state["post_pull_base"]
                    step_frac = base + share * (1.0 - base)
            if step_frac is not None:
                # Never move backwards: a retried pull restarts its layer count.
                state["step_frac"] = max(state["step_frac"], step_frac)
                derived = min(
                    (state["current_cumulative_pct"]
                     + state["step_frac"] * state["current_weight_pct"]) / 100.0,
                    1.0,
                )
        fraction = _settle(state, event, derived)
        if msg in state["seen_substeps"]:
            # Still update fraction even for duplicate substep messages.
            if fraction is not None:
                return {"fraction": fraction, "label": None, "pulse": False, "complete": False}
            return None
        state["seen_substeps"].add(msg)
        label = None
        if state["current_step"]:
            label = _step_label(state["current_step_id"], state["current_step_name"])
        return {"fraction": fraction, "label": label, "pulse": False, "complete": False}

    if event_type == "recovery_key":
        state["recovery_key"] = event.get("key", "")
        return None

    if event_type == "receipt":
        # What the install did with the installation receipt. It moves no
        # bar and fails nothing: the done page reads it from the state.
        state["receipt"] = receipt_of(event)
        return None

    if event_type == "source_reuse":
        # The copy of this computer's system, before the first step. It
        # moves no bar: the bar pulses until fisherman's first step.
        state["source_reuse"] = source_reuse_of(event, state["source_reuse"])
        return {"fraction": None, "label": None, "pulse": state["pulse_active"],
                "complete": False, "source_reuse": state["source_reuse"]}

    if event_type == "complete":
        state["pulse_active"] = False
        state["fraction"] = 1.0
        state["boot_id"] = event.get("boot_id", "")
        state["recovery_key"] = event.get("recovery_key", state["recovery_key"])
        return {"fraction": 1.0, "label": "Installation complete!",
                "pulse": False, "complete": True}

    if event_type == "error":
        # fisherman's reason for the failure. The last one is kept in the
        # state: the frontend shows it when the process exits non-zero,
        # instead of a search of the log for "fatal:".
        state["error"] = _error_of(event)
        return {"fraction": None, "label": None, "pulse": False, "complete": False,
                "error": {**state["error"], "cleanup": (dict(state["error"]["cleanup"])
                                                        if state["error"]["cleanup"] else None)}}

    return None


EXIT_CANCELLED = 130


def install_outcome(exit_code, cancel_requested: bool) -> str:
    """How an install ended: "succeeded", "cancelled" or "failed"
    (shared/progress/outcome-cases.json).

    `exit_code` is the wrapper's exit code, or None when a signal ended
    it. The exit code decides, never a `complete` event: fisherman can
    write `complete` and still exit non-zero. 0 is success, even after a
    cancel that came too late. 130 is fisherman's cancel, whoever asked.
    After the user confirmed a cancel, a signal (None, or a shell's
    128 + n) is the cancel too: the frontend signalled the wrapper's
    group. Any other exit code is a failure, cancel or not: fisherman
    failed before the cancel reached it.
    """
    if exit_code == 0:
        return "succeeded"
    if exit_code == EXIT_CANCELLED:
        return "cancelled"
    if cancel_requested and (exit_code is None or exit_code > 128):
        return "cancelled"
    return "failed"


def render_event(line: str) -> str | None:
    """A fisherman event as a line a person would want to read.

    Returns None for a line that is not a fisherman event, which the caller
    should show verbatim — fisherman's stderr is interleaved into the same
    view and is already human-readable.

    This exists because the protocol is machine-readable and the frontends
    show it to people. A log pane fed raw stdout renders as a wall of JSON;
    the screenshot harness caught exactly that on the XFCE install screen.
    The step NAME is used here, not the friendly label: the log is the thing
    people paste into bug reports, so it should say what fisherman said.
    """
    if not line.startswith("{"):
        return None
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(event, dict):
        return None

    kind = event.get("type", "")
    if kind == "step":
        step = event.get("step", 0)
        total = event.get("total_steps", 0)
        return f"[{step}/{total}] {event.get('step_name', '')}"
    if kind in ("substep", "info"):
        message = event.get("message", "")
        return f"  {message}" if message else None
    if kind == "complete":
        return event.get("message", "Installation complete")
    if kind == "error":
        return f"ERROR: {event.get('message', '')}"
    if kind == "receipt":
        written = event.get("written") is True
        line = "Installation receipt: " + ("written" if written else "not written")
        if written and isinstance(event.get("install_id"), str):
            line += f", install id {event['install_id']}"
        if isinstance(event.get("reason"), str) and event["reason"]:
            line += f" ({event['reason']})"
        return line
    if kind == "source_reuse":
        phase = event.get("phase", "")
        line = f"Source reuse: {phase}" if isinstance(phase, str) else "Source reuse"
        if isinstance(event.get("code"), str) and event["code"]:
            line += f" ({event['code']})"
        return line
    if kind == "recovery_key":
        # Shown, not hidden. A frontend with no recovery-key screen (see
        # docs/PARITY.md) leaves this as the only place the user can read a
        # key they cannot recover later; suppressing it here would lose it.
        return f"Recovery key: {event.get('key', '')}"
    return None


def transcript_path():
    """Where dry-run-transcript.ndjson is: the events of one install, which
    a demo mode or a capture harness replays (shared/progress/README.md)."""
    return _data.path("progress/dry-run-transcript.ndjson")
