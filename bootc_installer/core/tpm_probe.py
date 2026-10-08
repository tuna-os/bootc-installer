"""TPM 2.0 detection, per shared/tpm/README.md.

Canonical copy. The Python frontends carry byte-identical copies and a test
enforces that they match, the same arrangement shared/progress/ uses.

The point of the root parameter is that no CI runner has a TPM of any
version, so the only way to test this is to point it at a fixture tree.
"""

import os

# The kernel writes the TCG spec major version here: "2" for TPM 2.0, "1"
# for TPM 1.2. Added in Linux 5.5.
VERSION_FILE = "sys/class/tpm/tpm0/tpm_version_major"

# The in-kernel resource manager is a TPM 2.0 feature, so the kernel makes
# this device node only for a 2.0 device. It is the fallback for kernels
# older than 5.5, where VERSION_FILE does not exist.
RESOURCE_MANAGER = "dev/tpmrm0"


def probe_tpm2(root: str = "/") -> bool:
    """Whether `root` holds a TPM 2.0 device.

    Testing `/sys/class/tpm/tpm0` for existence, which every frontend used
    to do, is true for a TPM 1.2 device as well.
    """
    try:
        with open(os.path.join(root, VERSION_FILE), encoding="utf-8") as fh:
            return fh.read().strip() == "2"
    except OSError:
        # No version file: either a kernel older than 5.5, or no TPM.
        return os.path.exists(os.path.join(root, RESOURCE_MANAGER))


def fake_tpm_requested(environ=None) -> bool:
    """Whether BOOTC_INSTALLER_FAKE_TPM forces the answer to true.

    It only ever forces it ON, so a capture can show what the installer
    offers rather than what the runner's hardware allows. An exported but
    blank value does not count, so it cannot turn the choices on by
    accident.
    """
    env = os.environ if environ is None else environ
    return env.get("BOOTC_INSTALLER_FAKE_TPM", "") not in ("", "0")
