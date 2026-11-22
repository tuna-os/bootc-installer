package varlink

import (
	"math"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

// spaceLike are the characters that look like a space and are not U+0020
// (projectbluefin/utah#1437). U+00A0 is what GLib's g_format_size writes.
const spaceLike = "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007" +
	"\u2008\u2009\u200a\u202f\u205f\u3000"

// invisible have no width and no place in a comparison.
const invisible = "\u200b\u200c\u200d\u200e\u200f\u2060\u2066\u2067\u2068\u2069\ufeff\u00ad"

// NormalizeSizeText makes one plain space of each run of space-like
// characters, trims the text and removes invisible marks.
func NormalizeSizeText(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch {
		case strings.ContainsRune(invisible, r):
		case strings.ContainsRune(spaceLike, r) || unicode.IsSpace(r):
			b.WriteRune(' ')
		default:
			b.WriteRune(r)
		}
	}
	return strings.Join(strings.Fields(b.String()), " ")
}

var units = map[string]float64{
	"b": 1, "byte": 1, "bytes": 1,
	"kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "pb": 1e15,
	"kib": 1 << 10, "mib": 1 << 20, "gib": 1 << 30, "tib": 1 << 40, "pib": 1 << 50,
}

var sizeRE = regexp.MustCompile(`^(\d[\d.,]*) ?([A-Za-z]+)$`)

func number(raw string) (float64, bool) {
	switch {
	case strings.Contains(raw, ".") && strings.Contains(raw, ","):
		raw = strings.ReplaceAll(raw, ",", "")
	case strings.Contains(raw, ","):
		i := strings.LastIndex(raw, ",")
		head, tail := raw[:i], raw[i+1:]
		if len(tail) == 3 {
			raw = strings.ReplaceAll(head, ",", "") + tail
		} else {
			raw = strings.ReplaceAll(head, ",", "") + "." + tail
		}
	}
	v, err := strconv.ParseFloat(raw, 64)
	return v, err == nil
}

// ParseSize returns the size in bytes. ok is false when s is not one size.
// SI units are powers of 1000, as g_format_size writes them. IEC units are
// powers of 1024.
func ParseSize(s string) (n int64, ok bool) {
	m := sizeRE.FindStringSubmatch(NormalizeSizeText(s))
	if m == nil {
		return 0, false
	}
	unit, found := units[strings.ToLower(m[2])]
	value, valid := number(m[1])
	if !found || !valid {
		return 0, false
	}
	return int64(math.Round(value * unit)), true
}
