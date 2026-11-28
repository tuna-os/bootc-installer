package varlinkapi

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func userFixture(t *testing.T, files map[string]string) string {
	t.Helper()
	d := t.TempDir()
	for rel, body := range files {
		p := filepath.Join(d, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(body), 0o640); err != nil {
			t.Fatal(err)
		}
	}
	return d
}

func readIn(t *testing.T, d, rel string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(d, rel))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// TestAddUserWritesWhatUseraddWrites: user, private group, shadow and gshadow
// lines, membership of the admin group, subordinate ids. Files keep their
// inode and mode (so their SELinux label), and nothing runs useradd, which
// fails in a chroot without /proc on EL10 (tunaOS run 46063422856).
func TestAddUserWritesWhatUseraddWrites(t *testing.T) {
	d := userFixture(t, map[string]string{
		"etc/passwd":  "root:x:0:0:root:/root:/bin/bash\nbin:x:1:1:bin:/bin:/sbin/nologin\n",
		"etc/group":   "root:x:0:\nwheel:x:10:\nbuilder:x:1000:\n",
		"etc/shadow":  "root:*:1:::::\n",
		"etc/gshadow": "root:::\nwheel:::joe\nbuilder:!::\n",
		"etc/subuid":  "builder:100000:65536\n",
		"etc/subgid":  "builder:100000:65536\n",
		// an nss-altfiles account holds uid 1001; builder holds gid 1000
		"usr/lib/passwd": "svc:x:1001:1001:svc:/:/sbin/nologin\n",
	})
	before, _ := os.Stat(filepath.Join(d, "etc/passwd"))
	name := "Ada Lovelace"
	if err := addUser(d, &User{Username: "ada", FullName: &name}, "wheel"); err != nil {
		t.Fatal(err)
	}
	checks := map[string]string{
		"etc/passwd":  "ada:x:1000:1001:Ada Lovelace:/home/ada:/bin/bash\n",
		"etc/group":   "ada:x:1001:\n",
		"etc/shadow":  "ada:!:",
		"etc/gshadow": "ada:!::\n",
		"etc/subuid":  "ada:165536:65536\n",
		"etc/subgid":  "ada:165536:65536\n",
	}
	for rel, want := range checks {
		if got := readIn(t, d, rel); !strings.Contains(got, want) {
			t.Errorf("%s lacks %q:\n%s", rel, want, got)
		}
	}
	if got := readIn(t, d, "etc/group"); !strings.Contains(got, "wheel:x:10:ada\n") {
		t.Errorf("not in wheel:\n%s", got)
	}
	if got := readIn(t, d, "etc/gshadow"); !strings.Contains(got, "wheel:::joe,ada\n") {
		t.Errorf("gshadow wheel:\n%s", got)
	}
	after, _ := os.Stat(filepath.Join(d, "etc/passwd"))
	if !os.SameFile(before, after) || after.Mode() != before.Mode() {
		t.Error("passwd was replaced instead of rewritten in place")
	}
	if got := readIn(t, d, "etc/passwd"); strings.Count(got, "\n") != 3 {
		t.Errorf("passwd:\n%s", got)
	}
}

func TestAddUserRefusesWhatUseraddRefuses(t *testing.T) {
	d := userFixture(t, map[string]string{
		"etc/passwd": "root:x:0:0:root:/root:/bin/bash\n",
		"etc/group":  "root:x:0:\nada:x:500:\n",
	})
	if err := addUser(d, &User{Username: "root"}, ""); err == nil {
		t.Error("an existing user was added")
	}
	if err := addUser(d, &User{Username: "ada"}, ""); err == nil {
		t.Error("a name taken by a group was added")
	}
	for _, bad := range []string{"", "1ada", "-ada", "Ada", "a:b", "a b", strings.Repeat("a", 33)} {
		if err := addUser(d, &User{Username: bad}, ""); err == nil {
			t.Errorf("invalid name %q accepted", bad)
		}
	}
	fn := "x:y"
	if err := addUser(d, &User{Username: "bob", FullName: &fn}, ""); err == nil {
		t.Error("a full name with a colon was accepted")
	}
	// Without shadow, gshadow, subuid and admin group: only passwd and group.
	if err := addUser(d, &User{Username: "bob"}, ""); err != nil {
		t.Fatal(err)
	}
	if got := readIn(t, d, "etc/passwd"); !strings.Contains(got, "bob:x:1000:1000::/home/bob:/bin/bash\n") {
		t.Errorf("passwd:\n%s", got)
	}
}
