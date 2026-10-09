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
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub flatpaks: Vec<String>,
    /// Embedded OCI stores for offline installs (spec §4B).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub additional_image_stores: Vec<String>,
    #[serde(rename = "distroID")]
    pub distro_id: String,
    #[serde(default = "default_selinux")]
    pub selinux_disabled: bool,
    pub hostname: String,
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
            flatpaks: Vec::new(),
            additional_image_stores: Vec::new(),
            distro_id: crate::branding::NEUTRAL_ID.into(),
            selinux_disabled: false,
            hostname: crate::branding::NEUTRAL_ID.into(),
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

pub const FILESYSTEMS: [&str; 2] = ["xfs", "btrfs"];
