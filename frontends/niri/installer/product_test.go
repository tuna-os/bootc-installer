package main

import (
	"os"
	"path/filepath"
	"testing"
)

func write(t *testing.T, dir, name, body string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestProductNameFrom(t *testing.T) {
	dir := t.TempDir()
	host := write(t, dir, "host", "ID=tunaos\nPRETTY_NAME=\"Skipjack\"\n")
	sandbox := write(t, dir, "sandbox", "PRETTY_NAME='Freedesktop SDK'\n")
	empty := write(t, dir, "empty", "PRETTY_NAME=\nID=x\n")
	missing := filepath.Join(dir, "nope")

	cases := []struct {
		name  string
		paths []string
		want  string
	}{
		{"host preferred over sandbox", []string{host, sandbox}, "Skipjack"},
		{"quotes stripped", []string{sandbox}, "Freedesktop SDK"},
		{"missing file skipped", []string{missing, sandbox}, "Freedesktop SDK"},
		{"empty value skipped", []string{empty, sandbox}, "Freedesktop SDK"},
		{"nothing readable", []string{missing}, ""},
	}
	for _, tc := range cases {
		if got := productNameFrom(tc.paths...); got != tc.want {
			t.Errorf("%s: got %q want %q", tc.name, got, tc.want)
		}
	}
}
