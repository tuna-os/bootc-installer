# processor.py
#
# Copyright 2024 BootcOS contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation at version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import logging
import re

from bootc_shared import branding, catalog
from bootc_shared.account import resolve_groups
from bootc_installer.utils.sha512crypt import sha512_crypt

logger = logging.getLogger("Installer::Processor")


# A complete crypt(3) hash: $id$[rounds=N$]salt$hash, with the alphabet and
# lengths crypt uses. Only this is passed through unhashed. A bare "$"
# prefix is not enough: fisherman writes any "$"-prefixed password verbatim
# with `chpasswd -e`, so a user who typed "$uperSecret" got an account whose
# password field was that literal string, and could never log in.
_CRYPT_HASH_RE = re.compile(
    r"^\$(?:1|5|6)\$(?:rounds=\d+\$)?[./0-9A-Za-z]{1,16}\$[./0-9A-Za-z]{22,86}$"
    r"|^\$(?:y|gy|7)\$[./0-9A-Za-z]+\$[./0-9A-Za-z]+\$[./0-9A-Za-z]{43}$"
)


def _hash_user_password(password: str) -> str:
    """Hash a plaintext user password as a "$6$" crypt string.

    fisherman writes a "$"-prefixed password verbatim via `chpasswd -e`.
    Passing plaintext through forces fisherman to hash it itself via
    `chpasswd` without -e, which invokes the target's PAM stack to do so.
    On a composefs-native deploy fisherman only has `chpasswd --root <dir>`
    (no real chroot), so PAM module resolution fails against the target and
    the install aborts ("pam_chauthtok() failed", or plain "exit status 1"
    on EL10). Hashing here means fisherman never invokes PAM at all (#79).

    Hashed in plain Python (utils/sha512crypt.py): the flatpak's Python no
    longer has the `crypt` module, and an `openssl` CLI is not guaranteed.

    A complete crypt hash is returned unchanged, so a config that already
    carries one is not hashed twice. Empty input is returned unchanged:
    fisherman treats "" as "leave the account unset".
    """
    if not password or _CRYPT_HASH_RE.match(password):
        return password
    return sha512_crypt(password)


def _find_nvidia_imgref_for(imgref: str) -> str:
    """Search the image manifest for a nvidia_imgref associated with imgref.

    Walks the manifest tree (inherited from parent nodes) looking for the node
    whose imgref matches, then returns its nvidia_imgref field if present.
    Returns empty string if not found.
    """
    try:
        from bootc_installer.defaults.image import _MANIFEST
    except Exception:
        return ""
    # The catalog reader finds tag leaves (`registry` + `tag`) too.
    leaf = catalog.find(_MANIFEST, imgref)
    return leaf["nvidia_imgref"] if leaf else ""


def region_fields(merged: dict) -> dict:
    """The recipe's `locale`, `keyboard` and `timezone` from the finals of
    the language, keyboard and time zone steps (#292).

    A key is there only when its step has a selected value: without it
    fisherman keeps the image's own. `keyboard` is an XKB layout and, when
    the row has one, its variant. A value of the wrong type is left out;
    fisherman checks the names (`validate`), and the pages asked it first.
    """
    fields = {}
    language = merged.get("language")
    if isinstance(language, str) and language.strip():
        fields["locale"] = language.strip()
    keyboard = merged.get("keyboard")
    if isinstance(keyboard, dict):
        layout = keyboard.get("layout")
        variant = keyboard.get("variant")
        if isinstance(layout, str) and layout:
            fields["keyboard"] = {"layout": layout}
            if isinstance(variant, str) and variant:
                fields["keyboard"]["variant"] = variant
    timezone = merged.get("timezone")
    if isinstance(timezone, str) and timezone.strip():
        fields["timezone"] = timezone.strip()
    return fields


class Processor:
    @staticmethod
    def find_metadata(candidates, aliases, imgref) -> dict:
        """The catalog metadata of `imgref` in an `images` list: the fields
        that gen_install_recipe reads, or {} when the list has no leaf for
        the image.

        A list of one entry that names no image (no `imgref`, `tag`,
        `registry` or `children`) is the metadata of the one image there
        is; that entry is returned as it is.
        """
        leaf = catalog.find({"images": candidates, "aliases": aliases}, imgref, strict=True)
        if leaf is not None:
            return {
                "composefs": leaf["composefs"],
                "image_type": leaf["image_type"],
                "bootloader": leaf["bootloader"],
                # An image with one filesystem decides. One that offers a
                # choice does not: the disk page showed the list (the same
                # rule as image_finals.leaf_finals).
                "filesystem": leaf["filesystem"] if len(leaf["filesystems"]) <= 1 else "",
                "flatpak_var_path": leaf["flatpak_var_path"],
                "flatpaks": leaf["flatpaks"],
                "extras": leaf["extras"],
            }
        if (len(candidates) == 1
                and not any(key in candidates[0] for key in ("imgref", "tag", "registry", "children"))):
            return candidates[0]
        return {}

    @staticmethod
    def image_plan(finals: list, sys_recipe: dict) -> dict:
        """Which image is installed and which one updates follow.

        Returns {"selected", "install", "track"}: the image the user (or the
        recipe) chose, the image that is written to the disk, and the image
        `bootc upgrade` follows. They differ only for a catalog entry with
        an `nvidia_imgref`. gen_install_recipe and the confirm page both
        read this, so the page names the image that is installed (#314).
        `install` is the registry reference; a `local_imgref` source
        override is applied by gen_install_recipe afterwards.
        """
        merged = {}
        for step_finals in finals:
            if isinstance(step_finals, dict):
                merged.update(step_finals)

        # In Flatpak mode: finals contain "selected_image" or "custom_image" from the UI.
        # In live ISO mode: the image step is skipped; recipe["imgref"] holds the remote
        # tracking ref and optional "local_imgref" holds the install source override.
        image = merged.get("custom_image", "") or merged.get("selected_image", "")
        if not image:
            image = sys_recipe.get("imgref", "")
        if not image:
            # Fall back to first default-marked image in the recipe images list
            for img in sys_recipe.get("images", []):
                if img.get("default", False):
                    image = img.get("imgref", "")
                    break
        if not image and sys_recipe.get("images"):
            image = sys_recipe["images"][0].get("imgref", "")

        plan = {"selected": image, "install": image, "track": image}

        # NVIDIA: a catalog entry can name an nvidia_imgref.
        nvidia_imgref = merged.get("nvidia_imgref", "")
        if not nvidia_imgref and image:
            nvidia_imgref = _find_nvidia_imgref_for(image)
        if nvidia_imgref:
            # shared/catalog/README.md, "Image and NVIDIA image". With an
            # NVIDIA GPU the two are the NVIDIA image. Without one, the
            # NVIDIA image is the source only on live media whose store has
            # it and not the base image: the install needs no download, and
            # the first update moves the system to the base image. In each
            # other case a network install pulls the image the user chose.
            from bootc_installer.core.system import Systeminfo
            has_nvidia = bool(Systeminfo.has_nvidia_gpu())
            is_live = offline = None
            if not has_nvidia:
                is_live = bool(Systeminfo.is_live())
                offline = list(Systeminfo.offline_images()) if is_live else []
            plan["install"], plan["track"] = catalog.source_and_target(
                image, nvidia_imgref, has_nvidia, bool(is_live), offline or [])
            logger.info("NVIDIA image %s: gpu=%s live=%s, installing %s, tracking %s",
                        nvidia_imgref, has_nvidia, is_live, plan["install"], plan["track"])
        return plan

    @staticmethod
    def recipe_names_disk(recipe: dict) -> bool:
        """Whether the fisherman recipe names a target disk.

        The window checks this before starting fisherman: a recipe with an
        empty disk only fails inside fisherman, as "invalid recipe: disk is
        required", which a user cannot act on (#154).
        """
        try:
            return bool(str(recipe.get("disk") or "").strip())
        except AttributeError:
            return False

    @staticmethod
    def gen_install_recipe(log_path: str, finals: list, sys_recipe: dict) -> dict:
        """Generate a fisherman recipe JSON from the UI's collected finals.

        Args:
            log_path: not read; the callers still pass it
            finals: list of dicts collected from each installer step's get_finals()
            sys_recipe: the loaded system recipe (from /etc/bootcos-installer/recipe.json)

        Returns:
            The fisherman recipe. The caller hands it to fisherman on stdin
            (`fisherman -`); it is never written to a file, because it holds
            the LUKS passphrase and the user's password hash.
        """
        # Merge all finals dicts into one flat dict
        merged = {}
        for step_finals in finals:
            if isinstance(step_finals, dict):
                merged.update(step_finals)

        logger.info(f"Building fisherman recipe from finals: {list(merged.keys())}")

        # --- Disk ---
        # disk_info comes from BootcDefaultDisk.get_finals():
        #   {"auto": {"disk": "/dev/vda", ...}, "filesystem": ..., "btrfsSubvolumes": ...}
        # The wizard makes whole-disk layouts only. A manual layout (keys
        # that are partitions) had no page that could make it (#312), and
        # fisherman now needs /boot/efi (and /boot for GRUB with an XFS
        # root) in `customMounts`. Refuse it here, and never write
        # `customMounts`, so that no caller can send a layout that has no
        # boot partitions.
        disk_info = merged.get("disk", {})
        disk_device = ""
        filesystem = "xfs"
        btrfs_subvolumes = False

        if (isinstance(disk_info, dict) and disk_info
                and any(str(k).startswith("/dev/") for k in disk_info)):
            raise ValueError("Manual partition layouts are not supported")

        if isinstance(disk_info, dict):
            if "auto" in disk_info:
                disk_device = disk_info["auto"].get("disk", "")
            elif "disk" in disk_info:
                disk_device = disk_info["disk"]
            elif "device" in disk_info:
                disk_device = disk_info["device"]
            fs = disk_info.get("filesystem", "xfs")
            if fs not in ("xfs", "ext4", "btrfs", "zfs"):
                raise ValueError(f"Unsupported root filesystem: {fs!r}")
            filesystem = fs
            if filesystem == "btrfs":
                btrfs_subvolumes = disk_info.get("btrfsSubvolumes", False)
        elif isinstance(disk_info, str):
            disk_device = disk_info

        logger.info(f"Selected disk: {disk_device}, filesystem: {filesystem}")

        # --- Encryption ---
        enc_info = merged.get("encryption", {})
        encryption_type = "none"
        encryption_passphrase = ""

        if isinstance(enc_info, dict):
            use_enc = enc_info.get("use_encryption", False)
            if use_enc:
                key = enc_info.get("encryption_key", "")
                explicit_type = enc_info.get("type", "")
                if explicit_type in ("luks-passphrase", "tpm2-luks-passphrase", "tpm2-luks"):
                    encryption_type = explicit_type
                    encryption_passphrase = key
                elif key:
                    encryption_type = "luks-passphrase"
                    encryption_passphrase = key
                else:
                    encryption_type = "tpm2-luks"

        # --- Image / OCI ref ---
        # image_plan resolves the chosen image and the NVIDIA variant; the
        # confirm page reads the same plan.
        plan = Processor.image_plan(finals, sys_recipe)
        image = plan["install"]
        if not image:
            logger.warning("No image/imgref found in finals or sys_recipe!")

        # target_imgref is always the remote registry reference written into the
        # installed system so that bootc upgrade tracks the correct upstream image.
        target_imgref = plan["track"]
        metadata_imgref = plan["selected"]  # catalog identity before NVIDIA/source overrides

        # local_imgref (live ISO only) is an optional install *source* override — e.g.
        # "containers-storage:ghcr.io/org/image:tag" for offline installs from a
        # pre-populated squashfs.  It is passed to fisherman as --source-imgref while
        # target_imgref (the remote ref) is passed as --target-imgref unchanged.
        local_imgref = sys_recipe.get("local_imgref", "")
        if local_imgref:
            if not sys_recipe.get("imgref") or metadata_imgref != sys_recipe["imgref"]:
                raise ValueError("Local install source does not match the selected system image")
            logger.info(
                f"local_imgref override: install source={local_imgref}, "
                f"installed system tracks={target_imgref}"
            )
            image = local_imgref

        # --- Hostname ---
        # Use hardware-derived hostname if no explicit hostname was set by the user.
        hostname = merged.get("hostname", "")
        if not hostname:
            hostname = sys_recipe.get("hostname", "")
        if not hostname:
            from bootc_installer.core.system import Systeminfo
            hostname = Systeminfo.generate_hostname()


        # --- SELinux / unified storage / composefs / image type ---
        selinux_disabled = sys_recipe.get("selinuxDisabled", False)
        # unifiedStorage: fisherman never passed bootc's flag for it, and
        # refuses `true` now (tuna-os/fisherman#366). The key is written only
        # when the system recipe asks for it, so that the operator gets
        # fisherman's answer; the installer itself never asks.
        unified_storage = sys_recipe.get("unifiedStorage", False) is True
        # Resolve each field independently. A selected image's explicit false
        # is meaningful; missing filesystem metadata must not replace it with
        # the first catalog image's backend. Live media skips the image step,
        # so canonical top-level system-recipe fields are the next source.
        metadata = {}
        recipe_images = sys_recipe.get("images", [])
        if not isinstance(recipe_images, list):
            raise ValueError("System recipe images must be a list")  # noqa: TRY004 - invalid serialized recipe, surfaced in UI
        metadata_aliases = {}
        if recipe_images:
            candidates = recipe_images
        else:
            # The system catalog, then the legacy name of the same file
            # (shared/catalog/README.md). A file that is there and cannot
            # be read is an error here: the install must not go on with
            # the wrong backend.
            candidates = []
            etc = "/run/host/etc" if catalog.in_flatpak() else "/etc"
            for path in (f"{etc}/bootc-installer/images.json",
                         f"{etc}/tuna-installer/images.json"):
                try:
                    with open(path) as stream:
                        host_catalog = json.load(stream)
                    if not isinstance(host_catalog, dict):
                        raise ValueError("Image catalog must be an object")  # noqa: TRY004 - invalid serialized recipe, surfaced in UI
                    candidates = host_catalog.get("images", [host_catalog])
                    if isinstance(host_catalog.get("aliases"), dict):
                        metadata_aliases = host_catalog["aliases"]
                    break
                except FileNotFoundError:
                    continue
                except (OSError, ValueError) as error:
                    raise ValueError(f"Cannot read image metadata at {path}: {error}") from error
        # Match the chosen tracking reference, never a local OCI source or an
        # unrelated first row. The leaf comes from the one catalog reader
        # (bootc_shared.catalog), so it inherits what the image page shows.
        # `strict`: a tree that is not lists of objects, or a wrong type in
        # the leaf of this image, stops the install (CatalogError is a
        # ValueError); it must not go on with a default backend.
        metadata = Processor.find_metadata(candidates, metadata_aliases, metadata_imgref)

        def field(ui_key, system_key, image_key, default):
            for source, key in ((merged, ui_key), (sys_recipe, system_key),
                                (metadata, image_key)):
                if key in source and source[key] != "":
                    return source[key]
            return default

        composefs_backend = field("composefs_backend", "composeFsBackend", "composefs", False)
        if not isinstance(composefs_backend, bool):
            raise ValueError("composeFsBackend must be a boolean")  # noqa: TRY004 - invalid serialized recipe, surfaced in UI
        image_type = field("image_type", "imageType", "image_type", "bootc")
        bootloader = field("bootloader", "bootloader", "bootloader", "")
        image_filesystem = field("image_filesystem", "filesystem", "filesystem", "")
        flatpak_var_path = field("flatpak_var_path", "flatpakVarPath", "flatpak_var_path", "")
        for key, value in (("imageType", image_type), ("filesystem", image_filesystem),
                           ("bootloader", bootloader), ("flatpakVarPath", flatpak_var_path)):
            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string")  # noqa: TRY004 - invalid serialized recipe, surfaced in UI
        if bootloader not in ("", "grub2", "systemd"):
            raise ValueError(f"Unsupported bootloader: {bootloader!r}")
        # Image/backend compatibility remains fisherman's validation authority.
        # Preserve unsupported imageType values so its structured validation can
        # reject them; never turn an unknown backend into the bootc default.
        if image_filesystem:
            if image_filesystem not in ("xfs", "ext4", "btrfs", "zfs"):
                raise ValueError(f"Unsupported image filesystem: {image_filesystem!r}")
            # An image with one filesystem decides. An image that offers a
            # choice (`filesystems`) does not: the disk page showed that
            # list, and what the user picked from it stands.
            choices = merged.get("supported_filesystems") or []
            picked = disk_info.get("filesystem") if isinstance(disk_info, dict) else None
            if not (len(choices) > 1 and picked in choices):
                filesystem = image_filesystem

        # --- Flatpaks ---
        # shared/catalog/README.md, "Flatpak lists". `flatpaks` is written
        # only when a list is known: [] tells fisherman to copy no Flatpak,
        # and no key tells it to apply its own default. The installer never
        # downloads a list and never puts a list of its own here. The
        # sources, in order: the selected leaf (the image step), the
        # system recipe, the catalog entry of the image.
        flatpaks = None
        for source in (merged, sys_recipe):
            value = source.get("flatpaks")
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                flatpaks = list(value)
                break
        if flatpaks is None:
            flatpaks = catalog.resolve_flatpaks(metadata.get("flatpaks"), metadata_aliases)
        # --- Desktop extras ---
        # shared/catalog/README.md, "Desktop extras". The object of the
        # selected leaf, then the system recipe's, then the catalog entry
        # of the image. A staged fisherman has no catalog next to it, so
        # the installer copies the object; with no object the key is left
        # out and fisherman applies its own lookup.
        extras = None
        for source in (merged, sys_recipe, metadata):
            if isinstance(source.get("extras"), dict):
                extras = catalog.resolve_extras(source["extras"])
                break
        # Overriding a btrfs disk selection with ext4 must clear its stale flag.
        btrfs_subvolumes = (filesystem == "btrfs" and isinstance(disk_info, dict)
                           and bool(disk_info.get("btrfsSubvolumes", False)))

        # --- User account ---
        user_info = merged.get("user", {})
        user_username = user_info.get("username", "")
        user_fullname = user_info.get("fullname", "")
        user_password = _hash_user_password(user_info.get("password", ""))
        # Groups (shared/account/README.md): the user page sends the shared
        # default list. The operator's `user.groups` of the system recipe
        # replaces it when that is a list of strings ([] included): an ISO
        # builder knows the groups of the image.
        user_groups = resolve_groups(sys_recipe, default=user_info.get("groups", []))

        # For non-composefs (ostree/bootcDirect) live ISO installs, fisherman
        # expects an empty "image" and populated "targetImgref" so that it invokes
        # bootc install directly against host storage without containerized scratch export.
        fisherman_image = image
        # When the live ISO recipe explicitly sets image="" for non-composefs (bootcDirect),
        # honor the empty image so fisherman invokes host-direct bootc install.
        if not composefs_backend and image_type == "bootc" and sys_recipe.get("image") == "":
            fisherman_image = ""

        # Build the fisherman recipe
        recipe = {
            "disk": disk_device,
            "filesystem": filesystem,
            "btrfsSubvolumes": btrfs_subvolumes,
            "encryption": {
                "type": encryption_type,
                "passphrase": encryption_passphrase,
            },
            "image": fisherman_image,
            "targetImgref": target_imgref,
            "selinuxDisabled": selinux_disabled,
            "composeFsBackend": composefs_backend,
            "bootloader": bootloader,
            "hostname": hostname,
            # fisherman names the OEM paths and services after this
            # (/etc/<distroID>/oem/). It is the branding id, like every
            # other frontend; with nothing branded it is os-release's ID.
            "distroID": branding.resolve().id,
            "user": {
                "username": user_username,
                "fullname": user_fullname,
                "password": user_password,
                "groups": user_groups,
            },
        }
        if unified_storage:
            recipe["unifiedStorage"] = True
        if flatpaks is not None:
            recipe["flatpaks"] = flatpaks
        if extras is not None:
            recipe["extras"] = extras
        # fisherman refuses zfs unless the recipe accepts that it is
        # experimental (no VM test boots ZFS): zfs_experimental. The user
        # picked it, from a list that only an image's catalog entry offers.
        if filesystem == "zfs":
            recipe["experimental"] = ["zfs"]
        # Language, keyboard and time zone: only what the user selected.
        recipe.update(region_fields(merged))
        if image_type and image_type != "bootc":
            recipe["imageType"] = image_type
        if flatpak_var_path:
            recipe["flatpakVarPath"] = flatpak_var_path
        # Offline image stores: only when the ISO's recipe names them. Left
        # out, fisherman exposes the stores it finds on the host itself
        # (tuna-os/fisherman#276); [] would turn that off.
        additional_stores = sys_recipe.get("additionalImageStores")
        if additional_stores:
            recipe["additionalImageStores"] = additional_stores
        var_disk = merged.get("var_disk")
        if var_disk and var_disk.get("disk"):
            recipe["varDisk"] = {
                "disk": var_disk["disk"],
                "keepExisting": bool(var_disk.get("keep_existing", False)),
            }

        logger.info(f"Generated fisherman recipe: disk={disk_device}, image={image}, encryption={encryption_type}")

        return recipe
