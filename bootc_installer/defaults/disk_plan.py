"""Pure construction helpers for the disk wizard's installer payload."""


def build_auto_partition_recipe(disk) -> dict:
    """Return the automatic-partition recipe for a selected disk."""
    return {
        "auto": {
            "disk": disk.disk,
            "pretty_size": disk.pretty_size,
            "size": disk.size,
            # For the confirm page only (Processor reads "disk"): the model
            # names the physical disk that is about to be erased, and
            # "removable" (#251) lets the confirm page warn that it is a
            # USB stick or other external drive, not the internal disk.
            "model": getattr(disk, "model", "") or "",
            "removable": bool(getattr(disk, "is_removable", False)),
            "vgs_to_remove": [],
            "pvs_to_remove": [],
        }
    }


PAGE_FILESYSTEMS = ["xfs"]


def filesystem_options(image_finals) -> tuple[list, int]:
    """(the filesystems the user can pick, the index selected at the start).

    shared/catalog/README.md, "Filesystem": the choices are the leaf's
    `filesystems`, else its one `filesystem`, else the page's own list. The
    selected one is the leaf's `filesystem`, else the first choice. The
    image step gives the two as `supported_filesystems` and
    `default_filesystem`.
    """
    finals = image_finals if isinstance(image_finals, dict) else {}
    options = [fs for fs in (finals.get("supported_filesystems") or [])
               if isinstance(fs, str) and fs]
    if not options:
        options = list(PAGE_FILESYSTEMS)
    default = finals.get("default_filesystem") or ""
    return options, options.index(default) if default in options else 0


def build_disk_finals(
    partition_recipe: dict | None,
    filesystem: str,
    hostname: str,
    *,
    virtual_disk: tuple[str, str | None] | None = None,
    var_disk: tuple[str, bool] | None = None,
) -> dict:
    """Build the disk step result without depending on GTK widget state."""
    disk = dict(partition_recipe) if partition_recipe else {}
    if "auto" in disk:
        disk["filesystem"] = filesystem
        disk["btrfsSubvolumes"] = filesystem == "btrfs"

    result = {"disk": disk, "hostname": hostname.strip()}
    if virtual_disk is not None:
        result["virtual_disk_img"], result["virtual_disk_loop"] = virtual_disk
    if var_disk is not None:
        result["var_disk"] = {
            "disk": var_disk[0],
            "keep_existing": var_disk[1],
        }
    return result
