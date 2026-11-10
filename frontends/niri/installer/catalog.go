package main

// Image catalog for the Source step: this backend's reader for the contract
// in shared/catalog/README.md.
//
// A catalog (`images.json`) is a tree of images. `catalog` prints the flat
// leaf list with every inherited field resolved, the leaf that is selected at
// the start, and for each leaf the recipe keys the wizard writes for it on
// THIS machine (`recipe`): the QML copies those keys and adds nothing of its
// own. catalog_test.go holds this file to shared/catalog/fixtures/, the same
// fixture the other four frontends read.
//
// The machine facts the NVIDIA rule needs are the probe's (live media and
// the offline images) and a PCI scan for the GPU. A probe that fails is "not
// live, nothing offline", so the command still answers with no fisherman.

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// imagesPathEnv puts one file in front of the search path, for the tests and
// the end-to-end driver. It is a per-run switch, not a place a product ships
// a catalog: that is <etc>/bootc-installer/images.json.
const imagesPathEnv = "FISHERMAN_IMAGES_PATH"

// bundledCatalogs is where the package keeps fisherman's catalog: the
// Flatpak's copy, then a native install's.
var bundledCatalogs = []string{
	"/app/share/fisherman/data/images.json",
	"/usr/share/fisherman/data/images.json",
}

// hostEtc is the host's /etc: below /run/host in a Flatpak, where the
// sandbox has an /etc of its own (--filesystem=host).
func hostEtc(flatpak bool) string {
	if flatpak {
		return "/run/host/etc"
	}
	return "/etc"
}

// catalogSearchPaths is the contract's ordered list: the system file, its
// legacy name, the user's file, then the bundled catalog(s).
func catalogSearchPaths(flatpak bool, xdgConfigHome string, bundled ...string) []string {
	etc := hostEtc(flatpak)
	paths := []string{
		etc + "/bootc-installer/images.json",
		etc + "/tuna-installer/images.json",
		strings.TrimRight(xdgConfigHome, "/") + "/bootc-installer/images.json",
	}
	return append(paths, bundled...)
}

// xdgConfigHome is $XDG_CONFIG_HOME, else $HOME/.config.
func xdgConfigHome() string {
	if dir := os.Getenv("XDG_CONFIG_HOME"); dir != "" {
		return dir
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".config")
}

// catalogPaths is the search path of this process.
func catalogPaths() []string {
	paths := []string{}
	if p := os.Getenv(imagesPathEnv); p != "" {
		paths = append(paths, p)
	}
	return append(paths, catalogSearchPaths(inFlatpak(), xdgConfigHome(), bundledCatalogs...)...)
}

// CatalogLeaf is one installable image with every inherited field resolved,
// in the shape of `leaf` in shared/catalog/fixtures/expected.json plus what
// only the page shows (desc, carousel) and the recipe keys for this machine.
type CatalogLeaf struct {
	Imgref            string          `json:"imgref"`
	Name              string          `json:"name"`
	Desc              string          `json:"desc"`
	Product           string          `json:"product"`
	Channel           string          `json:"channel"`
	Label             string          `json:"label"`
	Path              []string        `json:"path"`
	Breadcrumb        string          `json:"breadcrumb"`
	NvidiaImgref      string          `json:"nvidia_imgref"`
	Bootloader        string          `json:"bootloader"`
	Composefs         bool            `json:"composefs"`
	Filesystem        string          `json:"filesystem"`
	Filesystems       []string        `json:"filesystems"`
	DefaultHostname   string          `json:"default_hostname"`
	Flatpaks          *[]string       `json:"flatpaks"` // null: leave the recipe key out
	FlatpaksURL       string          `json:"flatpaks_url"`
	FlatpakVarPath    string          `json:"flatpak_var_path"`
	NeedsUserCreation bool            `json:"needs_user_creation"`
	ImageType         string          `json:"image_type"`
	Extras            *Extras         `json:"extras"` // null: leave the recipe key out
	Carousel          []CarouselSlide `json:"carousel"`
	// Recipe is recipeFragment for the machine `catalog` ran on.
	Recipe map[string]any `json:"recipe"`
}

// Extras is the catalog's `extras` object and the recipe's: the desktop
// steps fisherman does after the install (shared/catalog/README.md, "Desktop
// extras"). Each switch is written, so `{}` in a catalog is four times false
// and is not the same as no object.
type Extras struct {
	PrintServices bool `json:"printServices"`
	OEMSetup      bool `json:"oemSetup"`
	AudioNames    bool `json:"audioNames"`
	BootSplash    bool `json:"bootSplash"`
}

// parseExtras reads a node's `extras`. Only the four switches are read: a
// key that fisherman does not know must not reach the recipe. An object
// with a switch that is not a boolean is not used.
func parseExtras(v any) (*Extras, bool) {
	object, ok := v.(map[string]any)
	if !ok {
		return nil, false
	}
	var extras Extras
	for key, into := range map[string]*bool{
		"printServices": &extras.PrintServices, "oemSetup": &extras.OEMSetup,
		"audioNames": &extras.AudioNames, "bootSplash": &extras.BootSplash,
	} {
		value, present := object[key]
		if !present {
			continue
		}
		on, isBool := value.(bool)
		if !isBool {
			return nil, false
		}
		*into = on
	}
	return &extras, true
}

// CarouselSlide is one tour slide from a leaf's "carousel" list. Keys beyond
// these three are ignored; a slide the QML cannot render (no title and no
// description and no image) is dropped.
type CarouselSlide struct {
	Title       string `json:"title"`
	Description string `json:"description"`
	Image       string `json:"image"`
}

// Catalog is one loaded catalog file.
type Catalog struct {
	DefaultImage string
	Leaves       []CatalogLeaf
}

// catalogContext is what a node hands down to its children: each inherited
// key with the value of the nearest node that sets it. A value of false, ""
// or [] is a value and stops the search; only a missing key (or null) does
// not.
type catalogContext struct {
	registry        string
	nvidiaImgref    string
	bootloader      string
	composefs       bool
	filesystem      string
	filesystems     []string
	defaultHostname string
	flatpaks        any // nil: no node set it
	flatpakVarPath  string
	needsUser       bool
	imageType       string
	extras          *Extras // nil: no node set it
	carousel        []any
	desc            string
}

func rootContext() catalogContext {
	// needs_user_creation is true when no node sets it: an install with no
	// account and no first-boot setup leaves nobody to sign in as.
	return catalogContext{needsUser: true, imageType: "bootc", filesystems: []string{}}
}

func stringList(v any) ([]string, bool) {
	items, ok := v.([]any)
	if !ok {
		return nil, false
	}
	out := make([]string, 0, len(items))
	for _, item := range items {
		s, ok := item.(string)
		if !ok {
			return nil, false
		}
		out = append(out, s)
	}
	return out, true
}

// inherit applies the keys `node` sets on top of the parent's context.
func (c catalogContext) inherit(node map[string]any) catalogContext {
	str := func(key string, into *string) {
		if v, ok := node[key].(string); ok {
			*into = v
		}
	}
	boolean := func(key string, into *bool) {
		if v, ok := node[key].(bool); ok {
			*into = v
		}
	}
	str("registry", &c.registry)
	str("nvidia_imgref", &c.nvidiaImgref)
	str("bootloader", &c.bootloader)
	str("filesystem", &c.filesystem)
	str("default_hostname", &c.defaultHostname)
	str("flatpak_var_path", &c.flatpakVarPath)
	str("image_type", &c.imageType)
	str("desc", &c.desc)
	boolean("composefs", &c.composefs)
	boolean("needs_user_creation", &c.needsUser)
	if list, ok := stringList(node["filesystems"]); ok {
		c.filesystems = list
	}
	if v, ok := node["flatpaks"]; ok && v != nil {
		c.flatpaks = v
	}
	if list, ok := node["carousel"].([]any); ok {
		c.carousel = list
	}
	// The nearest object replaces the parent's whole: no merge.
	if v, ok := node["extras"]; ok && v != nil {
		c.extras, _ = parseExtras(v)
	}
	return c
}

// resolveFlatpaks is the offline rule: a list is the list, `@name` is the
// list `aliases.name` holds. A URL (direct or through an alias), an alias
// that does not exist and no value are all nil: leave `flatpaks` out of the
// recipe, so fisherman applies its own default. This backend downloads
// nothing and has no list of its own.
func resolveFlatpaks(value any, aliases map[string]any) (list *[]string, url string) {
	if s, ok := value.(string); ok && strings.HasPrefix(s, "@") {
		value = aliases[s[1:]]
	}
	if items, ok := stringList(value); ok {
		return &items, ""
	}
	if s, ok := value.(string); ok && (strings.HasPrefix(s, "http://") || strings.HasPrefix(s, "https://")) {
		return nil, s
	}
	return nil, ""
}

// prettyFromImgref names a leaf that has no name: the last path part of the
// reference, without tag or digest ("registry.example/os/atlas-dx:1" is
// "Atlas DX").
func prettyFromImgref(imgref string) string {
	slug := imgref[strings.LastIndex(imgref, "/")+1:]
	slug, _, _ = strings.Cut(slug, "@")
	slug, _, _ = strings.Cut(slug, ":")
	parts := strings.FieldsFunc(strings.ReplaceAll(slug, "_", "-"), func(r rune) bool { return r == '-' })
	if len(parts) == 0 {
		return imgref
	}
	for i, part := range parts {
		if i == 0 {
			parts[i] = strings.ToUpper(part[:1]) + strings.ToLower(part[1:])
		} else {
			parts[i] = strings.ToUpper(part)
		}
	}
	return strings.Join(parts, " ")
}

// filesystemChoices is what the user may pick; empty means the wizard
// offers its own list.
func filesystemChoices(filesystem string, filesystems []string) []string {
	if len(filesystems) > 0 {
		return append([]string{}, filesystems...)
	}
	if filesystem != "" {
		return []string{filesystem}
	}
	return []string{}
}

// defaultFilesystem is what is selected before the user picks; "" means the
// wizard's own default.
func defaultFilesystem(filesystem string, filesystems []string) string {
	if filesystem != "" {
		return filesystem
	}
	if len(filesystems) > 0 {
		return filesystems[0]
	}
	return ""
}

func nodeName(node map[string]any) string {
	name, _ := node["name"].(string)
	return name
}

// walkCatalog appends every leaf below `nodes`, in catalog order.
func walkCatalog(nodes []any, inherited catalogContext, product string, path []string,
	aliases map[string]any, found *[]CatalogLeaf) {
	for _, raw := range nodes {
		node, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		ctx := inherited.inherit(node)
		name := nodeName(node)
		here := path
		if name != "" {
			here = append(append([]string{}, path...), name)
		}
		// The product is the name of the nearest node that sets a registry:
		// a tag leaf's own name is a channel ("Stable").
		ownRegistry, _ := node["registry"].(string)
		nodeProduct := product
		if ownRegistry != "" {
			nodeProduct = strings.TrimSpace(name)
		}
		ownImgref, _ := node["imgref"].(string)
		tag, hasTag := node["tag"].(string)
		if ownImgref != "" || (hasTag && ctx.registry != "") {
			*found = append(*found, makeLeaf(node, ctx, nodeProduct, ownRegistry != "", ownImgref, tag, here, aliases))
			continue
		}
		children, _ := node["children"].([]any)
		walkCatalog(children, ctx, nodeProduct, here, aliases, found)
	}
}

func makeLeaf(node map[string]any, ctx catalogContext, product string, ownsRegistry bool,
	ownImgref, tag string, path []string, aliases map[string]any) CatalogLeaf {
	name := strings.TrimSpace(nodeName(node))
	imgref, channel := ownImgref, ""
	if ownImgref != "" {
		product = name
		if product == "" {
			product = prettyFromImgref(imgref)
		}
	} else {
		imgref = ctx.registry + ":" + tag
		// A tag leaf that sets its own registry is its own product.
		if !ownsRegistry {
			channel = name
		}
		if product == "" {
			product = prettyFromImgref(imgref)
		}
	}
	flatpaks, flatpaksURL := resolveFlatpaks(ctx.flatpaks, aliases)
	return CatalogLeaf{
		Imgref: imgref, Name: name, Desc: ctx.desc,
		Product: product, Channel: channel,
		Label: strings.TrimSpace(product + " " + channel),
		Path:  append([]string{}, path...), Breadcrumb: strings.Join(path, " › "),
		NvidiaImgref: ctx.nvidiaImgref, Bootloader: ctx.bootloader, Composefs: ctx.composefs,
		Filesystem:        defaultFilesystem(ctx.filesystem, ctx.filesystems),
		Filesystems:       filesystemChoices(ctx.filesystem, ctx.filesystems),
		DefaultHostname:   ctx.defaultHostname,
		Flatpaks:          flatpaks,
		FlatpaksURL:       flatpaksURL,
		FlatpakVarPath:    ctx.flatpakVarPath,
		NeedsUserCreation: ctx.needsUser,
		ImageType:         ctx.imageType,
		Extras:            ctx.extras,
		Carousel:          parseCarousel(ctx.carousel),
	}
}

// parseCatalog reads one catalog file: a JSON object with an `images` list.
func parseCatalog(data []byte) (Catalog, error) {
	var doc map[string]any
	if err := json.Unmarshal(data, &doc); err != nil {
		return Catalog{}, fmt.Errorf("images.json is not valid JSON: %w", err)
	}
	images, ok := doc["images"].([]any)
	if !ok {
		return Catalog{}, fmt.Errorf("images.json is not a catalog: it has no `images` list")
	}
	aliases, _ := doc["aliases"].(map[string]any)
	catalog := Catalog{Leaves: []CatalogLeaf{}}
	catalog.DefaultImage, _ = doc["default_image"].(string)
	walkCatalog(images, rootContext(), "", nil, aliases, &catalog.Leaves)
	return catalog, nil
}

// loadCatalog reads the first file of the search path that is a catalog. A
// file that is missing or that does not parse does not stop the search; it is
// named in `skipped` so the page can say why the next file was used. No
// catalog at all is not an error: the wizard then offers the branding
// default image.
func loadCatalog(paths []string) (catalog Catalog, used string, skipped []string) {
	for _, path := range paths {
		if path == "" {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		parsed, err := parseCatalog(data)
		if err != nil {
			skipped = append(skipped, fmt.Sprintf("%s: %v", path, err))
			continue
		}
		return parsed, path, skipped
	}
	return Catalog{Leaves: []CatalogLeaf{}}, "", skipped
}

func parseCarousel(raw []any) []CarouselSlide {
	out := []CarouselSlide{}
	for _, item := range raw {
		slide, ok := item.(map[string]any)
		if !ok {
			continue
		}
		title, _ := slide["title"].(string)
		description, _ := slide["description"].(string)
		image, _ := slide["image"].(string)
		if image == "" {
			image, _ = slide["resource"].(string)
		}
		if title == "" && description == "" && image == "" {
			continue
		}
		out = append(out, CarouselSlide{Title: title, Description: description, Image: image})
	}
	return out
}

// findLeaf is the leaf for an image reference, or nil. The NVIDIA variant of
// a leaf is that leaf.
func findLeaf(leaves []CatalogLeaf, imgref string) *CatalogLeaf {
	if imgref == "" {
		return nil
	}
	for i := range leaves {
		if leaves[i].Imgref == imgref {
			return &leaves[i]
		}
	}
	for i := range leaves {
		if leaves[i].NvidiaImgref == imgref {
			return &leaves[i]
		}
	}
	return nil
}

// defaultImgref is the leaf selected at the start: the branding's
// default_image, then the catalog's. "" when neither names a leaf: then the
// user must choose, and the wizard never selects the first row.
func defaultImgref(catalog Catalog, brandingDefaultImage string) string {
	for _, candidate := range []string{brandingDefaultImage, catalog.DefaultImage} {
		if candidate == "" {
			continue
		}
		for _, leaf := range catalog.Leaves {
			if leaf.Imgref == candidate {
				return candidate
			}
		}
	}
	return ""
}

// needsUserCreation says whether the install of imgref creates an account.
// An image the catalog does not have needs one.
func needsUserCreation(leaves []CatalogLeaf, imgref string) bool {
	if leaf := findLeaf(leaves, imgref); leaf != nil {
		return leaf.NeedsUserCreation
	}
	return true
}

// Machine is what the NVIDIA rule reads from the computer.
type Machine struct {
	HasNvidia     bool     `json:"has_nvidia"`
	IsLive        bool     `json:"is_live"`
	OfflineImages []string `json:"offline_images"`
}

func contains(list []string, want string) bool {
	for _, item := range list {
		if item == want {
			return true
		}
	}
	return false
}

// sourceAndTarget is the contract's "Image and NVIDIA image" table.
func sourceAndTarget(leaf CatalogLeaf, m Machine) (image, target string) {
	base, nvidia := leaf.Imgref, leaf.NvidiaImgref
	if nvidia == "" {
		return base, base
	}
	if m.HasNvidia {
		return nvidia, nvidia
	}
	if m.IsLive && contains(m.OfflineImages, nvidia) && !contains(m.OfflineImages, base) {
		// Only the NVIDIA image is on the media. Install it with no
		// download; the first update moves the system to the base image.
		return nvidia, base
	}
	return base, base
}

// recipeFragment is the recipe keys the wizard writes for a leaf before the
// user changes anything. A key that is not in the map must not be in the
// recipe: no `flatpaks` when the list cannot be read offline, no
// `flatpakVarPath` when it is empty, no `imageType` for bootc, no `extras`
// when no node of the catalog has the object.
func recipeFragment(leaf CatalogLeaf, m Machine) map[string]any {
	image, target := sourceAndTarget(leaf, m)
	recipe := map[string]any{
		"image":            image,
		"targetImgref":     target,
		"bootloader":       leaf.Bootloader,
		"composeFsBackend": leaf.Composefs,
	}
	if leaf.Filesystem != "" {
		recipe["filesystem"] = leaf.Filesystem
	}
	if leaf.Flatpaks != nil {
		recipe["flatpaks"] = *leaf.Flatpaks
	}
	if leaf.FlatpakVarPath != "" {
		recipe["flatpakVarPath"] = leaf.FlatpakVarPath
	}
	if leaf.ImageType != "bootc" {
		recipe["imageType"] = leaf.ImageType
	}
	if leaf.Extras != nil {
		recipe["extras"] = *leaf.Extras
	}
	return recipe
}

// pciDevices is where the kernel lists PCI devices. The probe does not report
// the GPU; until it does the contract says to look here.
const pciDevices = "/sys/bus/pci/devices"

// hasNvidiaGPU looks for a PCI display device (class 0x03....) with vendor
// 0x10de below dir.
func hasNvidiaGPU(dir string) bool {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return false
	}
	read := func(device, name string) string {
		data, err := os.ReadFile(filepath.Join(dir, device, name))
		if err != nil {
			return ""
		}
		return strings.ToLower(strings.TrimSpace(string(data)))
	}
	for _, entry := range entries {
		if read(entry.Name(), "vendor") == "0x10de" && strings.HasPrefix(read(entry.Name(), "class"), "0x03") {
			return true
		}
	}
	return false
}

// thisMachine gathers the facts for the NVIDIA rule. A failed probe is not
// live media with nothing offline: the base image is then the choice.
func thisMachine() (Machine, ProbeFacts) {
	facts, err := runProbe()
	if err != nil {
		facts = ProbeFacts{OfflineImages: []string{}}
	}
	return Machine{
		HasNvidia:     hasNvidiaGPU(pciDevices),
		IsLive:        facts.IsLive,
		OfflineImages: facts.OfflineImages,
	}, facts
}

// catalogAnswer is what `catalog` prints for the QML Source step.
func catalogAnswer(catalog Catalog, used string, skipped []string, brandingDefaultImage string,
	m Machine, liveImage string) map[string]any {
	for i := range catalog.Leaves {
		catalog.Leaves[i].Recipe = recipeFragment(catalog.Leaves[i], m)
	}
	answer := map[string]any{
		"path":          used,
		"skipped":       append([]string{}, skipped...),
		"default_image": catalog.DefaultImage,
		// The leaf selected at the start, or "": then the user must choose.
		"selected": defaultImgref(catalog, brandingDefaultImage),
		"leaves":   catalog.Leaves,
		"machine":  m,
		// The leaf of the image the live media booted, for its account flag
		// and its install properties; null when the catalog does not have
		// it, and then the install creates an account.
		"live_leaf":                nil,
		"live_needs_user_creation": needsUserCreation(catalog.Leaves, liveImage),
	}
	if leaf := findLeaf(catalog.Leaves, liveImage); leaf != nil {
		answer["live_leaf"] = *leaf
	}
	return answer
}

// catalogMain is the `catalog` subcommand.
func catalogMain() {
	catalog, used, skipped := loadCatalog(catalogPaths())
	for _, reason := range skipped {
		fmt.Fprintf(os.Stderr, "catalog: skipped %s\n", reason)
	}
	machine, facts := thisMachine()
	answer := catalogAnswer(catalog, used, skipped, resolveBranding().DefaultImage, machine, facts.LiveImage)
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(answer); err != nil {
		fmt.Fprintf(os.Stderr, "encode output: %v\n", err)
		os.Exit(1)
	}
}
