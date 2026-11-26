package main

import (
	"os"
	"strings"
)

// Names for people. The recipe takes "de_DE.UTF-8", "de" and
// "Europe/Berlin"; the Session step shows these and keeps the ids. An id that
// has no name is shown as it is. COSMIC has the same table (src/names.rs).

// languageNames: each language in its own words.
var languageNames = map[string]string{
	"af": "Afrikaans",
	"ar": "العربية",
	"be": "Беларуская",
	"bg": "Български",
	"bn": "বাংলা",
	"bs": "Bosanski",
	"ca": "Català",
	"cs": "Čeština",
	"cy": "Cymraeg",
	"da": "Dansk",
	"de": "Deutsch",
	"el": "Ελληνικά",
	"en": "English",
	"eo": "Esperanto",
	"es": "Español",
	"et": "Eesti",
	"eu": "Euskara",
	"fa": "فارسی",
	"fi": "Suomi",
	"fr": "Français",
	"ga": "Gaeilge",
	"gl": "Galego",
	"gu": "ગુજરાતી",
	"he": "עברית",
	"hi": "हिन्दी",
	"hr": "Hrvatski",
	"hu": "Magyar",
	"hy": "Հայերեն",
	"id": "Bahasa Indonesia",
	"is": "Íslenska",
	"it": "Italiano",
	"ja": "日本語",
	"ka": "ქართული",
	"kk": "Қазақша",
	"km": "ខ្មែរ",
	"kn": "ಕನ್ನಡ",
	"ko": "한국어",
	"lt": "Lietuvių",
	"lv": "Latviešu",
	"mk": "Македонски",
	"ml": "മലയാളം",
	"mr": "मराठी",
	"ms": "Bahasa Melayu",
	"nb": "Norsk bokmål",
	"ne": "नेपाली",
	"nl": "Nederlands",
	"nn": "Norsk nynorsk",
	"pa": "ਪੰਜਾਬੀ",
	"pl": "Polski",
	"pt": "Português",
	"ro": "Română",
	"ru": "Русский",
	"sk": "Slovenčina",
	"sl": "Slovenščina",
	"sq": "Shqip",
	"sr": "Српски",
	"sv": "Svenska",
	"ta": "தமிழ்",
	"te": "తెలుగు",
	"th": "ไทย",
	"tr": "Türkçe",
	"uk": "Українська",
	"ur": "اردو",
	"uz": "Oʻzbekcha",
	"vi": "Tiếng Việt",
	"zh": "中文",
}

// isLanguage: C and POSIX are locales, and no person's language.
func isLanguage(locale string) bool {
	base, _, _ := strings.Cut(locale, ".")
	return base != "" && base != "C" && base != "POSIX"
}

// languageName is "Deutsch (DE)" for "de_DE.UTF-8".
func languageName(locale string) string {
	base, _, _ := strings.Cut(locale, ".")
	base, _, _ = strings.Cut(base, "@")
	code, territory, _ := strings.Cut(base, "_")
	name := languageNames[code]
	if name == "" {
		return ""
	}
	if territory == "" {
		return name
	}
	return name + " (" + territory + ")"
}

// timezoneName is "Buenos Aires (America/Argentina)": the city first.
func timezoneName(zone string) string {
	i := strings.LastIndex(zone, "/")
	if i < 0 {
		return zone
	}
	plain := strings.NewReplacer("_", " ")
	return plain.Replace(zone[i+1:]) + " (" + plain.Replace(zone[:i]) + ")"
}

// xkbLists: the sandbox has its own list; the host's is the second choice.
var xkbLists = []string{
	"/usr/share/X11/xkb/rules/evdev.lst",
	"/run/host/usr/share/X11/xkb/rules/evdev.lst",
}

// parseXKBLayouts reads the "! layout" section of an XKB rules list.
func parseXKBLayouts(text string) map[string]string {
	names, inside := map[string]string{}, false
	for _, line := range strings.Split(text, "\n") {
		if section, ok := strings.CutPrefix(line, "!"); ok {
			inside = strings.TrimSpace(section) == "layout"
			continue
		}
		if fields := strings.Fields(line); inside && len(fields) > 1 {
			names[fields[0]] = strings.Join(fields[1:], " ")
		}
	}
	return names
}

func keyboardNames() map[string]string {
	for _, path := range xkbLists {
		if text, err := os.ReadFile(path); err == nil {
			return parseXKBLayouts(string(text))
		}
	}
	return map[string]string{}
}

// withNames gives the choice the name of each id that has one, and no name to
// two ids: the page reads the id back from the name.
func (c SessionChoice) withNames(name func(string) string) SessionChoice {
	c.Names = map[string]string{}
	taken := map[string]bool{}
	for _, id := range append([]string{c.Current}, c.Available...) {
		label := name(id)
		if id == "" || label == "" || label == id || c.Names[id] != "" || taken[label] {
			continue
		}
		c.Names[id], taken[label] = label, true
	}
	return c
}
