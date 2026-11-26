package main

import (
	"reflect"
	"testing"
)

func TestNamesForPeople(t *testing.T) {
	for in, want := range map[string]string{
		"de_DE.UTF-8": "Deutsch (DE)", "eo": "Esperanto", "xx_XX.UTF-8": "", "ca_ES.UTF-8@valencia": "Català (ES)",
	} {
		if got := languageName(in); got != want {
			t.Errorf("languageName(%q) = %q, want %q", in, got, want)
		}
	}
	for in, want := range map[string]bool{"C": false, "C.UTF-8": false, "POSIX": false, "": false, "en_US.UTF-8": true} {
		if got := isLanguage(in); got != want {
			t.Errorf("isLanguage(%q) = %v", in, got)
		}
	}
	if got := timezoneName("America/Argentina/Buenos_Aires"); got != "Buenos Aires (America/Argentina)" {
		t.Errorf("timezoneName: %q", got)
	}
	got := parseXKBLayouts("! model\n  pc104  Generic\n! layout\n  de   German\n  us   English (US)\n! variant\n  x  de: X\n")
	if want := map[string]string{"de": "German", "us": "English (US)"}; !reflect.DeepEqual(got, want) {
		t.Errorf("layouts: %v", got)
	}
}

// The page finds the id from the name, so two ids never share one.
func TestOneNameHasOneId(t *testing.T) {
	c := SessionChoice{Current: "de_DE.UTF-8", Available: []string{"de_DE.UTF-8", "de_DE.ISO-8859-1", "xx"}}.withNames(languageName)
	want := map[string]string{"de_DE.UTF-8": "Deutsch (DE)"}
	if !reflect.DeepEqual(c.Names, want) {
		t.Errorf("names: %v", c.Names)
	}
}
