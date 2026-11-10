"""Can the install download its image: what to probe, and in which order.

The registry of the selected image is first. It is what the install
downloads from, so it is a better answer than a DNS server. The shared
targets come after it: the registry that most bootc images come from, then
a plain "is there a route" probe.
"""

import os
import socket

SHARED_TARGETS = (("ghcr.io", 443), ("8.8.8.8", 53))

# The registry that a reference with no registry in it names.
DEFAULT_REGISTRY = "registry-1.docker.io"

# A harness with no route out sets one of these. The value must be set and
# not "0": an empty variable does not turn the check off.
SKIP_ENV_VARS = ("VANILLA_SKIP_CONN_CHECK", "TUNA_INSTALLER_SKIP_CONN_CHECK")

TIMEOUT_SECONDS = 5


def registry_target(imgref):
    """(host, port) of the registry that serves `imgref`, or None.

    The first component of a reference is a registry when it has a dot or a
    port, or is "localhost"; otherwise the reference is a Docker Hub name.
    A registry with its own port is probed on that port, any other on 443.
    """
    ref = (imgref or "").strip() if isinstance(imgref, str) else ""
    if "://" in ref:
        ref = ref.split("://", 1)[1]
    if not ref:
        return None
    first = ref.split("/", 1)[0] if "/" in ref else ""
    if not first or not ("." in first or ":" in first or first == "localhost"):
        return (DEFAULT_REGISTRY, 443)
    host, _, port = first.partition(":")
    if not host:
        return None
    return (host, int(port) if port.isdigit() else 443)


def connectivity_targets(imgref=""):
    """What to probe, in order: the registry of the selected image, then
    the shared targets (#301). No target is in the list two times."""
    targets = []
    for target in (registry_target(imgref), *SHARED_TARGETS):
        if target and target not in targets:
            targets.append(target)
    return targets


def skip_requested(environ=None) -> bool:
    """Whether a harness turned the check off (SKIP_ENV_VARS)."""
    environ = os.environ if environ is None else environ
    return any(environ.get(name) not in (None, "", "0") for name in SKIP_ENV_VARS)


def has_connectivity(imgref="", timeout=TIMEOUT_SECONDS, connect=None, environ=None) -> bool:
    """Whether an install image could be downloaded now: the first of
    connectivity_targets(imgref) that accepts a connection."""
    if skip_requested(environ):
        return True
    connect = connect or socket.create_connection
    for host, port in connectivity_targets(imgref):
        try:
            sock = connect((host, port), timeout=timeout)
        except OSError:
            continue
        sock.close()
        return True
    return False
