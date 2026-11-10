package main

// The first account's groups (shared/account/README.md).
//
// groups.json is a byte-identical copy of shared/account/groups.json
// (user_test.go fails when the two differ): the default list every frontend
// writes into `user.groups`. fisherman removes each group the image does not
// have, so one list is correct for all images. An ISO builder replaces the
// list with `user.groups` of <etc>/bootc-installer/recipe.json.

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
)

// A copy of shared/account/groups.json: go:embed cannot leave the module.
// `go generate ./...` refreshes it; user_test.go holds the two together.
//
//go:generate cp ../../../shared/account/groups.json groups.json
//go:embed groups.json
var groupsJSON []byte

// sharedGroups is the embedded file's default list and where the operator's
// file is, below <etc>.
func sharedGroups() (defaults []string, overrideFile string) {
	var doc struct {
		DefaultGroups []string `json:"default_groups"`
		Override      struct {
			File string `json:"file"`
		} `json:"override"`
	}
	if err := json.Unmarshal(groupsJSON, &doc); err != nil {
		// The file is compiled in and tested; this cannot happen at run time.
		panic(fmt.Sprintf("groups.json: %v", err))
	}
	return doc.DefaultGroups, doc.Override.File
}

// groupsFrom is the rule: `user.groups` of the operator's recipe replaces
// the default list when it is a list of strings, the empty list included.
// No file, a file that does not parse, and any other value keep the default.
func groupsFrom(operatorRecipe []byte, defaults []string) []string {
	var doc map[string]any
	if operatorRecipe != nil && json.Unmarshal(operatorRecipe, &doc) == nil {
		if user, ok := doc["user"].(map[string]any); ok {
			if groups, ok := stringList(user["groups"]); ok {
				return groups
			}
		}
	}
	return append([]string{}, defaults...)
}

// accountGroups is the groups of the account this machine's install creates.
func accountGroups() []string {
	defaults, file := sharedGroups()
	data, err := os.ReadFile(hostEtc(inFlatpak()) + "/" + file)
	if err != nil {
		data = nil
	}
	return groupsFrom(data, defaults)
}
