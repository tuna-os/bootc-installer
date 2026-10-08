# Failure Path Testing

Make sure that the installer handles errors well: no stale state, clear error messages, and a retry/cancel that works.

Refs: #44|Closes

## Failure Scenarios

### 1. Network failure during image pull
- **Trigger:** Disconnect network after mount but before bootc install
- **Expected:** fisherman sends a fatal error with the "network" category
- **Verify:** Done screen shows network error hint, retry button works

### 2. Invalid/unreachable image reference
- **Trigger:** Set image to `ghcr.io/nonexistent/repo:tag`
- **Expected:** Podman/bootc fails to pull, fisherman exits non-zero
- **Verify:** The error hint names the image or registry, and the log shows the podman error

### 3. Disk too small
- **Trigger:** Target a 2GB USB stick
- **Expected:** The partition step fails (not enough space)
- **Verify:** Error shown before any destructive writes if possible

### 4. Disk busy/mounted
- **Trigger:** Mount a partition on the target disk before the install
- **Expected:** fisherman finds that the disk is busy and fails early
- **Verify:** Helpful error, no partial partition table

### 5. LUKS passphrase issues
- **Trigger:** Empty passphrase or special characters
- **Expected:** cryptsetup handles gracefully
- **Verify:** No hang, clear error if passphrase rejected

### 6. fisherman binary missing/corrupt
- **Trigger:** Delete/corrupt `~/.cache/bootc-installer/fisherman` after the installer stages it
- **Expected:** GUI shows "failed to launch" error
- **Verify:** No hang, clear error message

### 7. Permission denied (pkexec cancelled)
- **Trigger:** Deny the polkit prompt when fisherman tries to elevate
- **Expected:** Install fails immediately with permission error
- **Verify:** GUI shows actionable error, no orphan processes

### 8. Disk fills during install
- **Trigger:** Fill `/var/fisherman-tmp` during image pull
- **Expected:** Podman/bootc fails with ENOSPC
- **Verify:** The error hint tells about disk space

## Cleanup Verification

After any failure:
- [ ] No leftover mounts at `/mnt/fisherman-target`
- [ ] No open LUKS devices (`/dev/mapper/fisherman-*`)
- [ ] No orphan fisherman processes (`pgrep fisherman`)
- [ ] Target disk not left with partial partition table (or the installer warns the user)

## Files to Change

- [ ] `tests/unit/test_failure_hints.py` (new — test `__extract_failure_hint()` logic)
- [ ] `tests/ui/test_done.py` (how the failure state renders)
- [ ] `bootc_installer/views/done.py` (improve hint extraction)
- [ ] `fisherman/fisherman/cmd/fisherman/main.go` (cleanup on error)

## Acceptance

- [ ] Each failure scenario produces a user-readable error hint
- [ ] Retry button works after failure (no stale state)
- [ ] No orphan processes or mounts after failure
- [ ] Unit tests cover all error hint categories
