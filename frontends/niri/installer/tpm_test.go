package main

import (
	"path/filepath"
	"testing"
)

// The fixture trees are shared/tpm/fixtures/, which every frontend's probe
// is pointed at so all five agree. See shared/tpm/README.md.
const tpmFixtures = "../../../shared/tpm/fixtures"

func TestProbeTPM2(t *testing.T) {
	cases := []struct {
		tree string
		want bool
		why  string
	}{
		{"tpm2", true, "tpm_version_major reads 2"},
		{"tpm12", false, "tpm_version_major reads 1, and 1.2 cannot do tpm2-luks"},
		{"legacy-tpm2", true, "no version file, but /dev/tpmrm0 is TPM2-only"},
		{"legacy-none", false, "no version file and no resource manager"},
	}
	for _, c := range cases {
		t.Run(c.tree, func(t *testing.T) {
			got := probeTPM2(filepath.Join(tpmFixtures, c.tree))
			if got != c.want {
				t.Errorf("probeTPM2(%s) = %v, want %v -- %s", c.tree, got, c.want, c.why)
			}
		})
	}
}

// The bug this replaced: the directory alone was the whole test, and the
// kernel makes it for a TPM 1.2 device too.
func TestTpmDirectoryAloneIsNotEnough(t *testing.T) {
	if probeTPM2(filepath.Join(tpmFixtures, "tpm12")) {
		t.Fatal("a TPM 1.2 device must not report as TPM 2.0")
	}
}
