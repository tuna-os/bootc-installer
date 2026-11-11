# Network check

Before an install that downloads its image, each frontend checks that the
machine can reach the network. `targets.json` pins what it probes, in which
order, how long it waits, and which variables turn the check off. All five
frontends follow it, and a test in each one reads it.

## The order

1. The registry of the selected image. The install downloads from this
   host, so it is the best answer.
2. The shared targets: `ghcr.io:443`, then `8.8.8.8:53`.

The list has no target two times. A frontend stops at the first target
that accepts a TCP connection. It waits `timeout_seconds` (5) for each
target.

## The registry of an image

1. Remove the spaces at the two ends.
2. Remove an ostree prefix: `ostree-unverified-registry:`,
   `ostree-unverified-image:` or `ostree-image-signed:`. For
   `ostree-remote-registry:` and `ostree-remote-image:`, also remove the
   remote name and the colon after it.
3. Remove `docker://`.
4. An empty reference, a path, a local transport (`containers-storage:`,
   `oci:`, `oci-archive:`, `dir:`) or another URL has no registry. The
   list then starts with the shared targets.
5. The part before the first `/` is a registry when it has a dot or a
   port. `localhost` is also a registry. A reference with no such part is
   a Docker Hub name: the target is `registry-1.docker.io:443`.
6. The target keeps the port of the registry. Without a port, the port is
   443.

## Turn the check off

A test harness with no route out sets `VANILLA_SKIP_CONN_CHECK` or
`TUNA_INSTALLER_SKIP_CONN_CHECK`. The check then passes. An empty value
and `0` do not turn the check off.

## Tests

| Frontend | Test |
|---|---|
| GNOME, XFCE (`bootc_shared.network`) | `tests/unit/test_shared_network.py`, `frontends/xfce/tests/test_network_targets.py` |
| KDE | `test_backend.cpp` (`networkTargetsFollowTheFixture`) |
| COSMIC | `preflight.rs` (`connect_targets_follow_the_shared_fixture`) |
| Niri | `session_test.go` (`TestNetcheckTargetsFollowTheSharedFixture`) |
