package varlink_test

import (
	"encoding/json"
	"fmt"
	"time"

	varlink "github.com/tuna-os/installer/shared/client/go"
)

// Example_listCandidateDevices lists the disks of the installer daemon, as
// gnome-setup does. It has no Output line, so `go test` compiles it and does
// not run it: it needs a running service.
func Example_listCandidateDevices() {
	c, err := varlink.Dial("/run/systemd/io.systemd.SysInstall", 2*time.Second)
	if err != nil {
		fmt.Println(err)
		return
	}
	defer c.Close()
	type device struct {
		Node      string `json:"node"`
		Vendor    string `json:"vendor"`
		Model     string `json:"model"`
		SizeBytes int64  `json:"sizeBytes"`
		Fit       string `json:"fit"`
	}
	err = c.CallMore("io.systemd.SysInstall.ListCandidateDevices",
		map[string]any{"definitions": []string{}, "subscribe": false},
		func(p json.RawMessage) bool {
			var d device
			if varlink.Decode(p, &d) == nil && d.Node != "" {
				fmt.Printf("%s %s %.1f GB %s\n", d.Node,
					varlink.NormalizeSizeText(d.Vendor+" "+d.Model),
					float64(d.SizeBytes)/1e9, d.Fit)
			}
			return true
		})
	if err != nil {
		fmt.Println(err)
	}
}
