//! Fisherman recipe contract and installer domain data.
//!
//! Keeping these types outside the executable shell gives the serialized
//! backend interface one explicit owner shared by orchestration and UI code.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Recipe {
    pub disk: String,
    pub filesystem: String,
    #[serde(default)]
    pub btrfs_subvolumes: bool,
    pub encryption: Encryption,
    /// Empty in live-ISO mode: bootc installs the running container.
    /// `default` is what lets that empty form be read back: it is omitted
    /// on write, so without it a live-ISO recipe cannot be deserialized.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub image: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub target_imgref: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub bootloader: String,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub compose_fs_backend: bool,
    /// `None` leaves the key out and fisherman applies its own default
    /// (it copies the host's Flatpaks). `Some([])` is written as `[]` and
    /// tells fisherman to copy none. So a list this frontend could not
    /// read is `None`, never `[]` (shared/catalog/README.md).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flatpaks: Option<Vec<String>>,
    /// The catalog leaf's `flatpak_var_path`; left out when empty.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub flatpak_var_path: String,
    /// The catalog leaf's `image_type`; left out for `bootc`.
    #[serde(default, skip_serializing_if = "is_bootc")]
    pub image_type: String,
    /// The catalog leaf's `extras`: the desktop steps fisherman does after
    /// the install. `None` leaves the key out, and fisherman looks the image
    /// up in the catalog that it finds; a staged fisherman has none.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extras: Option<Extras>,
    /// The experimental features the user accepted: `zfs` with a zfs
    /// filesystem, which fisherman refuses without it. Set by
    /// [`Recipe::accept_experimental`] before the recipe goes out.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub experimental: Vec<String>,
    /// The language page's pick, `LANG` of the installed system (#292).
    /// Left out until the user picks one: the image keeps its own.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub locale: String,
    /// The keyboard page's pick: an XKB layout (#292).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub keyboard: Option<Keyboard>,
    /// The time zone page's pick, an IANA name (#292).
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub timezone: String,
    /// Embedded OCI stores for offline installs (spec §4B).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub additional_image_stores: Vec<String>,
    #[serde(rename = "distroID")]
    pub distro_id: String,
    #[serde(default = "default_selinux")]
    pub selinux_disabled: bool,
    pub hostname: String,
    /// The account fisherman creates (`user`, shared/recipe/README.md).
    /// Left out when no username was typed: fisherman then creates none.
    /// Built only by [`user_block`], so the groups are always the same.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user: Option<User>,
}

/// The recipe's `extras` (shared/catalog/README.md, "Desktop extras"): the
/// four switches, each written, so `{}` in a catalog is four times false.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Extras {
    #[serde(default)]
    pub print_services: bool,
    #[serde(default, rename = "oemSetup")]
    pub oem_setup: bool,
    #[serde(default)]
    pub audio_names: bool,
    #[serde(default)]
    pub boot_splash: bool,
}

/// The recipe's `keyboard` block: XKB names. fisherman needs `layout`.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Keyboard {
    pub layout: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub variant: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub model: String,
}

/// The `experimental` list for a filesystem: fisherman refuses `zfs`
/// without `"experimental": ["zfs"]` (zfs_experimental).
pub fn experimental_for(filesystem: &str) -> Vec<String> {
    if filesystem == "zfs" {
        vec!["zfs".to_string()]
    } else {
        Vec::new()
    }
}

/// The recipe's `user` block, as XFCE writes it.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct User {
    pub username: String,
    #[serde(default)]
    pub fullname: String,
    /// Plain text, like the LUKS passphrase: the recipe only ever travels on
    /// fisherman's stdin, never to a file.
    #[serde(default)]
    pub password: String,
    #[serde(default)]
    pub groups: Vec<String>,
}

/// `shared/account/groups.json`, compiled in (build.rs copies it to
/// OUT_DIR; the Flatpak sets TUNA_SHARED_DIR).
const ACCOUNT_GROUPS_JSON: &str = include_str!(concat!(env!("OUT_DIR"), "/account-groups.json"));

/// The supplementary groups of the first account when no operator file
/// says otherwise (`shared/account/README.md`). `wheel` and `sudo` are the
/// two admin groups; fisherman removes each group the image does not have.
pub fn default_groups() -> Vec<String> {
    let root: serde_json::Value =
        serde_json::from_str(ACCOUNT_GROUPS_JSON).expect("account-groups.json is JSON");
    root["default_groups"]
        .as_array()
        .expect("default_groups is a list")
        .iter()
        .filter_map(|g| g.as_str().map(str::to_string))
        .collect()
}

/// The groups for an operator recipe (`<etc>/bootc-installer/recipe.json`,
/// already parsed; `None` for no file). A `user.groups` that is a list of
/// strings replaces the default list, `[]` included. Anything else is
/// ignored.
pub fn groups_for(operator_recipe: Option<&serde_json::Value>) -> Vec<String> {
    operator_recipe
        .and_then(|r| r.get("user"))
        .and_then(|u| u.get("groups"))
        .and_then(|g| g.as_array())
        .and_then(|list| {
            list.iter()
                .map(|g| g.as_str().map(str::to_string))
                .collect::<Option<Vec<String>>>()
        })
        .unwrap_or_else(default_groups)
}

/// The operator recipe below `etc` (`/etc`, or `/run/host/etc` in a
/// Flatpak), parsed: what [`groups_for`] and
/// [`crate::image_catalog::live_leaf`] read. `None` for a file that is
/// missing or that does not parse.
pub fn read_operator_recipe(etc: &str) -> Option<serde_json::Value> {
    std::fs::read_to_string(format!("{etc}/bootc-installer/recipe.json"))
        .ok()
        .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
}

/// The account page's fields as the recipe's `user` block, or `None` when no
/// username was typed (fisherman skips user creation for an empty one).
pub fn user_block(username: &str, fullname: &str, password: &str, groups: &[String]) -> Option<User> {
    if username.is_empty() {
        return None;
    }
    Some(User {
        username: username.to_string(),
        fullname: fullname.to_string(),
        password: password.to_string(),
        groups: groups.to_vec(),
    })
}

fn is_bootc(image_type: &String) -> bool {
    image_type.is_empty() || image_type == "bootc"
}

/// What the machine tells the image choice: fisherman's probe for live
/// media and the offline stores, and this frontend's own look for an NVIDIA
/// GPU (the probe does not report one yet).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Machine {
    pub has_nvidia: bool,
    pub is_live: bool,
    pub offline_images: Vec<String>,
}

impl Recipe {
    /// Write every contract field of a catalog leaf
    /// (`shared/catalog/README.md`, "Fields that each frontend must use").
    /// The one place a leaf reaches the recipe: the image page, the live
    /// path and the end-to-end test all come through here. The hostname is
    /// the caller's, because the user can have typed one.
    pub fn apply_leaf(&mut self, leaf: &crate::image_catalog::ImageLeaf, machine: &Machine) {
        let (image, target) = crate::image_catalog::source_and_target(
            leaf,
            machine.has_nvidia,
            machine.is_live,
            &machine.offline_images,
        );
        self.image = image;
        self.target_imgref = target;
        self.bootloader.clone_from(&leaf.bootloader);
        self.compose_fs_backend = leaf.composefs;
        // The new leaf's filesystem, never the one of the leaf before it.
        // With no word from the leaf, this frontend's default.
        self.filesystem = if leaf.filesystem.is_empty() {
            Recipe::default().filesystem
        } else {
            leaf.filesystem.clone()
        };
        self.btrfs_subvolumes = self.filesystem == "btrfs";
        self.flatpaks.clone_from(&leaf.flatpaks);
        self.flatpak_var_path.clone_from(&leaf.flatpak_var_path);
        self.image_type.clone_from(&leaf.image_type);
        self.extras.clone_from(&leaf.extras);
    }

    /// Writes `experimental` for the filesystem the recipe has now.
    pub fn accept_experimental(&mut self) {
        self.experimental = experimental_for(&self.filesystem);
    }

    /// The disk page's filesystem pick (`Message::FilesystemChanged`):
    /// btrfs gets its subvolumes, the others none.
    pub fn choose_filesystem(&mut self, filesystem: &str) {
        self.btrfs_subvolumes = filesystem == "btrfs";
        self.filesystem = filesystem.to_string();
    }

    /// The encryption page's pick (`Message::EncryptionChanged`). A type
    /// that takes no passphrase drops the one typed before, so that a stale
    /// value cannot reach the recipe; the return value says it did.
    pub fn choose_encryption(&mut self, enc_type: &str) -> bool {
        self.encryption.enc_type = enc_type.to_string();
        if crate::validate::needs_passphrase(enc_type) {
            return false;
        }
        self.encryption.passphrase.clear();
        true
    }

    /// The keyboard page's pick (`Message::SelectKeymap`): an XKB layout.
    pub fn choose_keyboard(&mut self, layout: &str) {
        self.keyboard = Some(Keyboard {
            layout: layout.to_string(),
            ..Keyboard::default()
        });
    }

    /// The recipe as fisherman gets it, before the install source of the
    /// confirm page: with `experimental` for the filesystem.
    pub fn for_fisherman(&self) -> serde_json::Value {
        let mut recipe = self.clone();
        recipe.accept_experimental();
        serde_json::to_value(&recipe).unwrap_or_default()
    }

    /// An image that is not in the catalog (a custom reference, or the
    /// branding default with no catalog): the image is its own update
    /// target, and every leaf field goes back to its default.
    pub fn apply_unlisted_image(&mut self, imgref: &str) {
        let neutral = Recipe::default();
        self.image = imgref.to_string();
        self.target_imgref = imgref.to_string();
        self.bootloader = neutral.bootloader.clone();
        self.compose_fs_backend = neutral.compose_fs_backend;
        self.flatpaks = None;
        self.flatpak_var_path.clear();
        self.image_type.clear();
        self.extras = None;
        // The user's filesystem stays, unless only the leaf before could
        // offer it.
        if !crate::image_catalog::OWN_FILESYSTEMS.contains(&self.filesystem.as_str()) {
            self.filesystem = neutral.filesystem;
        }
        self.btrfs_subvolumes = self.filesystem == "btrfs";
    }
}

// true makes bootc boot the installed system with selinux=0. Keep SELinux on.
fn default_selinux() -> bool {
    false
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Encryption {
    #[serde(rename = "type")]
    pub enc_type: String,
    #[serde(default)]
    pub passphrase: String,
}

impl Default for Encryption {
    fn default() -> Self {
        Self {
            enc_type: "none".into(),
            passphrase: String::new(),
        }
    }
}

impl Default for Recipe {
    fn default() -> Self {
        Self {
            disk: String::new(),
            filesystem: "xfs".into(),
            btrfs_subvolumes: false,
            encryption: Encryption::default(),
            // Neutral; init() fills these from the branding contract.
            image: String::new(),
            target_imgref: String::new(),
            bootloader: String::new(),
            compose_fs_backend: false,
            flatpaks: None,
            flatpak_var_path: String::new(),
            image_type: String::new(),
            extras: None,
            experimental: Vec::new(),
            locale: String::new(),
            keyboard: None,
            timezone: String::new(),
            additional_image_stores: Vec::new(),
            distro_id: crate::branding::NEUTRAL_ID.into(),
            selinux_disabled: false,
            hostname: crate::branding::NEUTRAL_ID.into(),
            user: None,
        }
    }
}

/// One disk fisherman offers (`fisherman probe --json`, eligible only), as
/// every frontend renders it: shared/probe/README.md.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct DiskInfo {
    /// "/dev/nvme0n1"
    pub path: String,
    /// The model, or the path when the model is unknown.
    pub title: String,
    pub model: String,
    /// fisherman's size label, verbatim ("953.9 GiB").
    pub size_label: String,
    /// "NVMe", "SATA", "USB", ... or "".
    pub transport_label: String,
    pub removable: bool,
}


#[cfg(test)]
mod tests {
    use super::*;

    const SHARED_GROUPS: &str =
        concat!(env!("CARGO_MANIFEST_DIR"), "/../../shared/account/groups.json");

    /// The compiled-in list is the shared file (build.rs copies it), and
    /// default_groups() reads it.
    #[test]
    fn the_group_list_is_the_shared_file() {
        let shared = std::fs::read_to_string(SHARED_GROUPS).expect("shared/account/groups.json");
        let root: serde_json::Value = serde_json::from_str(&shared).unwrap();
        assert_eq!(serde_json::json!(default_groups()), root["default_groups"]);
        assert!(default_groups().contains(&"sudo".to_string()));
        assert!(default_groups().contains(&"wheel".to_string()));
    }

    /// Every case of the shared file: an operator file in, the groups out.
    #[test]
    fn the_shared_group_cases_hold() {
        let root: serde_json::Value = serde_json::from_str(ACCOUNT_GROUPS_JSON).unwrap();
        let cases = root["cases"].as_array().unwrap();
        assert!(cases.len() >= 8);
        for case in cases {
            let operator = &case["operator_recipe"];
            let got = groups_for((!operator.is_null()).then_some(operator));
            assert_eq!(serde_json::json!(got), case["groups"], "{}", case["name"]);
        }
    }

    #[test]
    fn the_operator_file_is_read_below_etc() {
        let dir = tempfile::tempdir().unwrap();
        let etc = dir.path().to_str().unwrap();
        let groups = |etc| groups_for(read_operator_recipe(etc).as_ref());
        assert_eq!(groups(etc), default_groups(), "no file");
        std::fs::create_dir_all(dir.path().join("bootc-installer")).unwrap();
        let file = dir.path().join("bootc-installer/recipe.json");
        std::fs::write(&file, r#"{"user": {"groups": ["wheel", "video"]}}"#).unwrap();
        assert_eq!(groups(etc), ["wheel", "video"]);
        std::fs::write(&file, "not json").unwrap();
        assert_eq!(groups(etc), default_groups(), "a file that does not parse");
    }

    #[test]
    fn the_region_keys_are_left_out_until_a_pick() {
        let recipe = Recipe::default();
        let json = serde_json::to_value(&recipe).unwrap();
        for key in ["locale", "keyboard", "timezone"] {
            assert!(json.get(key).is_none(), "{key}: {json}");
        }
        let recipe = Recipe {
            locale: "de_DE.UTF-8".into(),
            keyboard: Some(Keyboard { layout: "de".into(), ..Keyboard::default() }),
            timezone: "Europe/Berlin".into(),
            ..Recipe::default()
        };
        let json = serde_json::to_value(&recipe).unwrap();
        assert_eq!(json["locale"], "de_DE.UTF-8");
        assert_eq!(json["keyboard"], serde_json::json!({"layout": "de"}));
        assert_eq!(json["timezone"], "Europe/Berlin");
    }

    #[test]
    fn zfs_carries_the_experimental_opt_in_and_extras_round_trip() {
        let mut recipe = Recipe { filesystem: "zfs".into(), ..Recipe::default() };
        recipe.accept_experimental();
        let json = serde_json::to_value(&recipe).unwrap();
        assert_eq!(json["experimental"], serde_json::json!(["zfs"]));
        recipe.filesystem = "xfs".into();
        recipe.accept_experimental();
        assert!(serde_json::to_value(&recipe).unwrap().get("experimental").is_none());
        recipe.extras = Some(Extras { boot_splash: true, ..Extras::default() });
        let json = serde_json::to_value(&recipe).unwrap();
        assert_eq!(json["extras"], serde_json::json!(
            {"printServices": false, "oemSetup": false, "audioNames": false, "bootSplash": true}));
        assert!(serde_json::from_value::<Extras>(serde_json::json!({"desktopIcons": true})).is_err());
    }

    #[test]
    fn an_unlisted_image_is_its_own_target_and_drops_the_leaf_fields() {
        let catalog = crate::image_catalog::parse_manifest(
            r#"{"images": [{"name": "A", "imgref": "registry.example/os/a:1",
                "bootloader": "systemd", "composefs": true, "filesystem": "zfs",
                "flatpaks": [], "flatpak_var_path": "state/var", "extras": {"bootSplash": true}}]}"#,
        )
        .unwrap();
        let mut recipe = Recipe::default();
        recipe.apply_leaf(&catalog.leaves[0], &Machine::default());
        assert_eq!(recipe.filesystem, "zfs");
        recipe.apply_unlisted_image("registry.example/os/custom:1");
        let json = serde_json::to_value(&recipe).unwrap();
        assert_eq!(json["image"], "registry.example/os/custom:1");
        assert_eq!(json["targetImgref"], "registry.example/os/custom:1");
        for key in ["bootloader", "composeFsBackend", "flatpaks", "flatpakVarPath", "imageType", "extras"] {
            assert!(json.get(key).is_none(), "{key}: {json}");
        }
        // zfs was the leaf's own offer; this frontend's list has no zfs.
        assert_eq!(json["filesystem"], "xfs");
        // A filesystem of this frontend's own list stays.
        recipe.filesystem = "ext4".into();
        recipe.apply_unlisted_image("registry.example/os/custom:2");
        assert_eq!(recipe.filesystem, "ext4");
    }
}
