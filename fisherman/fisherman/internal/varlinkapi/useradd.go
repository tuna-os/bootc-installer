package varlinkapi

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// addUser adds an account to a deployment's /etc/passwd, group, shadow,
// gshadow, subuid and subgid, the way `useradd --user-group --no-create-home`
// does, without running useradd.
//
// `useradd --root` chroots into the deployment. There /proc and
// /sys/fs/selinux are missing while libselinux still thinks SELinux is on, so
// shadow-utils 4.15 (EL10) fails to set the file creation context
// ("openat(/proc/thread-self/attr/fscreate) = ENOENT") and aborts with
// "failure while writing changes to /etc/passwd", enforcing or not (tunaOS
// run 46063422856, albacore:kde). The files are rewritten in place, so each
// keeps its inode, mode and SELinux label.
//
// The password stays locked ("!"); the caller sets the hash. admin is the
// group that grants administrator rights, or "".
func addUser(d string, u *User, admin string) error {
	name := u.Username
	if !validAccountName(name) {
		return fmt.Errorf("invalid user name %q", name)
	}
	etc := filepath.Join(d, "etc")
	passwd, err := readLines(filepath.Join(etc, "passwd"))
	if err != nil {
		return err
	}
	group, err := readLines(filepath.Join(etc, "group"))
	if err != nil {
		return err
	}
	// Accounts of the image that live in /usr/lib/{passwd,group} (nss-altfiles)
	// take part in the name and id checks too.
	altPasswd, _ := readLines(filepath.Join(d, "usr/lib/passwd"))
	altGroup, _ := readLines(filepath.Join(d, "usr/lib/group"))

	usedUID := idSet(append(append([]string{}, passwd...), altPasswd...), 2)
	usedGID := idSet(append(append([]string{}, group...), altGroup...), 2)
	if usedName(append(append([]string{}, passwd...), altPasswd...), name) {
		return fmt.Errorf("user %q already exists", name)
	}
	if usedName(append(append([]string{}, group...), altGroup...), name) {
		return fmt.Errorf("group %q already exists", name)
	}
	// UID_MIN / GID_MIN of login.defs: 1000 on every base the medium has.
	uid := 1000
	for usedUID[uid] {
		uid++
	}
	// The private group takes the user's id when it is free.
	gid := uid
	for usedGID[gid] {
		gid++
	}
	comment := ""
	if u.FullName != nil {
		comment = *u.FullName
	}
	if strings.ContainsAny(comment, ":\n") {
		return fmt.Errorf("invalid full name %q", comment)
	}

	passwd = append(passwd, fmt.Sprintf("%s:x:%d:%d:%s:/home/%s:/bin/bash", name, uid, gid, comment, name))
	group = append(group, fmt.Sprintf("%s:x:%d:", name, gid))
	if admin != "" {
		group = editMembers(group, admin, 3, name)
	}
	if err := writeLines(filepath.Join(etc, "passwd"), passwd); err != nil {
		return err
	}
	if err := writeLines(filepath.Join(etc, "group"), group); err != nil {
		return err
	}

	days := time.Now().Unix() / 86400
	if shadow, err := readLines(filepath.Join(etc, "shadow")); err == nil {
		shadow = append(shadow, fmt.Sprintf("%s:!:%d:0:99999:7:::", name, days))
		if err := writeLines(filepath.Join(etc, "shadow"), shadow); err != nil {
			return err
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	if gshadow, err := readLines(filepath.Join(etc, "gshadow")); err == nil {
		gshadow = append(gshadow, fmt.Sprintf("%s:!::", name))
		if admin != "" {
			gshadow = editMembers(gshadow, admin, 3, name)
		}
		if err := writeLines(filepath.Join(etc, "gshadow"), gshadow); err != nil {
			return err
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	// Subordinate ids for rootless containers, where the image keeps the files.
	for _, f := range []string{"subuid", "subgid"} {
		p := filepath.Join(etc, f)
		lines, err := readLines(p)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return err
		}
		start := 100000 // SUB_UID_MIN, SUB_UID_COUNT 65536
		for _, l := range lines {
			fs := strings.Split(l, ":")
			if len(fs) != 3 {
				continue
			}
			first, e1 := strconv.Atoi(fs[1])
			count, e2 := strconv.Atoi(fs[2])
			if e1 == nil && e2 == nil && first+count > start {
				start = first + count
			}
		}
		lines = append(lines, fmt.Sprintf("%s:%d:65536", name, start))
		if err := writeLines(p, lines); err != nil {
			return err
		}
	}
	return nil
}

// validAccountName is useradd's rule: lower-case letters, digits, '_' and
// '-', not starting with a digit or '-', at most 32 characters.
func validAccountName(s string) bool {
	if s == "" || len(s) > 32 || s[0] == '-' || (s[0] >= '0' && s[0] <= '9') {
		return false
	}
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return false
		}
	}
	return true
}

// readLines returns the lines of an /etc database without a trailing empty one.
func readLines(path string) ([]string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	s := strings.TrimSuffix(string(b), "\n")
	if s == "" {
		return nil, nil
	}
	return strings.Split(s, "\n"), nil
}

// writeLines rewrites a file in place: same inode, mode, owner and label.
func writeLines(path string, lines []string) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_TRUNC, 0)
	if err != nil {
		return err
	}
	if _, err := f.WriteString(strings.Join(lines, "\n") + "\n"); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

// idSet is the set of numeric ids in field n of passwd-style lines.
func idSet(lines []string, n int) map[int]bool {
	out := map[int]bool{}
	for _, l := range lines {
		f := strings.Split(l, ":")
		if len(f) > n {
			if id, err := strconv.Atoi(f[n]); err == nil {
				out[id] = true
			}
		}
	}
	return out
}

func usedName(lines []string, name string) bool {
	for _, l := range lines {
		if n, _, ok := strings.Cut(l, ":"); ok && n == name {
			return true
		}
	}
	return false
}

// editMembers appends user to the comma-separated member list at field idx of
// the line of group g (group and gshadow both keep the members in field 4).
func editMembers(lines []string, g string, idx int, user string) []string {
	for i, l := range lines {
		f := strings.Split(l, ":")
		if len(f) <= idx || f[0] != g {
			continue
		}
		if f[idx] == "" {
			f[idx] = user
		} else {
			f[idx] += "," + user
		}
		lines[i] = strings.Join(f, ":")
	}
	return lines
}
