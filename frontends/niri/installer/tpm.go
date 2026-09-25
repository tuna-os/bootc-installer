package main

// TPM 2.0 detection, per shared/tpm/README.md.

import (
	"os"
	"path/filepath"
	"strings"
)

// tpmVersionFile holds the TCG spec major version the kernel read off the
// device: "2" for TPM 2.0, "1" for TPM 1.2. Added in Linux 5.5.
const tpmVersionFile = "sys/class/tpm/tpm0/tpm_version_major"

// tpmResourceManager is the in-kernel resource manager device node. It is a
// TPM 2.0 feature, so the kernel makes it only for a 2.0 device. This is the
// fallback for kernels older than 5.5, which have no tpmVersionFile.
const tpmResourceManager = "dev/tpmrm0"

// probeTPM2 reports whether root holds a TPM 2.0 device.
//
// The root parameter exists because no CI runner has a TPM of any version,
// so a fixture tree is the only way to test this.
func probeTPM2(root string) bool {
	b, err := os.ReadFile(filepath.Join(root, tpmVersionFile))
	if err == nil {
		return strings.TrimSpace(string(b)) == "2"
	}
	_, err = os.Stat(filepath.Join(root, tpmResourceManager))
	return err == nil
}
