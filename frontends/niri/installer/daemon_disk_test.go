package main

import "testing"

func TestADiskIsNeverCalledByAPCIID(t *testing.T) {
	for _, c := range []struct{ vendor, model, bus, want string }{
		{"0x1af4", "", "VirtIO", "VirtIO disk"},
		{"0x1af4", "", "", "/dev/vda"},
		{"Mockware", "Mock NVMe", "NVMe", "Mock NVMe"},
		{"ATA", "", "SATA", "ATA"},
	} {
		if got := daemonDiskTitle(c.vendor, c.model, c.bus, "/dev/vda"); got != c.want {
			t.Errorf("%+v: got %q", c, got)
		}
	}
}

func TestADiskThatIsTooSmallIsNamedSo(t *testing.T) {
	reason := "too_small"
	for _, c := range []struct {
		disk daemonDisk
		want bool
	}{
		{daemonDisk{Eligible: true, SizeBytes: 64, MinimalSizeBytes: 20}, false},
		{daemonDisk{Eligible: true, SizeBytes: 8, MinimalSizeBytes: 20}, true},
		{daemonDisk{ExcludedReason: &reason}, true},
		{daemonDisk{}, false},
	} {
		if got := daemonTooSmall(c.disk); got != c.want {
			t.Errorf("%+v: got %v", c.disk, got)
		}
	}
	for in, want := range map[int64]string{0: "", 20 << 30: "20 GiB", 512110190592: "476.9 GiB"} {
		if got := sizeLabel(in); got != want {
			t.Errorf("sizeLabel(%d) = %q, want %q", in, got, want)
		}
	}
}
