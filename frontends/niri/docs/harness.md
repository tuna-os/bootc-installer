# Niri installer test contract

The shared contract lives in `shared/flow/README.md` ("Test contract").
The harness dumps the AT-SPI tree in the guest and clicks from the host
with QMP `input-send-event`. This page says what that means for this
frontend. Its toolkit is Quickshell on Qt Quick.

## What the harness asserts today

Each interactive element carries an `objectName`. The list includes
tryButton, installNowButton, rstContinueButton, wipeFreeRow, wipeEraseRow,
wipeContinueButton, prereleaseContinueButton, eulaAckButton,
eulaContinueButton, recoveryKeyLabel, recoveryQrButton, recoveryQrOverlay,
recoveryQrDoneButton, recoveryContinueButton, handoffContinueButton,
handoffNotNowButton, handoffRebootButton, handoffRetryButton,
privacyLocationRow, sessionNextButton and accountNextButton.

The harness reads each screen from its text. Each page has its own title.
The recovery key matches the shape
`^[a-z]{6,10}(-[a-z]{6,10}){7}$`. Buttons match by label.

`tests/gui/capture-screens.py` drives the real `ui/installer.qml`
offscreen under PyQt6. Backend answers come from stubs. The script asserts
per frame: the button that leaves each step is visible and on screen, the
key is in the rendered text, Continue stays held until acknowledgement,
the QR dialog opens, and the stubbed handoff answers through the entry
call. Run it with `python3 tests/gui/capture-screens.py /tmp/shots`.

## AT-SPI status: unchecked

DankButton, DankCard and DankListItem set `Accessible.role` and
`Accessible.name` from their text. The tree should read cleanly. But no
one has checked whether Quickshell exposes Qt Quick accessibility over
AT-SPI. That check needs a live Niri session, and CI has no compositor.
The first run of Utah's `raw_e2e.py` against this frontend decides it.

## Fallback if AT-SPI is absent

`scripts/installer-walkthrough.py` already drives installs with QEMU key
events and OCR. If the AT-SPI tree is empty, this frontend falls back to
that. Send keys from the host with QMP `input-send-event` on a USB tablet:
Wayland refuses input that a program inside the guest sends. Read the
screen from OCR of the header and the button labels. Match the recovery
key by shape, never by node name. The screenshots in `docs/screenshots/`
are the OCR reference set: one per screen, rendered from the same QML the
installer ships.
