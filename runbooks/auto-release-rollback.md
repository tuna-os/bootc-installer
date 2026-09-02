# Runbook: rolling back a bad auto-release

`.github/workflows/flatpak.yml`'s `auto-release` job cuts a real,
non-prerelease GitHub release on every push to `dev` and marks it
`--latest`. That job only verifies the release asset is *reachable* — it
does not run the Python/Go test suites or any functional check — so a
`dev` push that compiles but is broken at runtime can become the release
served at `releases/latest/download/org.bootcinstaller.Installer.flatpak`.

That URL is what live ISOs (e.g. `projectbluefin/dakota-iso`) and other
downstream consumers pull from. They are not pinned to a tag — rolling
one back means moving what `latest` points to, not just fixing `dev`.

## 1. Confirm it's actually the latest release that's bad

```bash
gh release list --repo tuna-os/bootc-installer --limit 5
gh release view "$(gh release list --repo tuna-os/bootc-installer --limit 1 --json tagName --jq '.[0].tagName')" \
  --repo tuna-os/bootc-installer
```

Reproduce against the actual asset before touching anything — download
and run it, or check CI/user reports against the specific tag, not just
"dev looks broken now". `dev` may have already moved past the bad commit.

## 2. Find the last known-good release

```bash
gh release list --repo tuna-os/bootc-installer --limit 15 \
  --json tagName,createdAt,isLatest
```

Auto-release tags are `v<date>-<short-sha>` (e.g. `v2026.08.22-623f61f4`),
one per `dev` push — so the previous entry in this list is the previous
`dev` push, not necessarily a vetted release. Verify it works (or at
minimum that its commit predates the regression) before promoting it.

## 3. Re-point `latest`

```bash
# Demote the bad release
gh release edit <bad-tag> --repo tuna-os/bootc-installer --latest=false

# Promote the last known-good release
gh release edit <good-tag> --repo tuna-os/bootc-installer --latest
```

`releases/latest/` always resolves to the newest release with
`--latest=true` among non-prerelease releases — it is not simply "most
recently created", so demoting the bad one is not enough by itself if a
newer-but-also-bad release exists; check the full list from step 2.

## 4. Verify the fix took

```bash
curl -sfIL -o /dev/null https://github.com/tuna-os/bootc-installer/releases/latest/download/org.bootcinstaller.Installer.flatpak && \
  echo reachable
gh release view --repo tuna-os/bootc-installer -R tuna-os/bootc-installer 2>/dev/null | head -1
```

Confirm the tag now served under `releases/latest/` is `<good-tag>`, not
just that a file is reachable — a stale-but-present asset would pass the
`curl` check while still being wrong.

## 5. Fix forward

Re-pointing `latest` only stops new pulls of the bad build — it does not
fix `dev`. File/confirm the regression against the bad commit, land the
fix, and let the next `dev` push cut a new auto-release. Do not delete
the bad release/tag (`gh release delete`); leaving it demoted but intact
preserves the audit trail and any artifact already cached by a consumer
that pinned the tag directly instead of `latest`.

## Prevention

This runbook is a recovery procedure, not a fix for the underlying gap:
`auto-release` gates only on the `production` build job, not on the
Python/Go/UI test suites. Closing that gap is a separate, larger change
to workflow dependencies (`needs:`) and is out of scope here — see
[#57](https://github.com/tuna-os/bootc-installer/issues/57).
