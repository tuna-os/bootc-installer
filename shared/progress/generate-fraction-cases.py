#!/usr/bin/env python3
"""Write fraction-cases.json: the bar position after each event, per the
canonical parser.

Every frontend parses fisherman's progress protocol on its own: Python for
GNOME and XFCE, Rust for COSMIC, C++ for KDE, JavaScript in QML for Niri.
The README describes the semantics; this file pins the numbers, so a change
to the bar in one parser cannot leave the other four behind. That happened:
#115's deploy-phase weighting was written in Python only.

Each frontend's tests feed `events` through its own parser and require the
bar to read `bar` after every event (to 1e-6). Regenerate after changing
progress_parser.py:

    python3 shared/progress/generate-fraction-cases.py

It also writes overall-pct-cases.json: event streams that carry fisherman's
own `overall_pct`, which a frontend must show as it stands, and streams
without it, which must fall back to the derivation above. That file is kept
apart because fisherman's own tests replay fraction-cases.json through its
Tracker, which computes overall_pct rather than reading it.
"""

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python"))
from bootc_shared import progress as pp  # noqa: E402

OUT = HERE / "fraction-cases.json"
OVERALL_OUT = HERE / "overall-pct-cases.json"
ERROR_OUT = HERE / "error-cases.json"
RECEIPT_OUT = HERE / "receipt-cases.json"
OUTCOME_OUT = HERE / "outcome-cases.json"
REUSE_OUT = HERE / "source-reuse-cases.json"


def step(n, total, name, cumulative, weight):
    return {"type": "step", "step": n, "total_steps": total, "step_name": name,
            "cumulative_pct": cumulative, "weight_pct": weight}


def sub(message):
    return {"type": "substep", "message": message}


def at(event, overall_pct, step_id=None):
    """`event` as a current fisherman emits it: with overall_pct, and with
    step_id on a step event."""
    out = dict(event)
    if step_id:
        out["step_id"] = step_id
    out["overall_pct"] = overall_pct
    return out


CASES = {
    "cold_install_pulls_then_deploys": [
        step(4, 8, "Mounting filesystem", 1, 0),
        step(5, 8, "Installing OS", 1, 87),
        sub("Pulling container image"),
        sub("Pulling image: layer 1/4"),
        sub("Pulling image: layer 2/4"),
        sub("Pulling image: layer 4/4"),
        sub("Exporting image to OCI layout for composefs install"),
        sub("OCI export complete"),
        sub("Using overlay storage driver with OCI layout"),
        sub("Deploying image"),
        sub("OS deployed, installing bootloader"),
        sub("Configuring EFI boot entry"),
        sub("bootc installation complete"),
        step(6, 8, "Copying system Flatpaks", 88, 10),
        {"type": "complete", "message": "done"},
    ],
    # #115: nothing is pulled, so before the fix the bar sat at the step's
    # start for the whole export and deploy.
    "offline_install_moves_through_silent_phases": [
        step(5, 8, "Installing OS", 1, 68),
        sub("Exporting image to OCI layout for composefs install"),
        sub("OCI export complete"),
        sub("Deploying image"),
        sub("OS deployed, installing bootloader"),
        sub("bootc installation complete"),
    ],
    "a_retried_pull_never_moves_the_bar_back": [
        step(5, 8, "Installing OS", 1, 87),
        sub("Pulling image: layer 3/4"),
        sub("Pulling image: layer 1/4"),
        sub("Pulling image: layer 2/4"),
        sub("Pulling image: layer 4/4"),
    ],
    "unknown_messages_and_zero_weight_steps_hold_the_bar": [
        step(2, 8, "Partitioning disk", 0, 0),
        sub("Pulling image: layer 2/4"),
        sub("Deploying image"),
        step(5, 8, "Installing OS", 1, 87),
        sub("Something fisherman says that is not a phase"),
        sub("Pulling image: layer 0/0"),
    ],
    "a_new_step_starts_from_its_own_cumulative": [
        step(5, 8, "Installing OS", 1, 87),
        sub("Pulling image: layer 4/4"),
        sub("Deploying image"),
        step(6, 8, "Copying system Flatpaks", 88, 10),
        sub("Deploying image"),
    ],
}


# Streams with overall_pct. The first is fisherman's own output for its
# Flatpak-copy case (fisherman internal/progress/testdata/
# fraction-cases-fisherman.json, overall_pct as its Tracker emits it). The
# derivation here holds the bar through the copy; overall_pct moves it, so a
# frontend that ignores the field fails this case.
OVERALL_CASES = {
    "overall_pct_drives_the_bar": [
        at(step(5, 8, "Installing OS", 1, 87), 1, "install_os"),
        at(sub("bootc installation complete"), 88),
        at(step(6, 8, "Copying system Flatpaks", 88, 11), 88, "flatpaks"),
        at(sub("Found 3/3 wanted apps in system install"), 88),
        at(sub("Copying 3 Flatpak apps (1.2 GB)"), 88),
        at(sub("Copying Flatpak data: 5%"), 88.55),
        at(sub("Copying Flatpak data: 50%"), 93.5),
        at(sub("Copying Flatpak data: 100%"), 99),
        at(sub("Copied 3 Flatpak apps"), 99),
        at(step(7, 8, "Configuring installed system", 99, 0), 99, "configure"),
        at(step(8, 8, "Finalizing installation", 99, 1), 99, "finalize"),
        {"type": "complete", "message": "done", "overall_pct": 100},
    ],
    # fisherman never sends a lower overall_pct, but a frontend must not
    # draw one if it did; nor draw a value off either end of the bar.
    "overall_pct_never_moves_the_bar_back": [
        at(step(5, 8, "Installing OS", 1, 87), 40, "install_os"),
        at(sub("Pulling image: layer 1/4"), 35),
        at(sub("Something fisherman says that is not a phase"), 120),
    ],
    # An older fisherman: no overall_pct anywhere, so the derivation in
    # fraction-cases.json is what moves the bar.
    "without_overall_pct_the_bar_is_derived": [
        step(5, 8, "Installing OS", 1, 87),
        sub("Pulling image: layer 2/4"),
        sub("Deploying image"),
        step(6, 8, "Copying system Flatpaks", 88, 10),
        {"type": "complete", "message": "done"},
    ],
}


def run(events):
    state = pp.new_progress_state()
    bar = 0.0
    out = []
    for event in events:
        update = pp.apply_progress_event(json.dumps(event), state)
        if update and update.get("fraction") is not None:
            bar = update["fraction"]
        out.append(round(bar, 6))
    return out


def err(message, code=None, field=None):
    out = {"type": "error", "message": message}
    if code is not None:
        out["code"] = code
    if field is not None:
        out["field"] = field
    return out


# The `error` event: fisherman's reason for a failure. A parser keeps the
# last one as {message, code, field}; a part that is missing or is not a
# string is "". The event does not move the bar.
ERROR_CASES = {
    "validate_refuses_the_recipe": [
        err("disk /dev/vda is too small", "disk_too_small", "disk"),
    ],
    "an_older_fisherman_sends_only_the_message": [
        step(1, 8, "Partitioning disk", 0, 1),
        err("fatal: bootc install failed"),
    ],
    "the_last_error_is_kept": [
        err("first", "first_code", "hostname"),
        err("second", "second_code", "user.username"),
    ],
    "a_part_that_is_not_a_string_is_empty": [
        err("bad types", 5, ["disk"]),
    ],
    "the_bar_stays_where_it_was": [
        step(4, 8, "Mounting filesystem", 1, 0),
        step(5, 8, "Installing OS", 1, 87),
        sub("Pulling image: layer 2/4"),
        err("pull failed", "pull_failed", ""),
    ],
    "no_error": [
        step(1, 8, "Partitioning disk", 0, 1),
        {"type": "complete", "message": "Installation complete!"},
    ],
}


def run_errors(events):
    """(bar after each event, the last error or None) per the canonical parser."""
    state = pp.new_progress_state()
    bar, bars = 0.0, []
    for event in events:
        update = pp.apply_progress_event(json.dumps(event), state)
        if update and update.get("fraction") is not None:
            bar = update["fraction"]
        bars.append(round(bar, 6))
    return bars, state["error"]


def build_errors():
    cases = []
    for name, events in ERROR_CASES.items():
        bars, error = run_errors(events)
        cases.append({"name": name, "events": events, "bar": bars, "error": error})
    return {
        "_comment": (
            "Generated by generate-fraction-cases.py from progress_parser.py. "
            "Do not edit by hand. `error` is what the parser keeps after the "
            "events: the last `error` event as {message, code, field}, a "
            "missing or non-string part as \"\", or null with no error event. "
            "`bar` is the fraction after each event: an error does not move "
            "it. Every frontend's parser must reproduce both."
        ),
        "cases": cases,
    }


def rcpt(**fields):
    """A `receipt` event as fisherman writes it (tuna-os/fisherman#441)."""
    out = {"type": "receipt", "version": 1}
    out.update(fields)
    out.setdefault("timestamp", "1970-01-01T00:00:00Z")
    out.setdefault("elapsed_ms", 512000)
    return out


INSTALL_ID = "0123456789abcdef0123456789abcdef"
RECEIPT_PATH = "/var/lib/fisherman/install-receipt.json"

# The `receipt` event: what the install did with the installation receipt.
# The first six are fisherman's own lines, one per row of RECEIPT.md
# (fisherman/internal/progress/testdata/receipt-events.ndjson); the rest
# are what a frontend must not trust. The event moves no bar.
RECEIPT_CASES = {
    "written_and_check_set_up": [
        rcpt(written=True, install_id=INSTALL_ID, path=RECEIPT_PATH, first_boot_check=True),
    ],
    "written_transient_etc": [
        rcpt(written=True, install_id=INSTALL_ID, path=RECEIPT_PATH,
             first_boot_check=False, reason="transient_etc"),
    ],
    "written_collector_failed": [
        rcpt(written=True, install_id=INSTALL_ID, path=RECEIPT_PATH,
             first_boot_check=False, reason="collector_failed"),
    ],
    "not_written_resolve_failed": [
        rcpt(written=False, first_boot_check=False, reason="resolve_failed"),
    ],
    "not_written_build_failed": [
        rcpt(written=False, first_boot_check=False, reason="build_failed"),
    ],
    "not_written_write_failed": [
        rcpt(written=False, first_boot_check=False, reason="write_failed"),
    ],
    "a_new_reason_code_falls_back": [
        rcpt(written=False, first_boot_check=False, reason="disk_gone_away"),
    ],
    "a_reason_that_is_not_a_code_is_dropped": [
        rcpt(written=False, first_boot_check=False, reason="Write failed: EIO"),
    ],
    "written_without_a_reason_or_check": [
        rcpt(written=True, install_id=INSTALL_ID, path=RECEIPT_PATH),
    ],
    "version_2_is_unreadable": [
        rcpt(version=2, written=True, install_id=INSTALL_ID, first_boot_check=True),
    ],
    "a_version_that_is_not_a_number_is_unreadable": [
        rcpt(version="1", written=True, install_id=INSTALL_ID, first_boot_check=True),
    ],
    "written_that_is_not_a_boolean_is_unreadable": [
        rcpt(written="true", install_id=INSTALL_ID, first_boot_check=True),
    ],
    "a_written_receipt_without_an_install_id_is_unreadable": [
        rcpt(written=True, path=RECEIPT_PATH, first_boot_check=True),
    ],
    "an_install_id_that_is_not_32_hex_is_unreadable": [
        rcpt(written=True, install_id="0123456789ABCDEF0123456789ABCDEF",
             first_boot_check=True),
    ],
    "no_receipt_event": [
        step(7, 8, "Configuring installed system", 98, 1),
        {"type": "complete", "message": "Installation complete!"},
    ],
    "the_last_receipt_is_kept_and_the_bar_does_not_move": [
        step(7, 8, "Configuring installed system", 98, 1),
        rcpt(written=False, first_boot_check=False, reason="write_failed"),
        rcpt(written=True, install_id=INSTALL_ID, path=RECEIPT_PATH, first_boot_check=True),
        step(8, 8, "Finalizing installation", 99, 1),
        {"type": "complete", "message": "Installation complete!"},
    ],
    # The receipt says nothing about the outcome: a later error, or a
    # non-zero exit, is still a failed install, and the done page of a
    # failed install shows no receipt line.
    "a_receipt_then_an_error": [
        rcpt(written=True, install_id=INSTALL_ID, path=RECEIPT_PATH, first_boot_check=True),
        err("finalize failed", "", ""),
    ],
}


def run_receipt(events):
    """(bar after each event, the receipt view, the done page's lines)."""
    from bootc_shared import completion
    state = pp.new_progress_state()
    bar, bars = 0.0, []
    for event in events:
        update = pp.apply_progress_event(json.dumps(event), state)
        if update and update.get("fraction") is not None:
            bar = update["fraction"]
        bars.append(round(bar, 6))
    lines = [{"key": k, "value": v} for k, v in completion.receipt_lines(state["receipt"])]
    return bars, state["receipt"], lines


def build_receipts():
    cases = []
    for name, events in RECEIPT_CASES.items():
        bars, receipt, lines = run_receipt(events)
        cases.append({"name": name, "events": events, "bar": bars,
                      "receipt": receipt, "done_lines": lines})
    return {
        "_comment": (
            "Generated by generate-fraction-cases.py from bootc_shared.progress "
            "and bootc_shared.completion. Do not edit by hand. `receipt` is "
            "what the parser keeps after the events: the last `receipt` event "
            "as {state, install_id, reason}, or null with no receipt event. "
            "`done_lines` are the copy keys that the done page of an install "
            "that exited 0 shows, in order, with the value of {value}. `bar` "
            "is the fraction after each event: a receipt does not move it. "
            "Every frontend's parser must reproduce all three."
        ),
        "cases": cases,
    }


# The example line of fisherman docs/JSON-PROGRESS-FORMAT.md (`source_reuse`),
# verbatim. tests/unit/test_shared_progress.py holds it to the pinned doc.
REUSE_DOC_EXAMPLE = (
    '{"destination":"containers-storage:localhost/fisherman-reuse:111111111111-01'
    '23456789abcdef","digest":"sha256:1111111111111111111111111111111111111111111'
    '111111111111111111111","elapsed_ms":61210,"estimate":{"estimate_ms":4210,"fi'
    'les":51234,"required_bytes":8053063680,"same_filesystem":true,"scratch_bytes'
    '":3221225472,"scratch_free_bytes":60129542144,"store_bytes":3758096384,"stor'
    'e_free_bytes":60129542144},"phase":"planned","platform":"x86_64","source":"d'
    'ocker://ghcr.io/example/os:stable","timestamp":"2026-11-11T10:05:30.123456Z"'
    ',"type":"source_reuse","version":1}'
)

# fisherman's own lines: internal/reuse's fake host (reuse_test.go) driven
# through each path and written as progress.write writes them, with
# timestamp, elapsed_ms, estimate_ms, copy_ms and verify_ms frozen.
# `cancelled` is TestAcquire_Cancelled: the teardown releases the copy
# while bootc runs, then the killed copy fails.
REUSE_LINES = {
    "copied_and_verified": [
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":60000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"planned","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":61000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"copying","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","destination_digest":"sha256:ccccccccccccccccccccccc'
            'ccccccccccccccccccccccccccccccccccccccccc","digest":"sha256:111111111111'
            '1111111111111111111111111111111111111111111111111111","elapsed_ms":62000'
            ',"estimate":{"estimate_ms":4210,"files":3,"required_bytes":1073811456,"s'
            'ame_filesystem":true,"scratch_bytes":16384,"scratch_free_bytes":10737418'
            '2400,"store_bytes":53248,"store_free_bytes":107374182400},"measured":{"c'
            'opy_ms":61210,"scratch_peak_bytes":3221225472,"store_bytes":1073741824,"'
            'store_peak_bytes":3221225472,"verify_ms":830},"phase":"verified","platfo'
            'rm":"x86_64","source":"docker://ghcr.io/example/os:stable","timestamp":"'
            '1970-01-01T00:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":63000,"phase":"released","pl'
            'atform":"x86_64","reason":"removed","timestamp":"1970-01-01T00:00:00Z","'
            'type":"source_reuse","version":1}'
        ),
    ],
    "insufficient_space": [
        (
            '{"code":"source_reuse_insufficient_space","digest":"sha256:1111111111111'
            '111111111111111111111111111111111111111111111111111","elapsed_ms":60000,'
            '"estimate":{"estimate_ms":4210,"files":3,"required_bytes":1073811456,"sa'
            'me_filesystem":true,"scratch_bytes":16384,"scratch_free_bytes":536870912'
            ',"store_bytes":53248,"store_free_bytes":536870912},"phase":"failed","pla'
            'tform":"x86_64","reason":"insufficient_space","source":"docker://ghcr.io'
            '/example/os:stable","timestamp":"1970-01-01T00:00:00Z","type":"source_re'
            'use","version":1}'
        ),
    ],
    "source_moved": [
        (
            '{"code":"source_reuse_source_moved","digest":"sha256:1111111111111111111'
            '111111111111111111111111111111111111111111111","elapsed_ms":60000,"phase'
            '":"failed","platform":"x86_64","reason":"ref_moved","timestamp":"1970-01'
            '-01T00:00:00Z","type":"source_reuse","version":1}'
        ),
    ],
    "transfer_failed": [
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":60000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"planned","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":61000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"copying","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"code":"source_reuse_transfer_failed","destination":"containers-storage'
            ':localhost/fisherman-reuse:111111111111-0123456789abcdef","digest":"sha2'
            '56:1111111111111111111111111111111111111111111111111111111111111111","el'
            'apsed_ms":62000,"estimate":{"estimate_ms":4210,"files":3,"required_bytes'
            '":1073811456,"same_filesystem":true,"scratch_bytes":16384,"scratch_free_'
            'bytes":107374182400,"store_bytes":53248,"store_free_bytes":107374182400}'
            ',"phase":"failed","platform":"x86_64","reason":"command_failed","source"'
            ':"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T00:00:00Z"'
            ',"type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":63000,"phase":"released","pl'
            'atform":"x86_64","reason":"removed","timestamp":"1970-01-01T00:00:00Z","'
            'type":"source_reuse","version":1}'
        ),
    ],
    "disk_exhausted": [
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":60000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"planned","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":61000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"copying","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"code":"source_reuse_disk_exhausted","destination":"containers-storage:'
            'localhost/fisherman-reuse:111111111111-0123456789abcdef","digest":"sha25'
            '6:1111111111111111111111111111111111111111111111111111111111111111","ela'
            'psed_ms":62000,"estimate":{"estimate_ms":4210,"files":3,"required_bytes"'
            ':1073811456,"same_filesystem":true,"scratch_bytes":16384,"scratch_free_b'
            'ytes":107374182400,"store_bytes":53248,"store_free_bytes":107374182400},'
            '"phase":"failed","platform":"x86_64","reason":"disk_exhausted","source":'
            '"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T00:00:00Z",'
            '"type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":63000,"phase":"released","pl'
            'atform":"x86_64","reason":"removed","timestamp":"1970-01-01T00:00:00Z","'
            'type":"source_reuse","version":1}'
        ),
    ],
    "remove_failed": [
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":60000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"planned","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":61000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"copying","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","destination_digest":"sha256:ccccccccccccccccccccccc'
            'ccccccccccccccccccccccccccccccccccccccccc","digest":"sha256:111111111111'
            '1111111111111111111111111111111111111111111111111111","elapsed_ms":62000'
            ',"estimate":{"estimate_ms":4210,"files":3,"required_bytes":1073811456,"s'
            'ame_filesystem":true,"scratch_bytes":16384,"scratch_free_bytes":10737418'
            '2400,"store_bytes":53248,"store_free_bytes":107374182400},"measured":{"c'
            'opy_ms":61210,"scratch_peak_bytes":3221225472,"store_bytes":1073741824,"'
            'store_peak_bytes":3221225472,"verify_ms":830},"phase":"verified","platfo'
            'rm":"x86_64","source":"docker://ghcr.io/example/os:stable","timestamp":"'
            '1970-01-01T00:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":63000,"phase":"released","pl'
            'atform":"x86_64","reason":"remove_failed","timestamp":"1970-01-01T00:00:'
            '00Z","type":"source_reuse","version":1}'
        ),
    ],
    "cancelled": [
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":60000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"planned","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":61000,"estimate":{"estimate_'
            'ms":4210,"files":3,"required_bytes":1073811456,"same_filesystem":true,"s'
            'cratch_bytes":16384,"scratch_free_bytes":107374182400,"store_bytes":5324'
            '8,"store_free_bytes":107374182400},"phase":"copying","platform":"x86_64"'
            ',"source":"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T0'
            '0:00:00Z","type":"source_reuse","version":1}'
        ),
        (
            '{"destination":"containers-storage:localhost/fisherman-reuse:11111111111'
            '1-0123456789abcdef","digest":"sha256:11111111111111111111111111111111111'
            '11111111111111111111111111111","elapsed_ms":62000,"phase":"released","pl'
            'atform":"x86_64","reason":"removed","timestamp":"1970-01-01T00:00:00Z","'
            'type":"source_reuse","version":1}'
        ),
        (
            '{"code":"source_reuse_transfer_failed","destination":"containers-storage'
            ':localhost/fisherman-reuse:111111111111-0123456789abcdef","digest":"sha2'
            '56:1111111111111111111111111111111111111111111111111111111111111111","el'
            'apsed_ms":63000,"estimate":{"estimate_ms":4210,"files":3,"required_bytes'
            '":1073811456,"same_filesystem":true,"scratch_bytes":16384,"scratch_free_'
            'bytes":107374182400,"store_bytes":53248,"store_free_bytes":107374182400}'
            ',"phase":"failed","platform":"x86_64","reason":"command_failed","source"'
            ':"docker://ghcr.io/example/os:stable","timestamp":"1970-01-01T00:00:00Z"'
            ',"type":"source_reuse","version":1}'
        ),
    ],
}


def reuse(line):
    return json.loads(line)


CANCELLED = err("installation cancelled (SIGTERM)")

# The copy of this computer's system before the first step (#267,
# fisherman docs/SOURCE-REUSE.md). Each case ends as fisherman ends it.
REUSE_CASES = {
    "the_documented_planned_event": [reuse(REUSE_DOC_EXAMPLE)],
    "copied_verified_then_installed": [
        *map(reuse, REUSE_LINES["copied_and_verified"][:3]),
        at(step(1, 8, "Preparing disk", 0, 0), 0, "prepare"),
        at(step(5, 8, "Installing OS", 1, 87), 1, "install_os"),
        at(sub("Pulling image: layer 2/4"), 50),
        reuse(REUSE_LINES["copied_and_verified"][3]),
        {"type": "complete", "message": "Installation complete!", "overall_pct": 100},
    ],
    "insufficient_space": [*map(reuse, REUSE_LINES["insufficient_space"]),
                           err("source reuse: not enough space", "source_reuse_insufficient_space",
                               "sourceReuse")],
    "source_moved": [*map(reuse, REUSE_LINES["source_moved"]),
                     err("source reuse: the ref moved", "source_reuse_source_moved", "sourceReuse")],
    "transfer_failed": [*map(reuse, REUSE_LINES["transfer_failed"]),
                        err("source reuse: copy failed", "source_reuse_transfer_failed", "sourceReuse")],
    "disk_exhausted": [*map(reuse, REUSE_LINES["disk_exhausted"]),
                       err("source reuse: disk full", "source_reuse_disk_exhausted", "sourceReuse")],
    "the_copy_could_not_be_removed": list(map(reuse, REUSE_LINES["remove_failed"])),
    "cancelled_copy": [*map(reuse, REUSE_LINES["cancelled"]), CANCELLED],
    # While the copy runs, the cancel question says the disk does not change.
    "the_cancel_question_during_the_copy": list(map(reuse, REUSE_LINES["cancelled"][:2])),
    "a_new_failure_code_falls_back": [
        {**reuse(REUSE_LINES["source_moved"][0]), "code": "source_reuse_new_code"},
    ],
    "a_failure_code_from_another_family_falls_back": [
        {**reuse(REUSE_LINES["source_moved"][0]), "code": "pull_failed"},
    ],
    "planned_without_an_estimate": [
        {k: v for k, v in reuse(REUSE_LINES["copied_and_verified"][0]).items() if k != "estimate"},
    ],
    "counts_that_are_not_whole_numbers_are_dropped": [
        {**reuse(REUSE_LINES["copied_and_verified"][2]),
         "measured": {"copy_ms": "61210", "scratch_peak_bytes": -1, "store_peak_bytes": 1}},
    ],
    "two_filesystems_add_their_peaks": [
        {**reuse(REUSE_LINES["copied_and_verified"][2]),
         "estimate": {**reuse(REUSE_LINES["copied_and_verified"][2])["estimate"], "same_filesystem": False}},
    ],
    "a_verified_copy_without_a_digest": [
        {k: v for k, v in reuse(REUSE_LINES["copied_and_verified"][2]).items()
         if k != "destination_digest"},
    ],
    "an_unknown_phase_is_ignored": [
        reuse(REUSE_LINES["copied_and_verified"][0]),
        {**reuse(REUSE_LINES["copied_and_verified"][1]), "phase": "paused"},
    ],
    "an_unknown_release_reason": [
        {**reuse(REUSE_LINES["transfer_failed"][3]), "reason": "kept"},
    ],
    "version_2_is_unreadable": [
        {**reuse(REUSE_LINES["copied_and_verified"][0]), "version": 2},
    ],
    "no_source_reuse_event": [
        at(step(1, 8, "Preparing disk", 0, 0), 0, "prepare"),
        {"type": "complete", "message": "Installation complete!", "overall_pct": 100},
    ],
}


def run_reuse(events):
    """(bar after each event, the view, the progress page's lines, whether
    the cancel question is the copy's) per the canonical parser."""
    state = pp.new_progress_state()
    bar, bars = 0.0, []
    for event in events:
        update = pp.apply_progress_event(json.dumps(event), state)
        if update and update.get("fraction") is not None:
            bar = update["fraction"]
        bars.append(round(bar, 6))
    lines = [{"key": k, "value": v} for k, v in pp.source_reuse_lines(state["source_reuse"])]
    return bars, state["source_reuse"], lines, pp.copy_cancel(state)


def build_reuse():
    cases = []
    for name, events in REUSE_CASES.items():
        bars, view, lines, cancel = run_reuse(events)
        cases.append({"name": name, "events": events, "bar": bars, "source_reuse": view,
                      "lines": lines, "copy_cancel": cancel})
    return {
        "_comment": (
            "Generated by generate-fraction-cases.py from bootc_shared.progress. "
            "Do not edit by hand. The copy of this computer's system before the "
            "first step (#267): fisherman's `source_reuse` events, most of them "
            "fisherman's own lines. `source_reuse` is what the parser keeps after "
            "the events, or null with no such event. `lines` are the progress "
            "page's copy keys, in order, with the value of {value}. `copy_cancel` "
            "says whether the cancel question is `progress_reuse_cancel` after "
            "the events. `bar` is the fraction after each event: a source_reuse "
            "event does not move it. Every frontend's parser must reproduce all four."
        ),
        "cases": cases,
    }


COMPLETE = {"type": "complete", "message": "Installation complete!"}

# How an install ended: the exit code decides, never the `complete` event.
# exit_code None is a wrapper that a signal ended. After a confirmed cancel,
# 130 or a signal is the cancel; another exit code is a failure.
OUTCOME_CASES = {
    "complete_then_exit_0": ([COMPLETE], 0, False),
    "complete_then_a_non_zero_exit": ([COMPLETE], 1, False),
    "complete_then_a_signal": ([COMPLETE], None, False),
    "exit_0_without_a_complete_event": ([step(1, 8, "Partitioning disk", 0, 1)], 0, False),
    "an_error_then_exit_1": ([err("pull failed", "pull_failed", "")], 1, False),
    "exit_130_without_a_request": ([], 130, False),
    "exit_130_after_a_request": ([], 130, True),
    "a_signal_after_a_confirmed_cancel": ([], None, True),
    "the_shell_reports_a_signal_after_a_cancel": ([], 143, True),
    "the_shell_reports_a_signal_without_a_cancel": ([], 143, False),
    "a_cancel_that_came_too_late": ([COMPLETE], 0, True),
    "a_receipt_then_a_non_zero_exit": (
        [rcpt(written=True, install_id=INSTALL_ID, path=RECEIPT_PATH, first_boot_check=True)],
        1, False),
    # fisherman failed before the cancel reached it: a failure, cancel or not.
    "exit_1_after_a_confirmed_cancel": ([err("pull failed", "pull_failed", "")], 1, True),
    # The cancel question during the copy of this computer's system (#267):
    # fisherman removes the copy, reports the killed copy and exits 130.
    "a_cancelled_copy": (None, 130, True),
    "a_failed_copy_after_a_confirmed_cancel": (None, 1, True),
}


def build_outcomes():
    cases = []
    for name, (events, code, cancel) in OUTCOME_CASES.items():
        if events is None:
            events = REUSE_CASES["cancelled_copy" if code == 130 else "transfer_failed"]
        cases.append({"name": name, "events": events, "exit_code": code,
                      "cancel_requested": cancel,
                      "outcome": pp.install_outcome(code, cancel)})
    return {
        "_comment": (
            "Generated by generate-fraction-cases.py from bootc_shared.progress. "
            "Do not edit by hand. How an install ended, from the wrapper's "
            "`exit_code` (null: a signal ended it) and whether the user "
            "confirmed a cancel: succeeded, cancelled or failed. `events` "
            "are what fisherman wrote before it exited; a `complete` event "
            "does not change the outcome. Every frontend's rule must give "
            "`outcome`, and only a succeeded install shows the receipt lines."
        ),
        "cases": cases,
    }


def build_overall():
    return {
        "_comment": (
            "Generated by generate-fraction-cases.py from progress_parser.py. "
            "Do not edit by hand. Events that carry fisherman's overall_pct "
            "(0-100), which is authoritative: the bar shows it, never moving "
            "back, clamped to 0-1. Events without it fall back to the "
            "derivation pinned by fraction-cases.json. `bar` is the fraction "
            "(0-1) after each event; every frontend's parser must reproduce it."
        ),
        "cases": [
            {"name": name, "events": events, "bar": run(events)}
            for name, events in OVERALL_CASES.items()
        ],
    }


def build():
    return {
        "_comment": (
            "Generated by generate-fraction-cases.py from progress_parser.py. "
            "Do not edit by hand. `bar` is the progress fraction (0-1) after "
            "each event in `events`; every frontend's parser must reproduce it."
        ),
        "cases": [
            {"name": name, "events": events, "bar": run(events)}
            for name, events in CASES.items()
        ],
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {len(CASES)} cases to {OUT.relative_to(HERE.parents[1])}")
    OVERALL_OUT.write_text(json.dumps(build_overall(), indent=2) + "\n")
    print(f"wrote {len(OVERALL_CASES)} cases to {OVERALL_OUT.relative_to(HERE.parents[1])}")
    ERROR_OUT.write_text(json.dumps(build_errors(), indent=2) + "\n")
    print(f"wrote {len(ERROR_CASES)} cases to {ERROR_OUT.relative_to(HERE.parents[1])}")
    RECEIPT_OUT.write_text(json.dumps(build_receipts(), indent=2) + "\n")
    OUTCOME_OUT.write_text(json.dumps(build_outcomes(), indent=2) + "\n")
    print(f"wrote {len(OUTCOME_CASES)} cases to {OUTCOME_OUT.relative_to(HERE.parents[1])}")
    print(f"wrote {len(RECEIPT_CASES)} cases to {RECEIPT_OUT.relative_to(HERE.parents[1])}")
    REUSE_OUT.write_text(json.dumps(build_reuse(), indent=2) + "\n")
    print(f"wrote {len(REUSE_CASES)} cases to {REUSE_OUT.relative_to(HERE.parents[1])}")
