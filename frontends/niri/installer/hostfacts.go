package main

// Host facts the daemon does not report: the image's release type (the
// prerelease page) and the EULA text (the eula page).
//
// Both are read from the host, not from fisherman, so they work on either
// backend path. The os-release search reuses branding.go's host-first
// paths; TUNA_OS_RELEASE points at one file for tests. The EULA lookup
// follows gnome-setup ($PKGDATADIR/eula.xml): TUNA_EULA_FILE, then the
// installed data directory. No file means no eula page — the spec's EULA
// path is an open question, and "no file, no page" matches gnome-setup.

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// osReleaseEnv overrides the os-release file (tests).
const osReleaseEnv = "TUNA_OS_RELEASE"

// eulaEnv overrides the EULA file (tests).
const eulaEnv = "TUNA_EULA_FILE"

// readOsRelease parses the first readable os-release file.
func readOsRelease() map[string]string {
	if p := os.Getenv(osReleaseEnv); p != "" {
		data, err := os.ReadFile(p)
		if err != nil {
			return map[string]string{}
		}
		return parseOsRelease(string(data))
	}
	for _, path := range osReleasePaths {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		return parseOsRelease(string(data))
	}
	return map[string]string{}
}

// osReleaseType reads RELEASE_TYPE from os-release: "pre-release" and
// "experiment" show the prerelease page; anything else (missing file,
// missing key, unknown value) counts as stable and skips it.
func osReleaseType() string {
	switch v := readOsRelease()["RELEASE_TYPE"]; v {
	case "pre-release", "experiment":
		return v
	default:
		return "stable"
	}
}

// osReleaseExperiment reads EXPERIMENT from os-release: the free text the
// prerelease page shows for an experiment. "" when absent.
func osReleaseExperiment() string {
	return readOsRelease()["EXPERIMENT"]
}

func eulaPaths() []string {
	if p := os.Getenv(eulaEnv); p != "" {
		return []string{p}
	}
	return []string{
		"/app/share/tuna-installer-niri/eula.xml",
		"/usr/share/tuna-installer-niri/eula.xml",
	}
}

// eulaMain is the `eula` subcommand: {"present": bool, "text": ...} for the
// eula page. A missing file is {"present": false} (the page is skipped); a
// path that exists but cannot be read is {"present": true, "unreadable":
// true} (the eula-unreadable failure state: the terms cannot load).
func eulaMain() {
	for _, path := range eulaPaths() {
		data, err := os.ReadFile(path)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			out, _ := json.Marshal(map[string]any{
				"present": true, "unreadable": true,
				"path": filepath.Base(path),
			})
			fmt.Println(string(out))
			return
		}
		out, _ := json.Marshal(map[string]any{"present": true, "text": string(data)})
		fmt.Println(string(out))
		return
	}
	out, _ := json.Marshal(map[string]any{"present": false})
	fmt.Println(string(out))
}
