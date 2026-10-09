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
sys.path.insert(0, str(HERE))
import progress_parser as pp  # noqa: E402

OUT = HERE / "fraction-cases.json"
OVERALL_OUT = HERE / "overall-pct-cases.json"


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
