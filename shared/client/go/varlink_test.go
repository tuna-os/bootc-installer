package varlink

import (
	"bufio"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type sizeCase struct {
	Name       string `json:"name"`
	Input      string `json:"input"`
	Normalized string `json:"normalized"`
	Bytes      *int64 `json:"bytes"`
}

func TestSizeFixtures(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "fixtures", "sizes.json"))
	if err != nil {
		t.Fatal(err)
	}
	var f struct {
		Cases []sizeCase `json:"cases"`
	}
	if err := json.Unmarshal(raw, &f); err != nil {
		t.Fatal(err)
	}
	if len(f.Cases) == 0 {
		t.Fatal("no cases")
	}
	for _, c := range f.Cases {
		t.Run(c.Name, func(t *testing.T) {
			if got := NormalizeSizeText(c.Input); got != c.Normalized {
				t.Errorf("normalize(%q) = %q, want %q", c.Input, got, c.Normalized)
			}
			n, ok := ParseSize(c.Input)
			switch {
			case c.Bytes == nil && ok:
				t.Errorf("parse(%q) = %d, want not a size", c.Input, n)
			case c.Bytes != nil && (!ok || n != *c.Bytes):
				t.Errorf("parse(%q) = %d,%v, want %d", c.Input, n, ok, *c.Bytes)
			}
		})
	}
}

// serve runs script against one connection of a socket in a temp dir. The
// peer is a test double for the wire format, not the mock daemon.
func serve(t *testing.T, script func(req map[string]any, w *bufio.Writer)) string {
	t.Helper()
	dir, err := os.MkdirTemp("", "vl")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	path := filepath.Join(dir, "s")
	l, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { l.Close() })
	go func() {
		c, err := l.Accept()
		if err != nil {
			return
		}
		defer c.Close()
		r := bufio.NewReader(c)
		w := bufio.NewWriter(c)
		for {
			raw, err := r.ReadBytes(0)
			if err != nil {
				return
			}
			var req map[string]any
			if json.Unmarshal(raw[:len(raw)-1], &req) != nil {
				return
			}
			script(req, w)
			w.Flush()
		}
	}()
	return path
}

func msg(w *bufio.Writer, s string) { w.WriteString(s); w.WriteByte(0) }

func TestCall(t *testing.T) {
	path := serve(t, func(req map[string]any, w *bufio.Writer) {
		if req["method"] != "org.varlink.service.GetInfo" {
			t.Errorf("method = %v", req["method"])
		}
		msg(w, `{"parameters":{"vendor":"test"}}`)
	})
	c, err := Dial(path, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	var out struct{ Vendor string }
	if err := c.Call("org.varlink.service.GetInfo", nil, &out); err != nil {
		t.Fatal(err)
	}
	if out.Vendor != "test" {
		t.Errorf("vendor = %q", out.Vendor)
	}
}

func TestCallMoreEndsOnTheReplyWithoutContinues(t *testing.T) {
	path := serve(t, func(req map[string]any, w *bufio.Writer) {
		if req["more"] != true {
			t.Errorf("more = %v", req["more"])
		}
		msg(w, `{"parameters":{"progress":10},"continues":true}`)
		msg(w, `{"parameters":{"progress":100},"continues":true}`)
		msg(w, `{"parameters":{}}`)
	})
	c, _ := Dial(path, time.Second)
	defer c.Close()
	var seen []int
	err := c.CallMore("io.systemd.SysInstall.Run", map[string]any{"node": "/dev/vda"},
		func(p json.RawMessage) bool {
			var r struct{ Progress int }
			Decode(p, &r)
			seen = append(seen, r.Progress)
			return true
		})
	if err != nil {
		t.Fatal(err)
	}
	if len(seen) != 3 || seen[0] != 10 || seen[1] != 100 || seen[2] != 0 {
		t.Errorf("seen = %v", seen)
	}
}

func TestErrorReplyKeepsTheNameAndHidesTheParameters(t *testing.T) {
	path := serve(t, func(req map[string]any, w *bufio.Writer) {
		msg(w, `{"error":"io.systemd.SysInstall.DiskTooSmall","parameters":{"passphrase":"hunter2"}}`)
	})
	c, _ := Dial(path, time.Second)
	defer c.Close()
	err := c.Call("io.systemd.SysInstall.Run", nil, nil)
	ve, ok := err.(*Error)
	if !ok {
		t.Fatalf("err = %T %v", err, err)
	}
	if ve.Name != "io.systemd.SysInstall.DiskTooSmall" {
		t.Errorf("name = %q", ve.Name)
	}
	if strings.Contains(ve.Error(), "hunter2") {
		t.Error("the error text carries a parameter")
	}
}

func TestOnewayAndClosedConnection(t *testing.T) {
	got := make(chan map[string]any, 1)
	path := serve(t, func(req map[string]any, w *bufio.Writer) { got <- req })
	c, _ := Dial(path, time.Second)
	defer c.Close()
	if err := c.CallOneway("io.tunaos.Fisherman.Cancel", nil); err != nil {
		t.Fatal(err)
	}
	select {
	case req := <-got:
		if req["oneway"] != true {
			t.Errorf("oneway = %v", req["oneway"])
		}
	case <-time.After(2 * time.Second):
		t.Fatal("no request")
	}
}

func TestEOFIsAnError(t *testing.T) {
	a, b := net.Pipe()
	c := NewConn(a)
	go func() { b.Close() }()
	if err := c.Call("x.Y", nil, nil); err == nil {
		t.Fatal("want an error")
	}
}
