## QR Phone Companion MVP — Approach

Refs: #40|Draft

### Goal
Local HTTPS server + preferences page accessible from phone during install for account setup and personalization.

### Proposed approach
1. Start a local HTTPS server (self-signed cert) on the live ISO
2. Serve a captive-portal-like page with:
   - Account creation / sign-in (optional)
   - Preferences: hostname, user account, SSH keys, wallpaper
3. Display a QR code on the installer screen with a link to the local server
4. Accept completed preferences as JSON, feed into recipe/finals

### Files to touch
- `bootc_installer/utils/phone_companion.py` (new — HTTPS server)
- `bootc_installer/views/qr_companion.py` (new — QR display + status)
- `bootc_installer/windows/main_window.py` (wire companion step)
- `org.bootcinstaller.Installer.json` (stdlib-only, no extra deps)

### Open questions
- Self-signed cert generation — openssl on live ISO or `cryptography` module?
- mDNS for .local discovery?
- Must the phone be on the same network, or can it use a hotspot?
