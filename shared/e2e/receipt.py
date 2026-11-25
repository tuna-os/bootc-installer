#!/usr/bin/env python3
"""Evidence receipts for the installer walkthrough and E2E outputs (#270).

A receipt says what one run observed and how much that proves. It is a
small adapter over the outputs that already exist (the walkthrough report
of shared/walkthrough/parity_report.py, the VM canary of vm-install.sh).
It is not a runner. Capture and state assertions stay in each frontend's
own harness. The shape follows the shared visual-validation contract of
tunaOS#3475 (version 1). That contract is not final, so `version` is
checked and an unknown version is rejected.

A receipt binds:

  * target: frontend and capability;
  * identity: source and harness revision, image (and ISO only when the
    claim is about an ISO), run, attempt and session;
  * evidence_class: how the evidence was made (CLASSES);
  * modifications: the structured list of what a canary changed;
  * observation: what kind of measurement it was (semantic, OCR, pixels,
    input, backend). A measurement that was not made is null, never false
    or true by default;
  * assertions: each with an outcome (OUTCOMES) and, for `unsupported` and
    `inapplicable`, a reason;
  * artifacts: name and sha256, each mandatory or not;
  * attempts: the first failure and every retry stay in the list;
  * cleanup: written after teardown.

    receipt.py validate RECEIPT.json [--claim CLASS] [--dir ARTIFACT_DIR]
    receipt.py walkthrough REPORT.json --out FILE --run-id ID ...
    receipt.py canary --frontend NAME --out FILE --run-id ID ...

`validate` returns a list of reasons. The receipt validates for its claim
only when the list is empty. A required assertion that is failed, blocked,
not-run, flaky or unknown cannot make a capability `passed`. The check is
per capability: a receipt for the frontend walkthrough does not depend on
the VM canary receipt.
"""
import argparse
import hashlib
import json
import os
import sys

VERSION = 1
KIND = "installer-evidence-receipt"
CLASSES = ("fixture", "programmatic-capture", "modified-canary",
           "published-image", "installed-media")
OUTCOMES = ("passed", "failed", "blocked", "not-run", "unsupported", "flaky")
REASON_REQUIRED = ("unsupported", "inapplicable")
# What vm-install.sh does to the recipe and the guest. It is metadata of
# the run, so nobody reads a canary as proof about unchanged shipped media.
CANARY_MODIFICATIONS = (
    {"kind": "recipe-rewrite", "detail": "disk is replaced when the recipe's loop device is taken"},
    {"kind": "image", "detail": "the SSH-enabled canary image from the E2E catalog, not shipped media"},
    {"kind": "ssh-enabled", "detail": "fisherman scripts/enable-ssh-installed.sh adds root authorized_keys and an sshd drop-in"},
    {"kind": "kernel-arguments", "detail": "console=ttyS0,115200 console=tty0 enforcing=0 (permissive SELinux) added to BLS entries"},
)
# A claim that needs more than the class: these classes never prove it.
CLAIMS = {"installed-media": ("installed-media",)}
# An action that is not retried: the attempt list must hold one entry.
NO_RETRY = ("destructive", "secret")


def sha256_file(path):
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def artifact(path, mandatory=True, name=None):
    """An artifact entry. A missing file is recorded with sha256 null."""
    return {"name": name or os.path.basename(path), "mandatory": mandatory,
            "sha256": sha256_file(path) if os.path.isfile(path) else None}


def outcome_of(assertions, cleanup):
    """The outcome of the capability. A required assertion decides; unknown
    is not passed; a failed cleanup is never hidden by a pass."""
    worst = "passed"
    order = ("failed", "blocked", "not-run", "flaky")
    required = [a for a in assertions if a.get("required", True)]
    if not required:
        return "not-run"
    for name in order:
        if any(a.get("outcome") == name for a in required):
            worst = name
            break
    else:
        if any(a.get("outcome") not in ("passed", "unsupported", "inapplicable")
               for a in required):
            worst = "not-run"
        elif all(a.get("outcome") in ("unsupported", "inapplicable") for a in required):
            worst = "unsupported"
    if worst == "passed" and (cleanup or {}).get("outcome") not in ("ok", "not-needed"):
        worst = "failed"
    return worst


def validate(receipt, claim=None, artifact_dir=None, secrets=()):
    """Reasons that this receipt cannot stand for its capability (or for
    `claim`). An empty list is a valid receipt."""
    bad = []
    if not isinstance(receipt, dict):
        return ["receipt is not an object"]
    if receipt.get("kind") != KIND or receipt.get("version") != VERSION:
        return [f"not a {KIND} of version {VERSION}"]
    target = receipt.get("target") or {}
    for key in ("frontend", "capability"):
        if not target.get(key):
            bad.append(f"target.{key} is missing")
    ident = receipt.get("identity") or {}
    for key in ("run_id", "attempt", "session"):
        if ident.get(key) in (None, ""):
            bad.append(f"identity.{key} is missing")
    cls = receipt.get("evidence_class")
    if cls not in CLASSES:
        bad.append(f"evidence_class {cls!r} is not one of {', '.join(CLASSES)}")
    mods = receipt.get("modifications")
    if not isinstance(mods, list):
        bad.append("modifications must be a list (empty for none)")
        mods = []
    if cls == "modified-canary" and not mods:
        bad.append("a modified canary must list its modifications")
    if cls in ("installed-media", "published-image") and mods:
        bad.append(f"{cls} evidence cannot carry modifications")

    assertions = receipt.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        bad.append("assertions are missing")
        assertions = []
    for a in assertions:
        who = a.get("id", "?")
        out = a.get("outcome")
        if out not in OUTCOMES and out != "inapplicable":
            bad.append(f"assertion {who}: outcome {out!r} is unknown")
        if out in REASON_REQUIRED and not str(a.get("reason") or "").strip():
            bad.append(f"assertion {who}: {out} needs a reason")
        if out == "passed" and a.get("inputs") is None:
            bad.append(f"assertion {who}: passed without its inputs")
    required_bad = [a.get("id", "?") for a in assertions
                    if a.get("required", True)
                    and a.get("outcome") not in ("passed", "inapplicable", "unsupported")]
    cleanup = receipt.get("cleanup")
    if not isinstance(cleanup, dict) or cleanup.get("outcome") not in ("ok", "failed", "not-needed"):
        bad.append("cleanup is not recorded (a receipt is final only after teardown)")
        cleanup = {}
    if receipt.get("outcome") == "passed":
        if required_bad:
            bad.append("outcome is passed but required assertions are not: " + ", ".join(required_bad))
        if cleanup.get("outcome") == "failed":
            bad.append("outcome is passed although cleanup failed")
    elif receipt.get("outcome") not in OUTCOMES:
        bad.append(f"outcome {receipt.get('outcome')!r} is unknown")

    for item in receipt.get("artifacts") or []:
        if item.get("mandatory", True) and not item.get("sha256"):
            bad.append(f"mandatory artifact {item.get('name')} is missing")
        elif artifact_dir and item.get("sha256"):
            path = os.path.join(artifact_dir, os.path.basename(item["name"]))
            if not os.path.isfile(path) or sha256_file(path) != item["sha256"]:
                bad.append(f"artifact {item['name']} does not match its hash")

    attempts = receipt.get("attempts") or []
    for a in attempts:
        if a.get("kind") in NO_RETRY and sum(
                1 for b in attempts if b.get("action") == a.get("action")) > 1:
            bad.append(f"{a.get('kind')} action {a.get('action')} was retried")
    if receipt.get("outcome") == "passed" and attempts \
            and any(a.get("outcome") == "failed" for a in attempts):
        # A later pass keeps the earlier failure; it is a flaky run.
        bad.append("outcome is passed but an earlier attempt failed: record it as flaky")

    if claim:
        if claim not in CLASSES:
            bad.append(f"claim {claim!r} is unknown")
        elif cls != claim:
            bad.append(f"evidence_class {cls!r} cannot stand for {claim}")
        if claim in ("installed-media", "published-image"):
            image = ident.get("image") or {}
            if not image.get("digest"):
                bad.append(f"{claim} needs the image digest")
            if not ident.get("source_revision"):
                bad.append(f"{claim} needs the source revision")
        if claim == "installed-media" and target.get("subject") == "iso" \
                and not (ident.get("iso") or {}).get("sha256"):
            bad.append("a claim about an ISO needs the ISO identity")
    text = json.dumps(receipt)
    for value in secrets:
        if value and value in text:
            bad.append("a secret value is in the receipt")
    return bad


def base(frontend, capability, evidence_class, run_id, attempt=1, session=None,
         source_revision=None, harness_revision=None, image=None):
    return {
        "kind": KIND, "version": VERSION,
        "target": {"frontend": frontend, "capability": capability},
        "evidence_class": evidence_class,
        "modifications": [],
        "identity": {"run_id": run_id, "attempt": attempt,
                     "session": session or run_id,
                     "source_revision": source_revision,
                     "harness_revision": harness_revision,
                     "image": image or {}},
        "observation": {}, "assertions": [], "artifacts": [], "attempts": [],
        "cleanup": None, "outcome": None,
    }


def from_walkthrough(report, png_dir=None, **identity):
    """The receipt of a `walkthrough-<flavor>.json`. Its own labels stay:
    programmatic navigation, widget-tree text, no OCR, no activation key."""
    flavor = report.get("flavor", "unknown")
    receipt = base(flavor, "walkthrough-screens", "programmatic-capture", **identity)
    receipt["observation"] = {
        "semantic": report.get("text_source"),           # "widget-tree"
        "ocr": report.get("ocr"),                        # False: not measured by OCR
        "pixels": "pixel-audit" if report.get("pages") else None,
        "input_delivery": "programmatic",
        "activation_key": report.get("activation_key"),  # null stays unknown
        "backend_outcome": None,                         # a capture installs nothing
    }
    outcomes = report.get("screen_outcomes") or {}
    for sid, value in sorted(outcomes.items()):
        state = value.get("outcome") if isinstance(value, dict) else value
        mapped = {"passed": "passed", "failed": "failed", "exempt": "unsupported",
                  "optional-missing": "not-run", "not-measured": "not-run"}.get(state, "not-run")
        entry = {"id": f"screen:{sid}", "required": state != "optional-missing",
                 "outcome": mapped, "inputs": {"contract_digest": report.get("contract_digest")}}
        if mapped == "unsupported":
            entry["reason"] = (value.get("reason") if isinstance(value, dict) else None) \
                or "declared exemption in the frontend's feature manifest"
        receipt["assertions"].append(entry)
    if report.get("strict") and report.get("failures"):
        receipt["assertions"].append({"id": "strict", "required": True, "outcome": "failed",
                                      "reason": "; ".join(report.get("failure_reasons") or [])[:500],
                                      "inputs": None})
    for page in report.get("pages") or []:
        name = os.path.basename(page.get("png") or page.get("name") or "")
        receipt["artifacts"].append({"name": name, "mandatory": True,
                                     "sha256": page.get("sha256")})
    receipt["cleanup"] = {"outcome": "not-needed"}
    receipt["outcome"] = outcome_of(receipt["assertions"], receipt["cleanup"])
    return receipt


def from_canary(frontend, install_ok, boot_ok, cleanup, staged=(), **identity):
    """The receipt of vm-install.sh. The class is `modified-canary`: the
    image, kernel arguments and SSH are the run's own changes."""
    receipt = base(frontend, "vm-install-and-boot", "modified-canary", **identity)
    receipt["modifications"] = [dict(m) for m in CANARY_MODIFICATIONS]
    receipt["observation"] = {"semantic": None, "ocr": None, "pixels": None,
                              "input_delivery": None,
                              "backend_outcome": "bootc status answered over SSH" if boot_ok else None}
    receipt["assertions"] = [
        {"id": "install", "required": True, "outcome": "passed" if install_ok else "failed",
         "inputs": {"log": "install.log"}},
        {"id": "boot", "required": True,
         "outcome": "passed" if boot_ok else ("failed" if install_ok else "not-run"),
         "inputs": {"log": "boot.log"}},
    ]
    receipt["artifacts"] = list(staged)
    receipt["cleanup"] = cleanup
    receipt["outcome"] = outcome_of(receipt["assertions"], cleanup)
    return receipt


def _identity(args):
    return dict(run_id=args.run_id, attempt=args.attempt, session=args.session,
                source_revision=args.source_revision, harness_revision=args.harness_revision)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("receipt")
    p.add_argument("--claim")
    p.add_argument("--dir")
    for name in ("walkthrough", "canary"):
        p = sub.add_parser(name)
        if name == "walkthrough":
            p.add_argument("report")
        else:
            p.add_argument("--frontend", required=True)
            p.add_argument("--install-ok", action="store_true")
            p.add_argument("--boot-ok", action="store_true")
            p.add_argument("--cleanup", choices=("ok", "failed"), required=True)
            p.add_argument("--cleanup-detail", default="")
            p.add_argument("--stage-dir")
        p.add_argument("--out", required=True)
        p.add_argument("--run-id", required=True)
        p.add_argument("--attempt", type=int, default=1)
        p.add_argument("--session")
        p.add_argument("--source-revision")
        p.add_argument("--harness-revision")
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        with open(args.receipt, encoding="utf-8") as stream:
            problems = validate(json.load(stream), args.claim, args.dir)
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1 if problems else 0
    if args.cmd == "walkthrough":
        with open(args.report, encoding="utf-8") as stream:
            receipt = from_walkthrough(json.load(stream), **_identity(args))
    else:
        staged = []
        if args.stage_dir and os.path.isdir(args.stage_dir):
            staged = [artifact(os.path.join(args.stage_dir, n), mandatory=n in ("install.log", "boot.log"))
                      for n in sorted(os.listdir(args.stage_dir)) if not n.startswith("receipt-")]
        cleanup = {"outcome": args.cleanup}
        if args.cleanup_detail:
            cleanup["detail"] = args.cleanup_detail
        receipt = from_canary(args.frontend, args.install_ok, args.boot_ok, cleanup,
                              staged, **_identity(args))
    with open(args.out, "w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
