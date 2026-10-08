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

// fakeTPMRequested reports whether BOOTC_INSTALLER_FAKE_TPM forces the answer
// to true. It only ever forces it ON, so a capture can show what the installer
// offers rather than what the runner's hardware allows. An exported but blank
// value does not count, so it cannot turn the choices on by accident.
//
// Same variable and same meaning as the other four frontends use.
func fakeTPMRequested() bool {
	v := os.Getenv("BOOTC_INSTALLER_FAKE_TPM")
	return v != "" && v != "0"
}

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
