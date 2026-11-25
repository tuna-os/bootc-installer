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
