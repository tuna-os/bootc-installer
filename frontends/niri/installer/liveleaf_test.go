package main

import "testing"

// marlin:niri (iso-builder strict run 44501081152): no catalog leaf for the
// live image, and the ISO's operator recipe says composeFsBackend=true and
// bootloader=systemd. Falsification: without liveLeaf the recipe had neither
// key and fisherman stopped with "bootupd is required for ostree-based installs".
func TestLiveLeafTakesTheOperatorRecipeLayout(t *testing.T) {
	op := []byte(`{"composeFsBackend": true, "bootloader": "systemd", "filesystem": "btrfs"}`)
	leaf := liveLeaf(nil, "ghcr.io/tuna-os/marlin:niri", op)
	if leaf == nil {
		t.Fatal("no live leaf from an operator recipe with layout keys")
	}
	frag := recipeFragment(*leaf, Machine{OfflineImages: []string{}})
	if frag["composeFsBackend"] != true || frag["bootloader"] != "systemd" || frag["filesystem"] != "btrfs" {
		t.Fatalf("recipe fragment = %v", frag)
	}
	if _, ok := frag["imageType"]; ok {
		t.Fatalf("a bootc live image must not set imageType: %v", frag)
	}
}

func TestLiveLeafExplicitFalseWinsOverTheCatalog(t *testing.T) {
	cat := &CatalogLeaf{Imgref: "x", Composefs: true, Bootloader: "systemd", ImageType: "bootc"}
	leaf := liveLeaf(cat, "x", []byte(`{"composeFsBackend": false}`))
	if leaf.Composefs || leaf.Bootloader != "systemd" {
		t.Fatalf("leaf = %+v", leaf)
	}
	if !cat.Composefs {
		t.Fatal("the catalog leaf itself was modified")
	}
}

func TestLiveLeafNilWhenNothingIsKnown(t *testing.T) {
	if liveLeaf(nil, "x", nil) != nil || liveLeaf(nil, "x", []byte(`{"user":{}}`)) != nil ||
		liveLeaf(nil, "x", []byte(`not json`)) != nil {
		t.Fatal("a live leaf without a catalog leaf or layout keys")
	}
}
