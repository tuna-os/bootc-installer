package main

// Product branding: a branding.json first, os-release second, neutral last.
//
// The contract, the key table and the fixtures are in shared/branding/
// (monorepo root). Every frontend resolves the same way; this is the Go
// copy, exercised against the shared fixtures by branding_test.go. Nothing
// in this file names a product.

import (
	"encoding/json"
	"os"
	"strings"
)

const (
	brandingEnvFile = "BOOTC_INSTALLER_BRANDING"
	brandingEnvName = "BOOTC_INSTALLER_PRODUCT_NAME"
	neutralName     = "Linux"
	neutralID       = "linux"
)

// Host first: this ships as a flatpak, where /etc is the runtime's and the
// host's is under /run/host. The first readable file wins; no merging.
var brandingPaths = []string{
	"/run/host/etc/bootc-installer/branding.json",
	"/run/host/usr/share/bootc-installer/branding.json",
	"/etc/bootc-installer/branding.json",
	"/usr/share/bootc-installer/branding.json",
}

var osReleasePaths = []string{
	"/run/host/etc/os-release",
	"/run/host/usr/lib/os-release",
	"/etc/os-release",
	"/usr/lib/os-release",
}

// Branding is the JSON the QML receives under detect's "branding" key.
type Branding struct {
	Name            string `json:"name"`
	ID              string `json:"id"`
	Vendor          string `json:"vendor"`
	HomeURL         string `json:"homeUrl"`
	DocsURL         string `json:"docsUrl"`
	SupportURL      string `json:"supportUrl"`
	Logo            string `json:"logo"`
	DefaultHostname string `json:"defaultHostname"`
	DefaultImage    string `json:"defaultImage"`
}

// resolveBranding reads the machine's branding using the real search paths
// and environment.
func resolveBranding() Branding {
	paths := brandingPaths
	if p := strings.TrimSpace(os.Getenv(brandingEnvFile)); p != "" {
		paths = []string{p}
	}
	return resolveBrandingFrom(paths, osReleasePaths, os.Getenv(brandingEnvName))
}

func resolveBrandingFrom(filePaths, osrPaths []string, nameOverride string) Branding {
	var file map[string]any
	for _, p := range filePaths {
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		var m map[string]any
		if json.Unmarshal(data, &m) != nil || m == nil {
			continue
		}
		file = m
		break
	}
	osr := ""
	for _, p := range osrPaths {
		data, err := os.ReadFile(p)
		if err != nil || strings.TrimSpace(string(data)) == "" {
			continue
		}
		osr = string(data)
		break
	}
	return brandingFromSources(file, osr, nameOverride)
}

// brandingFromSources is the pure merge rule from shared/branding/README.md.
func brandingFromSources(file map[string]any, osReleaseText, nameOverride string) Branding {
	osr := parseOsRelease(osReleaseText)
	pick := func(key string, def string, osKeys ...string) string {
		if v, ok := file[key].(string); ok && strings.TrimSpace(v) != "" {
			return strings.TrimSpace(v)
		}
		for _, k := range osKeys {
			if v := strings.TrimSpace(osr[k]); v != "" {
				return v
			}
		}
		return def
	}
	b := Branding{
		Name:            pick("name", neutralName, "PRETTY_NAME", "NAME"),
		ID:              pick("id", neutralID, "ID"),
		Vendor:          pick("vendor", "", "VENDOR_NAME", "NAME"),
		HomeURL:         pick("home_url", "", "HOME_URL"),
		DocsURL:         pick("docs_url", "", "DOCUMENTATION_URL"),
		SupportURL:      pick("support_url", "", "SUPPORT_URL"),
		Logo:            pick("logo", "", "LOGO"),
		DefaultHostname: pick("default_hostname", neutralID, "DEFAULT_HOSTNAME", "ID"),
		DefaultImage:    pick("default_image", ""),
	}
	if o := strings.TrimSpace(nameOverride); o != "" {
		b.Name = o
	}
	return b
}

// parseOsRelease returns KEY=value pairs with quotes and backslash escapes
// removed. Lines that do not parse are skipped, not fatal.
func parseOsRelease(text string) map[string]string {
	out := map[string]string{}
	for _, raw := range strings.Split(text, "\n") {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		if key == "" {
			continue
		}
		out[key] = unquoteShell(strings.TrimSpace(value))
	}
	return out
}

// unquoteShell handles the subset of shell quoting os-release allows: a
// double-quoted string with backslash escapes, a single-quoted string, or a
// bare word (which ends at the first whitespace, like shlex.split()[0]).
func unquoteShell(v string) string {
	if v == "" {
		return ""
	}
	switch v[0] {
	case '"':
		var sb strings.Builder
		for i := 1; i < len(v); i++ {
			c := v[i]
			if c == '\\' && i+1 < len(v) {
				i++
				sb.WriteByte(v[i])
				continue
			}
			if c == '"' {
				break
			}
			sb.WriteByte(c)
		}
		return strings.TrimSpace(sb.String())
	case '\'':
		rest := v[1:]
		if end := strings.IndexByte(rest, '\''); end >= 0 {
			rest = rest[:end]
		}
		return strings.TrimSpace(rest)
	default:
		if i := strings.IndexAny(v, " \t"); i >= 0 {
			v = v[:i]
		}
		return v
	}
}
