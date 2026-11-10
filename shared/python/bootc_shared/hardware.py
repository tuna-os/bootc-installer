"""Hardware facts that `fisherman probe --json` does not report yet.

The probe has the disks, the TPM, live media and the requirements
(shared/probe/README.md). It has no GPU field, so the NVIDIA rule of
shared/catalog/README.md ("Image and NVIDIA image") reads sysfs here. A
Flatpak sees /sys too. This module goes when the probe has the fact.
"""

import os

PCI_DEVICES = "/sys/bus/pci/devices"
NVIDIA_VENDOR = "0x10de"
# The top byte of a PCI class: VGA, 3D and display controllers.
DISPLAY_CLASS = 0x03


def display_devices(pci_devices=PCI_DEVICES) -> list:
    """[(pci_address, vendor_id)] for each PCI display device, in the order
    of the names. `vendor_id` is lower case, as sysfs writes it ("0x10de").
    A device that cannot be read, or whose class is not a number, is not a
    display device."""
    try:
        names = sorted(os.listdir(pci_devices))
    except OSError:
        return []
    found = []
    for name in names:
        device = os.path.join(pci_devices, name)
        try:
            with open(os.path.join(device, "class"), encoding="ascii") as stream:
                pci_class = int(stream.read().strip(), 16)
            if (pci_class >> 16) != DISPLAY_CLASS:
                continue
            with open(os.path.join(device, "vendor"), encoding="ascii") as stream:
                vendor = stream.read().strip().lower()
        except (OSError, ValueError):
            continue
        found.append((name, vendor))
    return found


def has_nvidia_gpu(pci_devices=PCI_DEVICES) -> bool:
    """Whether a PCI display device has NVIDIA's vendor id."""
    return any(vendor == NVIDIA_VENDOR for _address, vendor in display_devices(pci_devices))
