//! Image catalog: which bootc images can be installed, and what each one
//! tells the recipe.
//!
//! The contract is `shared/catalog/README.md`; the fixture this reader is
//! held to is `shared/catalog/fixtures/{catalog,expected}.json`
//! (`the_shared_fixture_resolves_as_expected` below). The reference resolver
//! is `shared/catalog/resolve.py`; this module does not import it.
//!
//! - A node is a leaf when it has `imgref`, or `tag` with a `registry` in
//!   scope. Every other node is a group.
//! - A leaf takes each contract field from the nearest node that sets it.
//!   `false`, `""` and `[]` are values and stop the search.
//! - `needs_user_creation` is `true` when no node sets it: an install with
//!   no account and no first-boot setup leaves nobody to sign in as.
//! - A Flatpak list is written only when it resolves offline. This frontend
//!   never downloads a list and never reads `fallback_flatpaks`.

use serde_json::{Map, Value};

/// One installable image: a leaf of the catalog tree, with inherited fields.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ImageLeaf {
    /// The node's own `name` ("Stable" for a tag leaf).
    pub name: String,
    /// Short description (`desc`, or the older `description`).
    pub description: String,
    /// The image updates follow: `imgref`, or `<registry>:<tag>`.
    pub imgref: String,
    /// The `name` of the nearest node that sets `registry`.
    pub product: String,
    /// The `name` of a tag leaf; empty for a leaf with its own `imgref`.
    pub channel: String,
    /// Product and channel: what Confirm and a short list show.
    pub label: String,
    /// Every `name` from the root to the leaf: what a flat list shows,
    /// because `label` is not unique there.
    pub breadcrumb: String,
    /// The image for a machine with an NVIDIA GPU, or "".
    pub nvidia_imgref: String,
    /// `grub2`, `systemd`, or "" for fisherman's default.
    pub bootloader: String,
    /// The recipe's `composeFsBackend`. fisherman does not infer it.
    pub composefs: bool,
    /// The filesystem selected before the user picks one ("" = ours).
    pub filesystem: String,
    /// The filesystems the user may pick (empty = our own list).
    pub filesystems: Vec<String>,
    /// The first value of the hostname field, or "".
    pub default_hostname: String,
    /// `Some` only for a list that resolves offline (`[]` included).
    /// `None` leaves `flatpaks` out of the recipe.
    pub flatpaks: Option<Vec<String>>,
    /// The recipe's `flatpakVarPath`, written only when not empty.
    pub flatpak_var_path: String,
    /// Whether the installer creates the first account.
    pub needs_user_creation: bool,
    /// The recipe's `imageType`, written only when it is not `bootc`.
    pub image_type: String,
    /// The `extras` object of the nearest node that has one, or `None`:
    /// then the recipe has no `extras` key.
    pub extras: Option<crate::model::Extras>,
    /// Per-image tour slides (`carousel`). Page only.
    pub carousel: Vec<Value>,
    /// Extra words the search box matches (`search_extra`). Page only.
    pub search_extra: String,
}

/// The filesystems this frontend offers when the leaf names none.
pub const OWN_FILESYSTEMS: [&str; 3] = ["xfs", "ext4", "btrfs"];

impl ImageLeaf {
    /// What the user may pick: the leaf's list, else its one filesystem,
    /// else this frontend's own list.
    pub fn filesystem_choices(&self) -> Vec<String> {
        if self.filesystems.is_empty() {
            OWN_FILESYSTEMS.iter().map(|f| (*f).to_string()).collect()
        } else {
            self.filesystems.clone()
        }
    }

    /// Whether the search box's query matches this row.
    pub fn matches(&self, query: &str) -> bool {
        let q = query.trim().to_lowercase();
        q.is_empty()
            || [
                &self.breadcrumb,
                &self.imgref,
                &self.description,
                &self.search_extra,
            ]
            .iter()
            .any(|field| field.to_lowercase().contains(&q))
    }
}

/// The ordered list of catalog files (`shared/catalog/README.md`, "Where
/// the catalog is"). `<etc>` is `/run/host/etc` in a Flatpak: the sandbox
/// has its own `/etc`. The system file is first, so a file in a home
/// directory cannot replace the catalog an ISO ships.
pub fn search_paths(in_flatpak: bool, xdg_config_home: &str, bundled: &[&str]) -> Vec<String> {
    let etc = if in_flatpak { "/run/host/etc" } else { "/etc" };
    let mut paths = vec![
        format!("{etc}/bootc-installer/images.json"),
        format!("{etc}/tuna-installer/images.json"),
        format!(
            "{}/bootc-installer/images.json",
            xdg_config_home.trim_end_matches('/')
        ),
    ];
    paths.extend(bundled.iter().map(|p| (*p).to_string()));
    paths
}

/// The file of a test harness or an operator (`shared/catalog/README.md`,
/// "The override for a test or an operator"): tried before the system
/// file, and a missing or broken one does not stop the search.
pub const OVERRIDE_ENV: &str = "FISHERMAN_IMAGES_PATH";

/// [`search_paths`] with the [`OVERRIDE_ENV`] file in front when it names
/// one. An empty value is no override.
pub fn search_paths_with(
    override_path: &str,
    in_flatpak: bool,
    xdg_config_home: &str,
    bundled: &[&str],
) -> Vec<String> {
    let mut paths = Vec::new();
    if !override_path.is_empty() {
        paths.push(override_path.to_string());
    }
    paths.extend(search_paths(in_flatpak, xdg_config_home, bundled));
    paths
}

/// The catalog in the package: the Flatpak's copy, then a native install's.
pub const BUNDLED: [&str; 2] = [
    "/app/share/fisherman/data/images.json",
    "/usr/share/fisherman/data/images.json",
];

/// `<etc>` for this process.
pub fn etc_dir() -> &'static str {
    if std::path::Path::new("/.flatpak-info").exists() {
        "/run/host/etc"
    } else {
        "/etc"
    }
}

/// [`search_paths_with`] for this process: the [`OVERRIDE_ENV`] file
/// first, when it names one. An empty `XDG_CONFIG_HOME` means
/// `$HOME/.config`.
pub fn manifest_paths() -> Vec<String> {
    let config_home = std::env::var("XDG_CONFIG_HOME")
        .ok()
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| format!("{}/.config", std::env::var("HOME").unwrap_or_default()));
    search_paths_with(
        &std::env::var(OVERRIDE_ENV).unwrap_or_default(),
        std::path::Path::new("/.flatpak-info").exists(),
        &config_home,
        &BUNDLED,
    )
}

/// Replace `@alias` strings with values from the catalog's `aliases` table.
/// Runs once at load time. An unknown alias stays a string, and a string is
/// not a Flatpak list.
fn resolve_aliases(value: &mut Value, aliases: &Map<String, Value>) {
    match value {
        Value::String(s) if s.starts_with('@') => {
            if let Some(replacement) = aliases.get(&s[1..]) {
                *value = replacement.clone();
            }
        }
        Value::Array(items) => {
            for item in items {
                resolve_aliases(item, aliases);
            }
        }
        Value::Object(map) => {
            for (_, v) in map.iter_mut() {
                resolve_aliases(v, aliases);
            }
        }
        _ => {}
    }
}

/// The inherited fields at one point of the tree.
#[derive(Debug, Clone)]
struct Context {
    registry: String,
    nvidia_imgref: String,
    bootloader: String,
    composefs: bool,
    filesystem: String,
    filesystems: Vec<String>,
    default_hostname: String,
    /// The raw value after alias resolution: a list, a URL, an unknown
    /// alias, or nothing.
    flatpaks: Option<Value>,
    flatpak_var_path: String,
    needs_user_creation: bool,
    image_type: String,
    /// The raw `extras` object of the nearest node that has one.
    extras: Option<Value>,
    carousel: Vec<Value>,
}

impl Default for Context {
    fn default() -> Self {
        Self {
            registry: String::new(),
            nvidia_imgref: String::new(),
            bootloader: String::new(),
            composefs: false,
            filesystem: String::new(),
            filesystems: Vec::new(),
            default_hostname: String::new(),
            flatpaks: None,
            flatpak_var_path: String::new(),
            // The contract's default: the installer creates an account.
            needs_user_creation: true,
            image_type: "bootc".into(),
            extras: None,
            carousel: Vec::new(),
        }
    }
}

fn string_list(value: &Value) -> Option<Vec<String>> {
    value
        .as_array()?
        .iter()
        .map(|v| v.as_str().map(str::to_string))
        .collect()
}

impl Context {
    /// This context with the fields `node` sets. A `null` sets nothing.
    fn with(&self, node: &Map<String, Value>) -> Self {
        let mut ctx = self.clone();
        let text = |key: &str, slot: &mut String| {
            if let Some(v) = node.get(key).and_then(Value::as_str) {
                *slot = v.to_string();
            }
        };
        text("registry", &mut ctx.registry);
        text("nvidia_imgref", &mut ctx.nvidia_imgref);
        text("bootloader", &mut ctx.bootloader);
        text("filesystem", &mut ctx.filesystem);
        text("default_hostname", &mut ctx.default_hostname);
        text("flatpak_var_path", &mut ctx.flatpak_var_path);
        text("image_type", &mut ctx.image_type);
        if let Some(v) = node.get("composefs").and_then(Value::as_bool) {
            ctx.composefs = v;
        }
        if let Some(v) = node.get("needs_user_creation").and_then(Value::as_bool) {
            ctx.needs_user_creation = v;
        }
        if let Some(v) = node.get("filesystems").and_then(string_list) {
            ctx.filesystems = v;
        }
        if let Some(v) = node.get("carousel").and_then(Value::as_array) {
            ctx.carousel = v.clone();
        }
        match node.get("flatpaks") {
            None | Some(Value::Null) => {}
            Some(v) => ctx.flatpaks = Some(v.clone()),
        }
        // The nearest object replaces the parent's whole: no merge.
        match node.get("extras") {
            None | Some(Value::Null) => {}
            Some(v) => ctx.extras = Some(v.clone()),
        }
        ctx
    }

    /// The four switches of the `extras` object. Only those keys are read
    /// (fisherman refuses a recipe key that it does not know); an object
    /// with a switch that is not a boolean is not used.
    fn extras(&self) -> Option<crate::model::Extras> {
        let object = self.extras.as_ref()?.as_object()?;
        let switch = |key: &str| match object.get(key) {
            None => Some(false),
            Some(v) => v.as_bool(),
        };
        Some(crate::model::Extras {
            print_services: switch("printServices")?,
            oem_setup: switch("oemSetup")?,
            audio_names: switch("audioNames")?,
            boot_splash: switch("bootSplash")?,
        })
    }

    /// The Flatpak list, when it can be read without the network: a list
    /// of application ids. A URL, an unknown alias and no value are `None`.
    fn offline_flatpaks(&self) -> Option<Vec<String>> {
        self.flatpaks.as_ref().and_then(string_list)
    }
}

/// "atlas-dx" of `registry.example/os/atlas-dx:latest`, as a name.
fn pretty_from_imgref(imgref: &str) -> String {
    let slug = imgref.rsplit('/').next().unwrap_or(imgref);
    let slug = slug.split('@').next().unwrap_or(slug);
    let slug = slug.split(':').next().unwrap_or(slug);
    let parts: Vec<String> = slug
        .replace('_', "-")
        .split('-')
        .filter(|p| !p.is_empty())
        .enumerate()
        .map(|(i, p)| {
            if i == 0 {
                let mut chars = p.chars();
                chars
                    .next()
                    .map(|c| c.to_uppercase().collect::<String>() + chars.as_str())
                    .unwrap_or_default()
            } else {
                p.to_uppercase()
            }
        })
        .collect();
    if parts.is_empty() {
        imgref.to_string()
    } else {
        parts.join(" ")
    }
}

fn node_name(node: &Map<String, Value>) -> String {
    node.get("name")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string()
}

fn walk(nodes: &[Value], inherited: &Context, product: &str, path: &[String], out: &mut Vec<ImageLeaf>) {
    for node in nodes {
        let Some(obj) = node.as_object() else { continue };
        let ctx = inherited.with(obj);
        let name = node_name(obj);
        let mut here = path.to_vec();
        if !name.is_empty() {
            here.push(name.clone());
        }
        // The product is the name of the nearest node that sets a registry:
        // a tag leaf's own name is a channel ("Stable").
        let owns_registry = obj
            .get("registry")
            .and_then(Value::as_str)
            .is_some_and(|r| !r.is_empty());
        let node_product = if owns_registry { name.clone() } else { product.to_string() };

        let own = obj.get("imgref").and_then(Value::as_str).unwrap_or("");
        let tag = obj.get("tag").and_then(Value::as_str).unwrap_or("");
        let (imgref, product, channel) = if !own.is_empty() {
            let product = if name.is_empty() { pretty_from_imgref(own) } else { name.clone() };
            (own.to_string(), product, String::new())
        } else if !tag.is_empty() && !ctx.registry.is_empty() {
            let imgref = format!("{}:{tag}", ctx.registry);
            // A tag leaf that sets its own registry is its own product.
            let channel = if owns_registry { String::new() } else { name.clone() };
            let product = if node_product.is_empty() {
                pretty_from_imgref(&imgref)
            } else {
                node_product.clone()
            };
            (imgref, product, channel)
        } else {
            if let Some(children) = obj.get("children").and_then(Value::as_array) {
                walk(children, &ctx, &node_product, &here, out);
            }
            continue;
        };

        let filesystems = if !ctx.filesystems.is_empty() {
            ctx.filesystems.clone()
        } else if !ctx.filesystem.is_empty() {
            vec![ctx.filesystem.clone()]
        } else {
            Vec::new()
        };
        let filesystem = if !ctx.filesystem.is_empty() {
            ctx.filesystem.clone()
        } else {
            ctx.filesystems.first().cloned().unwrap_or_default()
        };
        let text = |key: &str| {
            obj.get(key)
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string()
        };
        let description = match text("desc") {
            d if d.is_empty() => text("description"),
            d => d,
        };
        out.push(ImageLeaf {
            label: format!("{product} {channel}").trim().to_string(),
            breadcrumb: here.join(" \u{203a} "),
            name,
            description,
            imgref,
            product,
            channel,
            nvidia_imgref: ctx.nvidia_imgref.clone(),
            bootloader: ctx.bootloader.clone(),
            composefs: ctx.composefs,
            filesystem,
            filesystems,
            default_hostname: ctx.default_hostname.clone(),
            flatpaks: ctx.offline_flatpaks(),
            flatpak_var_path: ctx.flatpak_var_path.clone(),
            needs_user_creation: ctx.needs_user_creation,
            image_type: ctx.image_type.clone(),
            extras: ctx.extras(),
            carousel: ctx.carousel.clone(),
            search_extra: text("search_extra"),
        });
    }
}

/// The parsed catalog: the default ref and the selectable leaves in
/// catalog order.
#[derive(Debug, Clone, Default)]
pub struct Catalog {
    pub default_image: String,
    pub leaves: Vec<ImageLeaf>,
}

/// Parse a catalog document. A catalog is a JSON object with an `images`
/// list; anything else is an error, and [`load_catalog`] then tries the
/// next file. Pure: the search order is [`search_paths`].
pub fn parse_manifest(text: &str) -> Result<Catalog, String> {
    let mut root: Value =
        serde_json::from_str(text).map_err(|e| format!("invalid images.json: {e}"))?;
    let aliases = root
        .get("aliases")
        .and_then(|v| v.as_object())
        .cloned()
        .unwrap_or_default();
    resolve_aliases(&mut root, &aliases);
    let Some(images) = root.get("images").and_then(Value::as_array) else {
        return Err("a catalog is an object with an `images` list".into());
    };
    let default_image = root
        .get("default_image")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let mut leaves = Vec::new();
    walk(images, &Context::default(), "", &[], &mut leaves);
    Ok(Catalog {
        default_image,
        leaves,
    })
}

/// Load the first file of `paths` that is a catalog. A file that is missing
/// or that does not parse does not stop the search.
pub fn load_first(paths: &[String]) -> Option<Catalog> {
    for path in paths {
        let Ok(text) = std::fs::read_to_string(path) else {
            continue;
        };
        match parse_manifest(&text) {
            Ok(catalog) => return Some(catalog),
            Err(e) => tracing::warn!("ignoring unparsable catalog {path}: {e}"),
        }
    }
    None
}

/// The catalog for this process, or `None` when no file on the search path
/// is one. The wizard then offers only the custom image row.
pub fn load_catalog() -> Option<Catalog> {
    load_first(&manifest_paths())
}

/// The image and the update target for a leaf on this machine
/// (`shared/catalog/README.md`, "Image and NVIDIA image").
pub fn source_and_target(
    leaf: &ImageLeaf,
    has_nvidia: bool,
    is_live: bool,
    offline_images: &[String],
) -> (String, String) {
    let (base, nvidia) = (&leaf.imgref, &leaf.nvidia_imgref);
    if nvidia.is_empty() {
        return (base.clone(), base.clone());
    }
    if has_nvidia {
        return (nvidia.clone(), nvidia.clone());
    }
    if is_live && offline_images.contains(nvidia) && !offline_images.contains(base) {
        // Only the NVIDIA image is on the media. Install it without a
        // download; the first update moves the system to the base image.
        return (nvidia.clone(), base.clone());
    }
    (base.clone(), base.clone())
}

/// The leaf "install this system" applies on live media: the catalog's leaf
/// for the running image (`live`), with the layout the ISO builder probed
/// from that image written over it. The operator recipe's (`<etc>/bootc-
/// installer/recipe.json`) `bootloader`, `composeFsBackend` and
/// `filesystem` win when set, an explicit `false` included; a key that is
/// missing, empty or of the wrong type keeps the leaf's value. A
/// `filesystem` is then the one choice. With no catalog leaf the running
/// image is its own update target. `None` when neither says anything: the
/// image is unlisted.
///
/// No tunaOS ISO ships a catalog, and fisherman's packaged one has no
/// grouper leaf, so composefs-native grouper went down bootc's ostree path
/// and fisherman exited 1 in "Installing OS" (tuna-os/tunaOS#4485). Same fix
/// as KDE (#354) and XFCE (#343, #347).
pub fn live_leaf(
    catalog_leaf: Option<&ImageLeaf>,
    live: &str,
    operator_recipe: Option<&Value>,
) -> Option<ImageLeaf> {
    let recipe = operator_recipe.and_then(Value::as_object);
    let text = |key: &str| {
        recipe
            .and_then(|r| r.get(key))
            .and_then(Value::as_str)
            .filter(|v| !v.is_empty())
            .map(str::to_string)
    };
    let bootloader = text("bootloader");
    let filesystem = text("filesystem");
    let composefs = recipe.and_then(|r| r.get("composeFsBackend")).and_then(Value::as_bool);
    if catalog_leaf.is_none() && bootloader.is_none() && filesystem.is_none() && composefs.is_none() {
        return None;
    }
    let mut leaf = catalog_leaf.cloned().unwrap_or_else(|| ImageLeaf {
        imgref: live.to_string(),
        ..ImageLeaf::default()
    });
    if let Some(bootloader) = bootloader {
        leaf.bootloader = bootloader;
    }
    if let Some(composefs) = composefs {
        leaf.composefs = composefs;
    }
    if let Some(filesystem) = filesystem {
        leaf.filesystems = vec![filesystem.clone()];
        leaf.filesystem = filesystem;
    }
    Some(leaf)
}

impl Catalog {
    /// The leaf for an image reference. The NVIDIA variant of a leaf is
    /// that leaf.
    pub fn find(&self, imgref: &str) -> Option<usize> {
        if imgref.is_empty() {
            return None;
        }
        self.leaves
            .iter()
            .position(|l| l.imgref == imgref)
            .or_else(|| self.leaves.iter().position(|l| l.nvidia_imgref == imgref))
    }

    /// The leaf selected at the start: the branding's `default_image`,
    /// then the catalog's, else nothing. Never the first row: with nothing
    /// selected the user must choose before the next page opens.
    pub fn default_index(&self, branding_default_image: &str) -> Option<usize> {
        [branding_default_image, self.default_image.as_str()]
            .iter()
            .filter(|candidate| !candidate.is_empty())
            .find_map(|candidate| self.leaves.iter().position(|l| l.imgref == *candidate))
    }

    /// Whether the install of `imgref` creates an account. An image the
    /// catalog does not have needs one.
    pub fn needs_user_creation(&self, imgref: &str) -> bool {
        self.find(imgref)
            .map_or(true, |i| self.leaves[i].needs_user_creation)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Machine, Recipe};

    const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../shared/catalog/fixtures");

    fn fixture(name: &str) -> String {
        std::fs::read_to_string(format!("{FIXTURES}/{name}")).unwrap_or_else(|e| panic!("{name}: {e}"))
    }

    fn strings(value: &Value) -> Vec<String> {
        string_list(value).unwrap_or_else(|| panic!("not a list of strings: {value}"))
    }

    /// A missing key and these values mean the same thing to fisherman.
    fn empty_value(key: &str) -> Option<Value> {
        match key {
            "bootloader" => Some(Value::String(String::new())),
            "composeFsBackend" => Some(Value::Bool(false)),
            "imageType" => Some(Value::String("bootc".into())),
            _ => None,
        }
    }

    /// The contract test: `shared/catalog/fixtures/catalog.json` through
    /// this frontend's parser and recipe builder gives
    /// `shared/catalog/fixtures/expected.json`. Every leaf, every resolved
    /// field, and for each machine case every recipe key that must be
    /// there and every key that must not.
    #[test]
    fn the_shared_fixture_resolves_as_expected() {
        let catalog = parse_manifest(&fixture("catalog.json")).unwrap();
        let expected: Value = serde_json::from_str(&fixture("expected.json")).unwrap();
        assert_eq!(expected["contract_version"], 1);
        let leaves = expected["leaves"].as_array().unwrap();
        assert_eq!(
            catalog.leaves.iter().map(|l| l.imgref.clone()).collect::<Vec<_>>(),
            leaves.iter().map(|l| l["imgref"].as_str().unwrap().to_string()).collect::<Vec<_>>(),
            "the leaves, in catalog order"
        );
        let mut cases = 0;
        for (leaf, want) in catalog.leaves.iter().zip(leaves) {
            let w = &want["leaf"];
            let name = &leaf.imgref;
            assert_eq!(leaf.name, w["name"], "{name}: name");
            assert_eq!(leaf.product, w["product"], "{name}: product");
            assert_eq!(leaf.channel, w["channel"], "{name}: channel");
            assert_eq!(leaf.label, w["label"], "{name}: label");
            assert_eq!(leaf.breadcrumb, w["breadcrumb"], "{name}: breadcrumb");
            assert_eq!(leaf.nvidia_imgref, w["nvidia_imgref"], "{name}: nvidia_imgref");
            assert_eq!(leaf.bootloader, w["bootloader"], "{name}: bootloader");
            assert_eq!(leaf.composefs, w["composefs"], "{name}: composefs");
            assert_eq!(leaf.filesystem, w["filesystem"], "{name}: filesystem");
            assert_eq!(leaf.filesystems, strings(&w["filesystems"]), "{name}: filesystems");
            assert_eq!(leaf.default_hostname, w["default_hostname"], "{name}: default_hostname");
            assert_eq!(leaf.flatpak_var_path, w["flatpak_var_path"], "{name}: flatpak_var_path");
            assert_eq!(leaf.needs_user_creation, w["needs_user_creation"], "{name}: needs_user_creation");
            assert_eq!(leaf.image_type, w["image_type"], "{name}: image_type");
            let want_flatpaks = (!w["flatpaks"].is_null()).then(|| strings(&w["flatpaks"]));
            assert_eq!(leaf.flatpaks, want_flatpaks, "{name}: flatpaks");
            let want_extras = (!w["extras"].is_null())
                .then(|| serde_json::from_value::<crate::model::Extras>(w["extras"].clone()).unwrap());
            assert_eq!(leaf.extras, want_extras, "{name}: extras");

            for case in want["cases"].as_array().unwrap() {
                cases += 1;
                let inputs = &case["inputs"];
                let machine = Machine {
                    has_nvidia: inputs["has_nvidia"].as_bool().unwrap(),
                    is_live: inputs["is_live"].as_bool().unwrap(),
                    offline_images: strings(&inputs["offline_images"]),
                };
                // The user selects the leaf and changes nothing.
                let mut recipe = Recipe::default();
                recipe.apply_leaf(leaf, &machine);
                let json = serde_json::to_value(&recipe).unwrap();
                for (key, value) in case["recipe"].as_object().unwrap() {
                    let got = json.get(key).cloned().or_else(|| empty_value(key));
                    assert_eq!(got.as_ref(), Some(value), "{name} {inputs}: {key}");
                }
                for key in strings(&case["absent"]) {
                    assert!(json.get(&key).is_none(), "{name} {inputs}: {key} must be left out");
                }
            }
        }
        assert!(cases > leaves.len(), "the NVIDIA cases were not read");
    }

    #[test]
    fn the_search_path_is_the_shared_one() {
        let expected: Value = serde_json::from_str(&fixture("expected.json")).unwrap();
        let rows = expected["search_paths"].as_array().unwrap();
        assert_eq!(rows.len(), 2);
        for row in rows {
            assert_eq!(
                search_paths(
                    row["in_flatpak"].as_bool().unwrap(),
                    row["xdg_config_home"].as_str().unwrap(),
                    &["<bundled>"],
                ),
                strings(&row["paths"]),
                "{row}"
            );
        }
        // This process: the system file first, the package last.
        if std::env::var_os(OVERRIDE_ENV).is_some() {
            return;
        }
        let paths = manifest_paths();
        assert_eq!(paths[0], "/etc/bootc-installer/images.json");
        assert_eq!(paths[1], "/etc/tuna-installer/images.json");
        assert!(paths[2].ends_with("/bootc-installer/images.json"));
        assert_eq!(paths[3..], BUNDLED.map(String::from));
    }

    #[test]
    fn the_override_is_the_shared_one() {
        // FISHERMAN_IMAGES_PATH, for each case of expected.json: its file
        // first when it names one, then the search path as without it.
        let expected: Value = serde_json::from_str(&fixture("expected.json")).unwrap();
        let over = &expected["override"];
        assert_eq!(over["env"], OVERRIDE_ENV);
        let cases = over["cases"].as_array().unwrap();
        assert!(cases.len() >= 3);
        for case in cases {
            assert_eq!(
                search_paths_with(
                    case["value"].as_str().unwrap(),
                    case["in_flatpak"].as_bool().unwrap(),
                    case["xdg_config_home"].as_str().unwrap(),
                    &["<bundled>"],
                ),
                strings(&case["paths"]),
                "{case}"
            );
        }
        // A missing override file does not stop the search; a catalog is
        // read from it.
        let dir = std::env::temp_dir().join(format!("cosmic-override-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let good = dir.join("images.json");
        std::fs::write(&good, fixture("catalog.json")).unwrap();
        let missing = dir.join("absent.json").display().to_string();
        let paths = search_paths_with(&missing, false, "/nonexistent", &[good.to_str().unwrap()]);
        assert_eq!(paths[0], missing);
        assert!(load_first(&paths).is_some());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_default_selection_is_the_shared_one() {
        let text = fixture("catalog.json");
        let with_default = parse_manifest(&text).unwrap();
        let mut root: Value = serde_json::from_str(&text).unwrap();
        root.as_object_mut().unwrap().remove("default_image");
        let without_default = parse_manifest(&root.to_string()).unwrap();
        let expected: Value = serde_json::from_str(&fixture("expected.json")).unwrap();
        let rows = expected["default_selection"].as_array().unwrap();
        assert!(rows.len() >= 6);
        for row in rows {
            // An empty catalog_default_image is the fixture without the key.
            let catalog = if row["catalog_default_image"] == "" {
                &without_default
            } else {
                &with_default
            };
            let selected = catalog
                .default_index(row["branding_default_image"].as_str().unwrap())
                .map(|i| catalog.leaves[i].imgref.clone());
            assert_eq!(
                selected.map(Value::String).unwrap_or(Value::Null),
                row["selected"],
                "{row}"
            );
        }
        // Never the first row: no default anywhere selects nothing.
        assert_eq!(without_default.default_index(""), None);
    }

    #[test]
    fn an_image_the_catalog_does_not_have_needs_an_account() {
        let catalog = parse_manifest(&fixture("catalog.json")).unwrap();
        let expected: Value = serde_json::from_str(&fixture("expected.json")).unwrap();
        let unknown = &expected["unknown_image"];
        assert_eq!(
            catalog.needs_user_creation(unknown["imgref"].as_str().unwrap()),
            unknown["needs_user_creation"]
        );
        assert!(Catalog::default().needs_user_creation("registry.example/os/any:1"));
        // The NVIDIA variant of a leaf is that leaf (the image live media
        // booted can be it).
        assert!(!catalog.needs_user_creation("registry.example/os/boreal-nvidia:latest"));
    }

    /// #286: a composefs leaf reaches the recipe with its boot stack and a
    /// filesystem fisherman accepts, and ext4 is offered where the leaf
    /// allows it.
    #[test]
    fn a_composefs_leaf_reaches_the_recipe() {
        let catalog = parse_manifest(&fixture("catalog.json")).unwrap();
        let boreal = &catalog.leaves[catalog.find("registry.example/os/boreal:latest").unwrap()];
        let mut recipe = Recipe::default();
        assert_eq!(recipe.filesystem, "xfs");
        recipe.apply_leaf(boreal, &Machine::default());
        let json = serde_json::to_value(&recipe).unwrap();
        assert_eq!(json["composeFsBackend"], true);
        assert_eq!(json["bootloader"], "systemd");
        // composefs on xfs is what fisherman rejects; the leaf's own
        // default went in instead of this frontend's.
        assert_eq!(json["filesystem"], "btrfs");
        assert_eq!(json["btrfsSubvolumes"], true);
        assert_eq!(json["targetImgref"], "registry.example/os/boreal:latest");
        assert_eq!(json["flatpakVarPath"], "state/os/default/var");
        assert_eq!(boreal.filesystem_choices(), ["btrfs", "ext4"]);

        // The next leaf's fields replace them: nothing of Boreal is left.
        let stable = &catalog.leaves[catalog.find("registry.example/os/atlas:stable").unwrap()];
        recipe.apply_leaf(stable, &Machine::default());
        let json = serde_json::to_value(&recipe).unwrap();
        assert_eq!(json["bootloader"], "grub2");
        assert!(json.get("composeFsBackend").is_none());
        assert_eq!(json["filesystem"], "xfs");
        assert_eq!(json["btrfsSubvolumes"], false);
        assert!(json.get("flatpakVarPath").is_none());
        assert_eq!(stable.filesystem_choices(), ["xfs"]);

        // A leaf that names no filesystem: this frontend's list, with ext4.
        let cirrus = &catalog.leaves[catalog.find("registry.example/os/cirrus:1").unwrap()];
        assert_eq!(cirrus.filesystem_choices(), ["xfs", "ext4", "btrfs"]);
        recipe.apply_leaf(cirrus, &Machine::default());
        assert_eq!(recipe.filesystem, "xfs");
        assert!(recipe.bootloader.is_empty());
    }

    /// #296: a list that cannot be read offline leaves the key out.
    /// `fallback_flatpaks` is never read, and never sent.
    #[test]
    fn a_flatpak_list_is_written_only_when_it_resolves_offline() {
        let catalog = parse_manifest(&fixture("catalog.json")).unwrap();
        let flatpaks = |imgref: &str| catalog.leaves[catalog.find(imgref).unwrap()].flatpaks.clone();
        // An alias that names a list.
        assert_eq!(
            flatpaks("registry.example/os/atlas:stable"),
            Some(vec!["org.example.Browser".to_string(), "org.example.Editor".to_string()])
        );
        // `[]` is a value: copy nothing.
        assert_eq!(flatpaks("registry.example/os/atlas:beta"), Some(Vec::new()));
        // An alias that names a URL, an alias that does not exist, no value.
        assert_eq!(flatpaks("registry.example/os/atlas-dx:latest"), None);
        assert_eq!(flatpaks("registry.example/os/drift:edge"), None);
        assert_eq!(flatpaks("registry.example/os/cirrus:1"), None);
        for leaf in &catalog.leaves {
            let mut recipe = Recipe::default();
            recipe.apply_leaf(leaf, &Machine::default());
            let text = serde_json::to_string(&recipe).unwrap();
            assert!(!text.contains("org.example.NeverSent"), "{}: {text}", leaf.imgref);
        }
        // A list with an entry that is not an id is not a list.
        let odd = parse_manifest(r#"{"images": [{"name": "A", "imgref": "x:1", "flatpaks": ["a", 7]}]}"#)
            .unwrap();
        assert_eq!(odd.leaves[0].flatpaks, None);
    }

    #[test]
    fn rows_are_found_by_product_reference_or_description() {
        let catalog = parse_manifest(&fixture("catalog.json")).unwrap();
        let found = |q: &str| {
            catalog
                .leaves
                .iter()
                .filter(|l| l.matches(q))
                .map(|l| l.breadcrumb.clone())
                .collect::<Vec<_>>()
        };
        assert_eq!(found("").len(), catalog.leaves.len());
        assert_eq!(found("  ATLAS dx "), ["Atlas \u{203a} Atlas DX \u{203a} Latest"]);
        assert_eq!(found("os/cirrus"), ["Cirrus"]);
        assert_eq!(found("stable channel"), ["Atlas \u{203a} Stable"]);
        assert!(found("no such system").is_empty());
    }

    const MANIFEST: &str = r#"{
        "default_image": "registry.example/os/desktop:stable",
        "aliases": {"stable_tag": "stable"},
        "images": [
            {"name": "Group", "needs_user_creation": false, "children": [
                {"name": "Desktop", "imgref": "registry.example/os/desktop:stable"},
                {"name": "Minimal", "registry": "registry.example/os/minimal", "tag": "@stable_tag",
                 "description": "No frills", "needs_user_creation": true,
                 "carousel": [{"title": "Hi", "description": "Welcome", "image": "a.png"}]}
            ]},
            {"name": "Server", "imgref": "registry.example/os/server:stable"}
        ]
    }"#;

    #[test]
    fn leaves_inherit_needs_user_from_the_nearest_ancestor() {
        let catalog = parse_manifest(MANIFEST).unwrap();
        assert_eq!(catalog.leaves.len(), 3);
        // Inherited from Group.
        assert!(!catalog.leaves[0].needs_user_creation);
        // Overridden on the leaf itself.
        assert!(catalog.leaves[1].needs_user_creation);
        // No node sets it: the contract's default, true (#288). This was
        // false, and such an image got no account from this frontend.
        assert!(catalog.leaves[2].needs_user_creation);
    }

    #[test]
    fn aliases_resolve_before_leaves_are_read() {
        let catalog = parse_manifest(MANIFEST).unwrap();
        assert_eq!(catalog.leaves[1].imgref, "registry.example/os/minimal:stable");
        // A tag leaf that sets its own registry is its own product.
        assert_eq!(catalog.leaves[1].label, "Minimal");
    }

    #[test]
    fn only_a_whole_string_is_an_alias() {
        // A string that STARTS WITH @ is an alias; an @ in the middle of a
        // longer value is literal and survives loading.
        let catalog = parse_manifest(
            r#"{"aliases": {"t": "stable"},
                "images": [{"name": "A", "imgref": "x:@t"},
                           {"name": "B", "imgref": "@t"}]}"#,
        )
        .unwrap();
        assert_eq!(catalog.leaves[0].imgref, "x:@t");
        assert_eq!(catalog.leaves[1].imgref, "stable");
    }

    #[test]
    fn carousel_and_description_ride_along() {
        let catalog = parse_manifest(MANIFEST).unwrap();
        assert_eq!(catalog.leaves[1].description, "No frills");
        assert_eq!(catalog.leaves[1].carousel.len(), 1);
        assert!(catalog.leaves[0].carousel.is_empty());
    }

    #[test]
    fn a_tag_leaf_takes_the_registry_in_scope() {
        let catalog = parse_manifest(
            r#"{"images": [{"name": "Old", "registry": "registry.example/os/old",
                            "children": [{"name": "LTS", "tag": "lts"}]},
                           {"name": "No registry", "tag": "lts"}]}"#,
        )
        .unwrap();
        // A tag with no registry in scope is not an image.
        assert_eq!(catalog.leaves.len(), 1);
        assert_eq!(catalog.leaves[0].imgref, "registry.example/os/old:lts");
        assert_eq!(catalog.leaves[0].label, "Old LTS");
    }

    #[test]
    fn garbage_is_an_error_not_a_panic() {
        assert!(parse_manifest("not json").is_err());
        // Not a catalog: the search goes on to the next file.
        assert!(parse_manifest(r#"{"images": {}}"#).is_err());
        assert!(parse_manifest("[]").is_err());
        // Nodes that are not objects are skipped.
        assert!(parse_manifest(r#"{"images": [7, "x", null]}"#).unwrap().leaves.is_empty());
    }

    /// A file that is missing or that is not a catalog does not stop the
    /// search. It used to: the first missing path ended it, so only a
    /// catalog at the first path was ever read.
    #[test]
    fn the_first_file_that_is_a_catalog_is_used() {
        let dir = tempfile::tempdir().unwrap();
        let path = |name: &str| dir.path().join(name).to_string_lossy().into_owned();
        std::fs::write(path("broken.json"), "not json").unwrap();
        std::fs::write(path("list.json"), "[]").unwrap();
        std::fs::write(path("good.json"), MANIFEST).unwrap();
        std::fs::write(
            path("later.json"),
            r#"{"images": [{"name": "Later", "imgref": "x:1"}]}"#,
        )
        .unwrap();
        let paths = ["missing.json", "broken.json", "list.json", "good.json", "later.json"].map(path);
        let catalog = load_first(&paths).expect("a catalog");
        assert_eq!(catalog.leaves.len(), 3);
        assert_eq!(catalog.default_image, "registry.example/os/desktop:stable");
        assert!(load_first(&paths[..3]).is_none());
    }

    #[test]
    fn live_leaf_takes_the_operator_layout() {
        let live = "ghcr.io/tuna-os/grouper:cosmic";
        // The grouper ISO's recipe (tunaOS#4485): no catalog leaf at all.
        let grouper = serde_json::json!({
            "bootloader": "systemd", "composeFsBackend": true, "user": {"groups": ["sudo"]}
        });
        let leaf = live_leaf(None, live, Some(&grouper)).unwrap();
        assert_eq!((leaf.bootloader.as_str(), leaf.composefs), ("systemd", true));
        assert_eq!(leaf.imgref, live, "the running image is its own update target");
        let mut recipe = Recipe::default();
        recipe.apply_leaf(&leaf, &Machine { is_live: true, ..Machine::default() });
        let json = serde_json::to_value(&recipe).unwrap();
        assert_eq!(json["bootloader"], "systemd");
        assert_eq!(json["composeFsBackend"], true);
        assert_eq!(recipe.target_imgref, live);

        // Over a catalog leaf: a set key wins, an explicit false included;
        // a missing, empty or mistyped one keeps the leaf's value.
        let catalog_leaf = ImageLeaf {
            imgref: live.into(),
            label: "Grouper COSMIC".into(),
            bootloader: "grub2".into(),
            composefs: true,
            filesystem: "btrfs".into(),
            filesystems: vec!["btrfs".into(), "xfs".into()],
            ..ImageLeaf::default()
        };
        let operator = serde_json::json!({"bootloader": "", "composeFsBackend": false, "filesystem": "ext4"});
        let leaf = live_leaf(Some(&catalog_leaf), live, Some(&operator)).unwrap();
        assert_eq!(leaf.bootloader, "grub2");
        assert!(!leaf.composefs);
        assert_eq!((leaf.filesystem.as_str(), leaf.filesystems.clone()), ("ext4", vec!["ext4".to_string()]));
        assert_eq!(leaf.label, "Grouper COSMIC");
        let mistyped = serde_json::json!({"bootloader": 1, "composeFsBackend": "yes", "filesystem": null});
        assert_eq!(live_leaf(Some(&catalog_leaf), live, Some(&mistyped)).unwrap(), catalog_leaf);

        // Neither a leaf nor a layout: the image stays unlisted.
        assert_eq!(live_leaf(None, live, None), None);
        assert_eq!(live_leaf(None, live, Some(&serde_json::json!({"user": {}}))), None);
    }
}
