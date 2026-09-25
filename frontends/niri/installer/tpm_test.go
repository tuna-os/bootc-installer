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

// The override the other four frontends have had. Niri did not, so its
// capture rendered a two-option encryption page on every runner -- exactly
// the blind spot the override exists to close.
func TestFakeTPMOverride(t *testing.T) {
	for _, v := range []string{"1", "true", "yes"} {
		t.Setenv("BOOTC_INSTALLER_FAKE_TPM", v)
		if !fakeTPMRequested() {
			t.Errorf("%q must force the choices on", v)
		}
	}
	for _, v := range []string{"", "0"} {
		t.Setenv("BOOTC_INSTALLER_FAKE_TPM", v)
		if fakeTPMRequested() {
			t.Errorf("%q must not force the choices on", v)
		}
	}
}

// It makes the choices VISIBLE. It does not make them work: fisherman still
// fails at enrolment on a machine with no TPM 2.0.
func TestFakeTPMIsACaptureAidNotAHardwareClaim(t *testing.T) {
	t.Setenv("BOOTC_INSTALLER_FAKE_TPM", "1")
	if !hasTPM() {
		t.Fatal("the override must show the choices")
	}
	if probeTPM2(filepath.Join(tpmFixtures, "tpm12")) {
		t.Fatal("the probe itself must stay honest about the hardware")
	}
}
