#!/usr/bin/env python3
"""Write capabilities-cases.json, bootc-store-cases.json,
source-reuse-cases.json and ../completion/verification-cases.json from the canonical Python readers.

Each case names a fixture file and the selection that the probe ran for.
The expected view comes from bootc_shared.source_check and
bootc_shared.completion; every frontend's reader must give the same view.
Run it after a change to a reader or to a fixture:

    python3 shared/probe/generate-source-check-cases.py

tests/unit/test_shared_source_check.py fails when a file is out of date.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SHARED, "python"))

from bootc_shared import completion, source_check

STABLE = "containers-storage:ghcr.io/example/os:stable"
TARGET = "ghcr.io/example/os:stable"

# name, fixture (relative to fixtures/capabilities/, None = see note), request
CAPABILITY_CASES = [
    ("probe-failed", "PROBE_FAILED", {"source": STABLE, "target": TARGET}),
    ("old-backend", None, {"source": STABLE, "target": TARGET}),
    ("matching-ostree-current", "caps-matching-ostree-current.json",
     {"source": STABLE, "target": TARGET}),
    ("matching-composefs", "caps-matching-composefs.json", None),
    ("matching-older", "caps-matching-older.json", None),
    ("live-root", "caps-live-root.json", {"live_root": True}),
    ("no-source", "caps-no-source.json", {}),
    ("remote-source", "caps-remote-source.json", {"source": TARGET}),
    ("pinned-reference", "caps-pinned-reference.json", None),
    ("oci-layout", "caps-oci-layout.json", None),
    ("local-not-found", "caps-local-not-found.json", None),
    ("ambiguous", "caps-ambiguous.json", None),
    ("unrelated-live-host", "caps-unrelated-live-host.json", None),
    ("host-bootc-missing", "caps-host-bootc-missing.json", None),
    ("check-failed", "caps-check-failed.json", None),
    ("malformed-output", "caps-malformed.json", None),
    ("unknown-fields", "caps-unknown-fields.json", None),
    ("wrong-types", "caps-wrong-types.json", None),
    ("blocked-unified-storage", "caps-matching-ostree-current.json",
     {"source": STABLE, "target": TARGET, "features": ["unified_storage"]}),
    ("stale-other-source", "caps-matching-ostree-current.json",
     {"source": "containers-storage:ghcr.io/example/os:next", "target": TARGET}),
    ("stale-other-target", "caps-matching-ostree-current.json",
     {"source": STABLE, "target": "ghcr.io/example/os:next"}),
    ("stale-target-dropped", "caps-matching-ostree-current.json", {"source": STABLE}),
    ("stale-live-root-reply", "caps-live-root.json", {"source": TARGET}),
    ("version-2", "frontend-version-2.json", {"source": STABLE, "target": TARGET}),
    ("not-an-object", "frontend-not-object.json", {"source": STABLE, "target": TARGET}),
    ("unknown-codes", "frontend-unknown-codes.json", {"source": STABLE, "target": TARGET}),
]

STORE_CASES = [
    ("probe-failed", "PROBE_FAILED"),
    ("old-backend", None),
    ("version-2", "frontend-version-2.json"),
    ("not-an-object", "frontend-not-object.json"),
    ("unknown-values", "frontend-unknown-values.json"),
]

# name, fixture (fixtures/bootc-store/, None = no bootc_store, PROBE_FAILED),
# live (`live.is_live`; None = no `live` object), update reference
REUSE_CASES = [
    ("probe-failed", "PROBE_FAILED", False, TARGET),
    ("old-backend", None, False, TARGET),
    ("booted-on-an-installed-host", "store-inaccessible.json", False, TARGET),
    ("docker-transport-on-the-update-ref", "store-inaccessible.json", False,
     "docker://" + TARGET),
    ("live-media", "store-inaccessible.json", True, TARGET),
    ("no-live-facts", "store-inaccessible.json", None, TARGET),
    ("other-update-ref", "store-inaccessible.json", False, "ghcr.io/example/os:next"),
    ("no-update-ref", "store-inaccessible.json", False, ""),
    ("staged-update-moves-the-ref", "store-bootc-host-default.json", False, TARGET),
    ("rollback-with-the-same-ref", "frontend-reuse-rollback.json", False, TARGET),
    ("untrusted-items", "frontend-reuse-untrusted.json", False, TARGET),
    ("version-2", "frontend-version-2.json", False, TARGET),
    ("not-an-object", "frontend-not-object.json", False, TARGET),
    ("unknown-values", "frontend-unknown-values.json", False, TARGET),
    # fisherman's golden inventory of live media: the probe says is_live.
    ("store-live-media", "store-live-media.json", True, TARGET),
]

# The recipe that a frontend builds for TARGET before the user picks this
# computer's system; `recipe` in a case is what apply_reuse() makes of it.
REUSE_BASE_RECIPE = {
    "disk": "/dev/vda",
    "filesystem": "xfs",
    "encryption": {"type": "none", "passphrase": ""},
    "image": TARGET,
    "targetImgref": TARGET,
    "composeFsBackend": False,
    "hostname": "workstation",
}

VERIFY_CASES = [
    ("not-json", "frontend-not-json.txt", ""),
    ("version-2", "frontend-version-2.json", ""),
    ("other-schema", "frontend-other-schema.json", ""),
    ("unknown-outcome", "frontend-unknown-outcome.json", ""),
    ("unknown-reason", "frontend-unknown-reason.json", ""),
    ("verified-but-check-mismatch", "frontend-verified-check-mismatch.json", ""),
    ("stale-prior-install", "ostree-collected-verified.json",
     "fedcba9876543210fedcba9876543210"),
    ("bound-to-this-install", "ostree-collected-verified.json",
     "0123456789abcdef0123456789abcdef"),
]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def request_from(caps):
    """The selection that fisherman's golden reply answers."""
    source = caps.get("source") or {}
    target = caps.get("target") or {}
    req = {}
    if source.get("transport") == "live-root":
        req["live_root"] = True
    elif source.get("ref"):
        req["source"] = source["ref"]
    if target.get("update_ref_from") == "target_imgref":
        req["target"] = target["update_ref"]
    return req


def full_request(req):
    return source_check.request(**req)


def capability_cases():
    fixtures = os.path.join(HERE, "fixtures", "capabilities")
    golden = sorted(f for f in os.listdir(fixtures) if f.startswith("caps-"))
    named = {c[1] for c in CAPABILITY_CASES}
    missing = [f for f in golden if f not in named]
    if missing:
        sys.exit(f"no case reads {missing}")
    out = []
    for name, fixture, req in CAPABILITY_CASES:
        if fixture == "PROBE_FAILED":
            probe = None
        elif fixture is None:
            probe = {"protocol_version": 1}
        else:
            caps = load(os.path.join(fixtures, fixture))
            probe = {"protocol_version": 1, "capabilities": caps}
            if req is None:
                req = request_from(caps)
        req = full_request(req or {})
        view = source_check.source_check(probe, req)
        case = {"name": name, "fixture": fixture if fixture != "PROBE_FAILED" else None,
                "probe_failed": fixture == "PROBE_FAILED", "request": req,
                "probe_args": source_check.probe_args(req), "expected": view,
                "blocks_install": source_check.blocks_install(view)}
        out.append(case)
    return out


def store_cases():
    fixtures = os.path.join(HERE, "fixtures", "bootc-store")
    cases = list(STORE_CASES) + [
        (f[len("store-"):-len(".json")], f)
        for f in sorted(os.listdir(fixtures)) if f.startswith("store-")]
    out = []
    for name, fixture in cases:
        if fixture == "PROBE_FAILED":
            probe = None
        elif fixture is None:
            probe = {"protocol_version": 1}
        else:
            probe = {"protocol_version": 1,
                     "bootc_store": load(os.path.join(fixtures, fixture))}
        out.append({"name": name,
                    "fixture": fixture if fixture != "PROBE_FAILED" else None,
                    "probe_failed": fixture == "PROBE_FAILED",
                    "expected": source_check.bootc_store(probe)})
    return out


def reuse_cases():
    fixtures = os.path.join(HERE, "fixtures", "bootc-store")
    golden = sorted(f for f in os.listdir(fixtures) if f.startswith("store-"))
    named = {c[1] for c in REUSE_CASES}
    cases = list(REUSE_CASES) + [
        ("store-" + f[len("store-"):-len(".json")], f, False, TARGET)
        for f in golden if f not in named]
    out = []
    for name, fixture, live, update_ref in cases:
        if fixture == "PROBE_FAILED":
            probe = None
        else:
            probe = {"protocol_version": 1}
            if fixture is not None:
                probe["bootc_store"] = load(os.path.join(fixtures, fixture))
            if live is not None:
                probe["live"] = {"is_live": live}
        source = source_check.reuse_source(probe, update_ref)
        case = {"name": name,
                "fixture": fixture if fixture != "PROBE_FAILED" else None,
                "probe_failed": fixture == "PROBE_FAILED",
                "live": live, "update_ref": update_ref, "expected": source}
        if source:
            recipe = source_check.apply_reuse(
                {**REUSE_BASE_RECIPE, "image": update_ref, "targetImgref": update_ref}, source)
            case["recipe"] = recipe
            case["fragment"] = source_check.reuse_fragment(recipe)
            case["request"] = source_check.recipe_request(recipe, False)
            case["probe_args"] = source_check.probe_args(case["request"])
        out.append(case)
    return out


def verify_cases():
    fixtures = os.path.join(SHARED, "completion", "fixtures")
    cases = [(f[:-len(".json")], f, "") for f in sorted(os.listdir(fixtures))
             if f.endswith(".json") and not f.startswith("frontend-")]
    cases += VERIFY_CASES
    out = []
    for name, fixture, install_id in cases:
        with open(os.path.join(fixtures, fixture), encoding="utf-8") as fh:
            text = fh.read()
        out.append({"name": name, "fixture": fixture,
                    "expected_install_id": install_id,
                    "expected": completion.verification(text, install_id)})
    return out


def document(comment, cases):
    return json.dumps({"_comment": comment, "cases": cases}, indent=2) + "\n"


FILES = {
    os.path.join(HERE, "capabilities-cases.json"): ((
        "Generated by generate-source-check-cases.py from bootc_shared.source_check. "
        "Each case: the probe is {protocol_version: 1, capabilities: <fixtures/capabilities/"
        "fixture>}; fixture null is a probe without capabilities (an older fisherman); "
        "probe_failed means the probe gave no result. `request` is the selection the "
        "frontend probed for. Every frontend's reader must give `expected` and "
        "`blocks_install`. See README.md, 'Source check'."), capability_cases),
    os.path.join(HERE, "bootc-store-cases.json"): ((
        "Generated by generate-source-check-cases.py from bootc_shared.source_check. "
        "Each case: the probe is {protocol_version: 1, bootc_store: <fixtures/bootc-store/"
        "fixture>}; fixture null is a probe without bootc_store. Every frontend's reader "
        "must give `expected`. See README.md, 'bootc storage of this computer'."),
        store_cases),
    os.path.join(HERE, "source-reuse-cases.json"): ((
        "Generated by generate-source-check-cases.py from bootc_shared.source_check. "
        "Each case: the plain probe is {protocol_version: 1, bootc_store: <fixtures/"
        "bootc-store/fixture>, live: {is_live: live}}; fixture null leaves bootc_store out, "
        "live null leaves live out, probe_failed means no result. `update_ref` is the "
        "recipe's targetImgref. `expected` is the item of this computer's bootc storage "
        "that the frontend offers as a second install source, or null. With an item, "
        "`recipe` is the recipe after the user picks it (from a base recipe that names "
        "update_ref as image and targetImgref), `fragment` what `validate --json "
        "--partial` gets, and `request`/`probe_args` the source check of that recipe. "
        "See README.md, 'Install from the bootc storage of this computer'."), reuse_cases),
    os.path.join(SHARED, "completion", "verification-cases.json"): ((
        "Generated by ../probe/generate-source-check-cases.py from bootc_shared.completion. "
        "Each case: the text of fixtures/<fixture> and the install id the reader expects "
        "(\"\" for none). Every frontend's reader must give `expected`. See README.md."),
        verify_cases),
}


def render():
    return {path: document(comment, build()) for path, (comment, build) in FILES.items()}


def main():
    for path, text in render().items():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(path)


if __name__ == "__main__":
    main()
