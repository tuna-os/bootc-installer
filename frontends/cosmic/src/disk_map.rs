//! The disk map: what is on a disk, and what the install makes of it, as a
//! bar of parts in proportion with a legend.
//!
//! It shows only what the daemon's Probe says. A daemon that names no
//! partitions gives no map, and the page is as it was without one.

use crate::probe::{DiskData, Partition};
use crate::ui::copy;

/// What a part of the bar is, which sets its colour.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Boot,
    Windows,
    Linux,
    Locked,
    Other,
    Free,
    New,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Part {
    pub kind: Kind,
    pub name: String,
    /// 0 for a size that nothing states.
    pub bytes: u64,
    /// The share of the bar. Never below `MIN_SHARE`: a 100 MiB partition of a
    /// 2 TB disk is a part a person must see.
    pub share: u16,
}

const MIN_SHARE: u64 = 12;
const SCALE: u64 = 1000;

fn part(kind: Kind, name: String, bytes: u64, total: u64) -> Part {
    let share = (bytes.saturating_mul(SCALE) / total.max(1)).clamp(MIN_SHARE, SCALE);
    Part { kind, name, bytes, share: share as u16 }
}

fn kind_of(p: &Partition) -> Kind {
    match p.fstype.as_str() {
        "vfat" => Kind::Boot,
        "ntfs" | "BitLocker" => Kind::Windows,
        "crypto_LUKS" => Kind::Locked,
        "ext2" | "ext3" | "ext4" | "btrfs" | "xfs" => Kind::Linux,
        _ => Kind::Other,
    }
}

/// The label a person gave it, else what it is.
fn name_of(p: &Partition, kind: Kind) -> String {
    if !p.label.is_empty() {
        return p.label.clone();
    }
    match kind {
        Kind::Boot => crate::i18n::tr(copy::MAP_BOOT),
        Kind::Windows => crate::i18n::tr(copy::MAP_WINDOWS),
        Kind::Linux => crate::i18n::tr(copy::MAP_LINUX),
        Kind::Locked => crate::i18n::tr(copy::MAP_ENCRYPTED),
        _ if p.fstype.is_empty() => p.path.clone(),
        _ => p.fstype.clone(),
    }
}

/// The disk as it is. Empty without facts about it.
pub fn now(disk: &DiskData) -> Vec<Part> {
    if disk.size_bytes == 0 {
        return Vec::new();
    }
    let mut parts: Vec<Part> = disk
        .partitions
        .iter()
        .map(|p| {
            let kind = kind_of(p);
            part(kind, name_of(p, kind), p.size_bytes, disk.size_bytes)
        })
        .collect();
    if disk.free_bytes > disk.size_bytes / 1000 {
        parts.push(part(
            Kind::Free,
            crate::i18n::tr(copy::MAP_FREE),
            disk.free_bytes,
            disk.size_bytes,
        ));
    }
    parts
}

/// The disk after the install. With `keep` the parts stay and the product
/// takes the free space; without it the product has the disk. The daemon
/// states no sizes of the new partitions, so the boot part has none.
pub fn after(disk: &DiskData, keep: bool, product: &str) -> Vec<Part> {
    if disk.size_bytes == 0 {
        return Vec::new();
    }
    if keep {
        let mut parts: Vec<Part> =
            now(disk).into_iter().filter(|p| p.kind != Kind::Free).collect();
        parts.push(part(Kind::New, product.to_string(), disk.free_bytes, disk.size_bytes));
        return parts;
    }
    vec![
        Part {
            kind: Kind::Boot,
            name: crate::i18n::tr(copy::MAP_BOOT),
            bytes: 0,
            share: MIN_SHARE as u16,
        },
        part(Kind::New, product.to_string(), disk.size_bytes, disk.size_bytes),
    ]
}

/// "512.1 GiB", as fisherman writes a size.
pub fn size(bytes: u64) -> String {
    let mut value = bytes as f64;
    let mut unit = "B";
    for next in ["KiB", "MiB", "GiB", "TiB"] {
        if value < 1024.0 {
            break;
        }
        value /= 1024.0;
        unit = next;
    }
    let text = format!("{value:.1}");
    format!("{} {unit}", text.strip_suffix(".0").unwrap_or(&text))
}

/// One line of the legend.
pub fn legend(part: &Part) -> String {
    if part.bytes == 0 {
        part.name.clone()
    } else {
        format!("{} \u{b7} {}", part.name, size(part.bytes))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const GIB: u64 = 1 << 30;

    fn windows() -> DiskData {
        let p = |path: &str, fstype: &str, label: &str, size_bytes| Partition {
            path: path.into(),
            fstype: fstype.into(),
            label: label.into(),
            size_bytes,
        };
        DiskData {
            size_bytes: 500 * GIB,
            free_bytes: 100 * GIB,
            partitions: vec![
                p("/dev/sda1", "vfat", "SYSTEM", GIB / 4),
                p("/dev/sda2", "ntfs", "", 399 * GIB),
            ],
            ..DiskData::default()
        }
    }

    #[test]
    fn the_parts_are_in_proportion_and_none_is_lost() {
        let parts = now(&windows());
        assert_eq!(
            parts.iter().map(|p| p.kind).collect::<Vec<_>>(),
            [Kind::Boot, Kind::Windows, Kind::Free]
        );
        assert_eq!(parts[0].name, "SYSTEM");
        assert_eq!(parts[0].share, 12, "a small part stays visible");
        assert_eq!(parts[1].share, 798);
        assert_eq!(legend(&parts[2]), "Free space \u{b7} 100 GiB");
    }

    #[test]
    fn an_erase_leaves_the_product_and_free_space_keeps_the_rest() {
        let erased = after(&windows(), false, "Example");
        assert_eq!(erased.iter().map(|p| p.kind).collect::<Vec<_>>(), [Kind::Boot, Kind::New]);
        let kept = after(&windows(), true, "Example");
        assert_eq!(
            kept.iter().map(|p| p.kind).collect::<Vec<_>>(),
            [Kind::Boot, Kind::Windows, Kind::New]
        );
        assert_eq!(kept[2].bytes, 100 * GIB);
    }

    #[test]
    fn a_daemon_that_says_nothing_gives_no_map() {
        assert!(now(&DiskData::default()).is_empty());
        assert!(after(&DiskData::default(), false, "Example").is_empty());
    }

    #[test]
    fn sizes_read_as_fisherman_writes_them() {
        assert_eq!(size(64 * GIB), "64 GiB");
        assert_eq!(size(512_110_190_592), "476.9 GiB");
        assert_eq!(size(260 << 20), "260 MiB");
    }
}
