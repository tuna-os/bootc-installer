"""List the disks that the installer daemon offers, with normalised sizes.

    python3 example_candidates.py [SOCKET [DEFINITIONS_DIR...]]

The call is io.systemd.SysInstall.ListCandidateDevices, as gnome-setup makes
it. With "subscribe" the service keeps the stream open and sends "add" and
"remove" actions when a disk comes or goes. This example asks for no
subscription, so it ends after the first full list.
"""

import sys

from sizes import normalize_size_text
from varlink_client import Connection

DEFAULT_SOCKET = "/run/systemd/io.systemd.SysInstall"


def candidates(path, definitions):
    with Connection(path) as connection:
        stream = connection.call_more(
            "io.systemd.SysInstall.ListCandidateDevices",
            {"definitions": definitions, "subscribe": False})
        for device in stream:
            if device.get("node"):
                yield device


def label(device):
    name = " ".join(filter(None, (device.get("vendor"), device.get("model")))) or "Unknown Disk"
    size = device.get("sizeBytes", 0)
    return normalize_size_text("%s %.1f GB" % (name, size / 1e9))


if __name__ == "__main__":
    socket_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOCKET
    for found in candidates(socket_path, sys.argv[2:]):
        print(found["node"], label(found), found.get("fit", ""))
