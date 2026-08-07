"""progress_parser.py — Pure fisherman progress-event parser (no GTK).

Provides apply_progress_event() and _new_progress_state() for use by
BootcProgress and for unit tests.
"""

import json
import re

# Human-friendly labels for each fisherman step name.
# Keys must match the step_name strings emitted by fisherman exactly.
# Unknown step names fall back to the raw step_name.
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


def _friendly_label(step_name: str) -> str:
    """Human label for a fisherman step, with {product} filled in.

    Falls back to the raw step name, which is what unknown steps already did.
    Only labels containing the placeholder are formatted, so a future label
    with a literal brace cannot raise here.
    """
    label = _FRIENDLY_STEP_LABELS.get(step_name, step_name)
    if "{product}" in label:
        return label.format(product=_PRODUCT_NAME)
    return label


# Matches "Pulling image: layer 23/71" substep messages from fisherman.
_RE_LAYER_PROGRESS = re.compile(r"Pulling image: layer (\d+)/(\d+)")


def new_progress_state() -> dict:
    """Return a fresh progress state dict (no GTK types)."""
    return {
        "pulse_active": True,
        "current_step": 0,
        "current_total": 0,
        "current_step_name": "",
        "current_weight_pct": 0,
        "current_cumulative_pct": 0,
        "seen_substeps": set(),
        "boot_id": "",
        "recovery_key": "",
    }


def apply_progress_event(line: str, state: dict) -> dict | None:
    """Parse one fisherman log line and return a UI-update dict, or None.

    Pure function — no GTK, no I/O.  The returned dict has:
      "fraction"  — float 0-1 for progressbar.set_fraction()
      "label"     — str for progressbar_text.set_label() (None = no change)
      "pulse"     — bool; True means switch bar to pulse mode
      "complete"  — bool; True means install finished
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
        state["seen_substeps"].clear()
        state["pulse_active"] = False
        friendly = _friendly_label(name)
        return {
            "fraction": cumulative_pct / 100.0,
            "label": friendly,
            "pulse": False,
            "complete": False,
        }

    if event_type == "substep":
        msg = event.get("message", "")
        if not msg:
            return None
        fraction = None
        m = _RE_LAYER_PROGRESS.match(msg)
        if m and state["current_weight_pct"] > 0:
            done = int(m.group(1))
            total_layers = int(m.group(2))
            sub_frac = done / total_layers
            fraction = min(
                (state["current_cumulative_pct"] + sub_frac * state["current_weight_pct"]) / 100.0,
                1.0,
            )
        if msg in state["seen_substeps"]:
            # Still update fraction even for duplicate substep messages.
            if fraction is not None:
                return {"fraction": fraction, "label": None, "pulse": False, "complete": False}
            return None
        state["seen_substeps"].add(msg)
        label = None
        if state["current_step"]:
            friendly = _friendly_label(state["current_step_name"])
            label = friendly
        return {"fraction": fraction, "label": label, "pulse": False, "complete": False}

    if event_type == "recovery_key":
        state["recovery_key"] = event.get("key", "")
        return None

    if event_type == "complete":
        state["pulse_active"] = False
        state["boot_id"] = event.get("boot_id", "")
        state["recovery_key"] = event.get("recovery_key", state["recovery_key"])
        return {"fraction": 1.0, "label": "Installation complete!", "pulse": False, "complete": True}

    return None
