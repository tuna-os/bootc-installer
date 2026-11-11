"""What a frontend shows from fisherman's source-scoped probe (#266, #267).

`fisherman probe --json --source <ref> [--target-imgref <ref>]` (or
`--live-root`) adds two objects to the probe: `capabilities`, what the
selected source's own bootc can do (tuna-os/fisherman#383), and
`bootc_store`, the images that the live host's bootc keeps
(tuna-os/fisherman#384). fisherman/docs/PROBE.md owns both schemas;
shared/probe/README.md says what a frontend renders.

This module is the canonical reader. It decides no compatibility rule of
its own: it turns fisherman's answer into one of the states below and
picks the copy keys. GNOME and XFCE import it; KDE, COSMIC and Niri have a
port in their own language. shared/probe/capabilities-cases.json and
bootc-store-cases.json hold all five to the same answers
(tests/unit/test_shared_source_check.py writes and checks them).

States of the source check:

  checking     a reply for the current selection has not come yet (UI only)
  ready        the source's own bootc answered, and nothing blocks
  blocked      the recipe asks for a feature that fisherman reports as
               unsupported; fisherman refuses the install
  unsupported  this fisherman does not report capabilities, or reports a
               version that this reader does not know
  unavailable  no answer about the source: the probe failed, its output is
               malformed, or no root that the probe may run is the source's
  stale        the reply is for another source or target: drop it

`unavailable` is never a green check, and only `blocked` holds Install.
"""

import re

from bootc_shared import _data

CAPABILITIES_VERSION = 1
BOOTC_STORE_VERSION = 1

# The feature names of capabilities.version 1. An unknown name is ignored.
FEATURES = (
    "bootc_image_storage",
    "deployment_mount",
    "finalization",
    "install_configuration",
    "native_inspection",
    "unified_storage",
)

STATUSES = ("supported", "unsupported", "unknown")

TITLE_PREFIX = "source_check_"
REASON_PREFIX = "source_check_reason_"
REASON_UNKNOWN = REASON_PREFIX + "unknown"
KIND_PREFIX = "bootc_store_kind_"

_TOKEN = re.compile(r"^[a-z0-9_]{1,64}$")


def _copy_keys():
    raw = _data.load_json("branding/copy-defaults.json")
    return frozenset(k for k in raw if not k.startswith("_"))


def _obj(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) else ""


def _true(value):
    return value is True


def _int(value):
    """An int that is not a bool, else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _token(value):
    value = _str(value)
    return value if _TOKEN.match(value) else "unknown"


def reason_key(reason, has_copy=None):
    """The copy key that explains `reason`; the unknown line when the
    contract has no line for it. A code is never shown raw."""
    if has_copy is None:
        keys = _copy_keys()
        has_copy = keys.__contains__
    key = REASON_PREFIX + _token(reason)
    return key if has_copy(key) else REASON_UNKNOWN


def request(source="", live_root=False, target="", features=()):
    """The selection a probe was run for. `source` is the recipe's `image`,
    `live_root` means the recipe leaves `image` empty on live media, and
    `target` is the recipe's `targetImgref`. `features` are the feature
    names that the recipe asks for (today only `unified_storage`, when a
    recipe sets `unifiedStorage`)."""
    return {"source": source or "", "live_root": bool(live_root),
            "target": target or "", "features": list(features)}


def probe_args(req):
    """The arguments after `probe --json` that select `req`. [] when the
    selection names no source (the probe then answers no_source_selected)."""
    args = []
    if req.get("live_root"):
        args.append("--live-root")
    elif req.get("source"):
        args += ["--source", req["source"]]
    else:
        return []
    if req.get("target"):
        args += ["--target-imgref", req["target"]]
    return args


def _view(state, reason, has_copy):
    return {
        "state": state,
        "reason": reason,
        "reason_key": reason_key(reason, has_copy),
        "install_from": "",
        "update_ref": "",
        "live_host_image": "",
        "source_digest": "",
        "defaults": [],
        "blockers": [],
    }


def _is_stale(caps, req):
    source = _obj(caps.get("source"))
    target = _obj(caps.get("target"))
    if req.get("live_root"):
        if _str(source.get("transport")) != "live-root":
            return True
    elif req.get("source"):
        if (_str(source.get("ref")) != req["source"]
                or _str(source.get("transport")) == "live-root"):
            return True
    elif _true(source.get("selected")):
        return True
    from_target = _str(target.get("update_ref_from")) == "target_imgref"
    if req.get("target"):
        return not from_target or _str(target.get("update_ref")) != req["target"]
    return from_target


def source_check(result, req, has_copy=None):
    """The view of the source check. `result` is the parsed probe output,
    or None when the probe failed. `req` is request()."""
    if has_copy is None:
        keys = _copy_keys()
        has_copy = keys.__contains__
    if not isinstance(result, dict):
        return _view("unavailable", "probe_failed", has_copy)
    if "capabilities" not in result:
        return _view("unsupported", "backend_too_old", has_copy)
    caps = result.get("capabilities")
    if not isinstance(caps, dict) or _int(caps.get("version")) is None:
        return _view("unavailable", "malformed", has_copy)
    if caps["version"] != CAPABILITIES_VERSION:
        return _view("unsupported", "version_unsupported", has_copy)
    if _is_stale(caps, req):
        return _view("stale", "reply_for_other_source", has_copy)

    source = _obj(caps.get("source"))
    root = _obj(caps.get("execution_root"))
    features = _obj(caps.get("features"))

    blockers = []
    for name in req.get("features") or []:
        if name in FEATURES and _str(_obj(features.get(name)).get("status")) == "unsupported":
            blockers.append(name)

    if blockers:
        state, reason = "blocked", "feature_unsupported"
    elif not _true(source.get("selected")):
        state, reason = "unavailable", "no_source_selected"
    elif not _true(root.get("established")):
        state, reason = "unavailable", _token(root.get("reason"))
        digest_reason = _str(source.get("digest_reason"))
        if reason == "source_digest_unknown" and digest_reason:
            reason = _token(digest_reason)
    else:
        state, reason = "ready", _token(root.get("reason"))

    view = _view(state, reason, has_copy)
    view["install_from"] = _str(source.get("ref"))
    view["update_ref"] = _str(_obj(caps.get("target")).get("update_ref"))
    view["live_host_image"] = _str(_obj(caps.get("live_host")).get("image"))
    view["source_digest"] = _str(source.get("digest"))
    view["blockers"] = blockers
    defaults = _obj(caps.get("install_defaults"))
    if state == "ready" and _true(defaults.get("observed")):
        lines = []
        fs = _str(defaults.get("root_filesystem"))
        if fs:
            lines.append({"key": "source_check_default_filesystem", "value": fs})
        setups = defaults.get("block_setups")
        if isinstance(setups, list):
            setups = [s for s in setups if isinstance(s, str) and s]
            if setups:
                lines.append({"key": "source_check_default_block_setups",
                              "value": ", ".join(setups)})
        loader = _str(defaults.get("bootloader"))
        if loader:
            lines.append({"key": "source_check_default_bootloader", "value": loader})
        view["defaults"] = lines
    return view


def blocks_install(view):
    """Whether Install must wait: only a blocked source holds it. Every
    other state leaves the decision to fisherman, which revalidates before
    it touches a disk."""
    return view.get("state") == "blocked"


AVAILABILITIES = ("deployed", "stored", "listed")


def bootc_store(result):
    """The view of the live host's bootc storage (#267).

    state: "listed" (items to show), "empty", "unavailable" or
    "unsupported". Each item is an image that the live host's bootc keeps:
    it describes the machine that runs the installer, never the target.
    `installable` is false for each item: no fisherman install path reads
    bootc-owned storage yet (fisherman/docs/PROBE.md, "Reuse is not
    implemented"), so a frontend shows the items and offers none of them
    as a source, and never as available offline.
    """
    def view(state, reason):
        return {"state": state, "reason": reason, "items": [], "hidden": 0}

    if not isinstance(result, dict):
        return view("unavailable", "probe_failed")
    if "bootc_store" not in result:
        return view("unsupported", "backend_too_old")
    store = result.get("bootc_store")
    if not isinstance(store, dict) or _int(store.get("version")) is None:
        return view("unavailable", "malformed")
    if store["version"] != BOOTC_STORE_VERSION:
        return view("unsupported", "version_unsupported")
    if not _true(store.get("available")):
        return view("unavailable", _token(store.get("reason")))
    raw = store.get("items")
    if not isinstance(raw, list):
        return view("unavailable", "malformed")
    items, hidden = [], 0
    for item in raw:
        item = _obj(item)
        ref = _str(item.get("ref"))
        if (not ref or _str(item.get("owner")) != "bootc"
                or _str(item.get("context")) != "live-host"):
            hidden += 1
            continue
        roles = [r for r in item.get("roles") or [] if isinstance(r, str)] \
            if isinstance(item.get("roles"), list) else []
        availability = _str(item.get("availability"))
        if availability not in AVAILABILITIES:
            availability = "listed"
        kind = "booted" if "booted" in roles else availability
        items.append({
            "ref": ref,
            "kind": kind,
            "availability": availability,
            "storage": _str(item.get("storage")) or "unknown",
            "digest": _str(item.get("digest")),
            "platform": _str(item.get("platform")),
            "matches_machine": _true(item.get("matches_machine")),
            "installable": False,
        })
    out = view("listed" if items else "empty", "observed")
    out["items"] = items
    out["hidden"] = hidden
    return out


def recipe_request(recipe, is_live):
    """request() for a recipe as the frontend will send it: `image` is the
    source (empty on live media: the running system), `targetImgref` the
    target, and `unifiedStorage` asks for that feature. The probe gets the
    references only, never the recipe."""
    recipe = recipe if isinstance(recipe, dict) else {}
    image = _str(recipe.get("image"))
    features = ["unified_storage"] if recipe.get("unifiedStorage") is True else []
    return request(source=image, live_root=(not image and bool(is_live)),
                   target=_str(recipe.get("targetImgref")), features=features)


def rows(view, store, text):
    """The rows a Python frontend shows for the source check: a list of
    (title, subtitle). `view` is source_check() (None while checking),
    `store` is bootc_store() (None to leave it out), `text(key)` is the
    frontend's copy resolver. A stale view shows as checking: the reply
    that it was is dropped."""
    out = []
    if view is None or view.get("state") == "stale":
        return [(text(TITLE_PREFIX + "checking"), "")]

    def value_line(key, value):
        if value:
            out.append((text(key).replace("{value}", value), ""))

    value_line("source_install_from", view.get("install_from", ""))
    value_line("source_update_ref", view.get("update_ref", ""))
    value_line("source_live_host", view.get("live_host_image", ""))
    out.append((text(TITLE_PREFIX + view["state"]), text(view["reason_key"])))
    for line in view.get("defaults") or []:
        value_line(line["key"], line["value"])
    if store and store.get("state") == "listed":
        out.append((text("bootc_store_listed"), ""))
        for item in store["items"]:
            out.append((item["ref"], text(KIND_PREFIX + item["kind"])))
    return out
