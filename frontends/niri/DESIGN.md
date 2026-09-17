# tuna-installer-niri — Design

Quickshell QML frontend running fullscreen on the Niri scrollable-tiling
Wayland compositor. The shared flow and contract are defined in the
[installer frontend specification](https://github.com/tuna-os/tunaOS/blob/main/docs/INSTALLER-FRONTENDS.md).

## Direction

Niri's audience is keyboard-driven minimalists; the installer *is* the session
(kiosk). So this frontend gets the boldest treatment of the four: a dark,
instrument-panel aesthetic — closer to a ship's bridge console than a desktop
dialog — and navigation that mimics Niri itself.

## Signature element: the scrolling column strip

Wizard steps are **columns on an infinite horizontal strip**, exactly like
Niri's scrollable tiling. The current step is centered at ~720 px wide;
the previous and next steps peek in from the edges at 40 % opacity and 0.92
scale. Advancing scrolls the strip left (280 ms, cubic ease; reduced-motion:
instant). Users who know Niri feel at home in the first second — the
installer speaks the compositor's native gesture.

Keyboard is primary: `Tab`/arrows within a column, `Enter` advances,
`Shift+Enter` goes back. A persistent hint bar at the bottom shows live
keybindings (Niri users expect this from their bars).

## Tokens

| Token | Hex | Use |
|---|---|---|
| `--void` | `#0A0E12` | Backdrop (whole screen) |
| `--panel` | `#131A21` | Column card background |
| `--line` | `#22303C` | Hairline borders, dividers |
| `--fog` | `#8FA3B0` | Secondary text |
| `--sonar` | `#2EC4B6` | Focus ring, active elements, progress |
| `--catch` | `#F4A259` | Destructive accent (Install, wipe warnings) |

Dark only. This is a live-session kiosk, not a desktop app; committing to one
look is correct here.

## Type

- Body/UI: **Inter** (bundle in Flatpak), 15 px base.
- Data (device names, sizes, image refs, log output): **JetBrains Mono**
  13.5 px — data is the protagonist in an installer; setting it in mono makes
  every value scannable and copy-exact.
- Column titles: Inter, 28 px, weight 250 (light), tracking +0.02em — the one
  typographic flourish.

## Layout

```
        ┌─────────┐ ┌──────────────────────────────┐ ┌─────────┐
        │ (source │ │  DESTINATION                 │ │ (setup  │
        │  peeks) │ │                              │ │  peeks) │
        │         │ │  nvme0n1  Samsung 990 PRO    │ │         │
        │         │ │           1.0 TB    ● focus  │ │         │
        │         │ │  sda      WD Blue    2.0 TB  │ │         │
        │         │ │                              │ │         │
        │         │ │  ⚠ erases everything on the  │ │         │
        │         │ │    selected disk             │ │         │
        └─────────┘ └──────────────────────────────┘ └─────────┘
  ────────────────────────────────────────────────────────────────
   ⏎ continue   ⇧⏎ back   ↑↓ select   /  search        3 / 8 steps
```

- Progress page: the 9 fisherman steps render as a vertical rail of mono
  labels; the active one pulses `--sonar`; raw log scrolls in a collapsed
  drawer (`l` toggles).
- Focus ring: 2 px `--sonar` outer glow — the *only* glow in the app.

## Copy

Terse, lowercase-tolerant, but complete sentences for anything consequential.
Warnings always spell out the device: "erases everything on nvme0n1
(Samsung 990 PRO)".

## Quality floor

Every interactive element reachable and operable by keyboard alone (mouse is
optional hardware here). Hint bar always reflects the actual bindings of the
focused context. Passphrase entry: mono bullets, reveal on `Ctrl+R`, caps-lock
indicator in the hint bar. All animation gated on a reduced-motion setting
(env `TUNA_REDUCED_MOTION=1`).
