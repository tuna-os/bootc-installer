# disk.py
#
# Copyright 2024 mirkobrombin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundationat version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Class overview (all are GTK widget subclasses — kept in one file due to
# tight coupling; extract only if they grow independent):
#
#   BootcDefaultDiskEntry      — single disk item row (auto-select list)
#   BootcDefaultDiskConfirmModal — confirmation modal before the install
#   BootcDefaultDisk           — main disk wizard step (whole-disk install)

import pathlib
import subprocess
from gettext import gettext as _
import logging
import os

from gi.repository import Adw, GLib, Gtk

from bootc_installer.core.disks import DisksManager
from bootc_installer.core.system import Systeminfo
from bootc_installer.utils.field_check import FieldCheck
from bootc_installer.defaults.disk_plan import (
    build_auto_partition_recipe,
    build_disk_finals,
)

logger = logging.getLogger("Installer::Disk")


# ── Disk list row ──────────────────────────────────────────────────────────────

@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/widget-disk.ui")
class BootcDefaultDiskEntry(Adw.ActionRow):
    __gtype_name__ = "BootcDefaultDiskEntry"

    chk_button = Gtk.Template.Child()

    def __init__(self, parent, disk, role="system", **kwargs):
        super().__init__(**kwargs)
        self.__parent = parent
        self.__disk = disk
        # fisherman's disk (shared/probe/README.md): the model (the path when
        # unknown), then the path, fisherman's size label and the bus.
        self.set_title(disk.display_name)
        bits = [disk.disk, disk.pretty_size, getattr(disk, "transport_label", "")]
        self.set_subtitle(" · ".join(b for b in bits if b))

        callback = (
            self.__parent.on_var_disk_entry_toggled
            if role == "var"
            else self.__parent.on_disk_entry_toggled
        )
        self.chk_button.connect("toggled", callback, self.disk)

    @property
    def is_active(self):
        if self.chk_button.get_active():
            return True

    @property
    def disk(self):
        return self.__disk

    @property
    def disk_block(self):
        return self.__partition.disk_block


# ── Install confirmation modal ────────────────────────────────────────────────

@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/dialog-disk-confirm.ui")
class BootcDefaultDiskConfirmModal(Adw.Window):
    __gtype_name__ = "BootcDefaultDiskConfirmModal"

    btn_cancel = Gtk.Template.Child()
    btn_apply = Gtk.Template.Child()
    group_partitions = Gtk.Template.Child()

    def __init__(self, window, partition_recipe, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.set_transient_for(self.__window)
        self.default_width, self.default_height = self.get_default_size()

        # signals
        self.btn_cancel.connect("clicked", self.__on_btn_cancel_clicked)
        self.btn_apply.connect("clicked", self.__on_btn_apply_clicked)

        # The only layout the wizard makes is the automatic one: the whole
        # disk. Manual partitioning was never reachable and is gone (#312).
        auto = partition_recipe.get("auto") if isinstance(partition_recipe, dict) else None
        if not isinstance(auto, dict):
            return
        entry = Adw.ActionRow()
        entry.set_title(auto["disk"])
        entry.set_subtitle(_("Entire disk will be used."))
        self.group_partitions.add(entry)
        for vg in auto.get("vgs_to_remove", []):
            entry = Adw.ActionRow()
            entry.set_title(_("LVM volume group: %s") % vg)
            entry.set_subtitle(_("Volume group will be removed."))
            self.group_partitions.add(entry)
        for pv in auto.get("pvs_to_remove", []):
            entry = Adw.ActionRow()
            entry.set_title(_("LVM physical volume: %s") % pv)
            entry.set_subtitle(_("Physical volume will be removed."))
            self.group_partitions.add(entry)

    def __on_btn_cancel_clicked(self, widget):
        self.destroy()

    def __on_btn_apply_clicked(self, widget):
        self.__window.next()
        self.destroy()


# ── Main disk wizard step ──────────────────────────────────────────────────────

@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-disk.ui")
class BootcDefaultDisk(Adw.Bin):
    __gtype_name__ = "BootcDefaultDisk"

    btn_next = Gtk.Template.Child()
    btn_auto = Gtk.Template.Child()
    btn_exit = Gtk.Template.Child()
    group_disks = Gtk.Template.Child()
    filesystem_row = Gtk.Template.Child()
    fs_tool_error_banner = Gtk.Template.Child()
    hostname_entry = Gtk.Template.Child()
    var_disk_switch = Gtk.Template.Child()
    group_var_disks = Gtk.Template.Child()
    group_var_disk_existing = Gtk.Template.Child()
    battery_banner = Gtk.Template.Child()
    var_disk_keep_row = Gtk.Template.Child()
    var_disk_keep_switch = Gtk.Template.Child()

    _VIRTUAL_DISK_SIZE = "50G"

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.delta = False
        self.__registry_disks = []
        self.__selected_disks = []
        self.__disks = DisksManager()
        self.__partition_recipe = None
        self.__selected_disks_sum = 0
        self.__use_virtual_disk = False
        self.__fs_tool_ok = True  # optimistic default; updated by __check_fs_tool
        self.__var_disk_selected = None  # Disk object for the optional /var disk
        self.__var_registry_disks = []   # BootcDefaultDiskEntry rows for var picker

        # The disks fisherman offers, in its order (shared/probe/README.md).
        # No minimum size and no removable-disk filter here: fisherman
        # already excluded disks under 50 GiB and the live USB, and an
        # external disk is a legitimate target.
        for disk in self.__disks.all_disks():
            entry = BootcDefaultDiskEntry(self, disk)
            self.group_disks.add(entry)
            self.__registry_disks.append(entry)

        # With no disk to install to, say so here rather than skipping the
        # page. Skipping it is what let a user reach Install with an empty
        # disk recipe and only learn from fisherman's "disk is required" (#154).
        self.__no_disks_row = None
        if not self.__registry_disks:
            self.__no_disks_row = Adw.ActionRow()
            if self.__disks.error:
                self.__no_disks_row.set_title(_("Could not detect disks"))
                self.__no_disks_row.set_subtitle(self.__disks.error)
            else:
                self.__no_disks_row.set_title(_("No disks detected"))
                self.__no_disks_row.set_subtitle(
                    _("Connect a disk of at least 50 GiB to install to. "
                      "Nothing can be installed until one is available.")
                )
            self.__no_disks_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
            self.group_disks.add(self.__no_disks_row)

        # The virtual disk is a developer aid for testing in a VM. It is only
        # offered when BOOTC_VIRTUAL_DISK names a loop device set up outside
        # the sandbox; on a real machine it would install into a file in the
        # live session, which is never what a user wants.
        self.__virtual_check = None
        if os.environ.get("BOOTC_VIRTUAL_DISK"):
            self.__virtual_row = self.__build_virtual_disk_row()
            self.group_disks.add(self.__virtual_row)

        # The hostname rule is fisherman's (`fisherman validate --json
        # --partial -`). This page used to accept any text and only strip
        # whitespace, so "my_pc" reached the installed /etc/hostname.
        self.hostname_message = Gtk.Label(xalign=0, wrap=True, margin_top=6)
        self.hostname_message.add_css_class("error")
        hostname_group = self.hostname_entry.get_ancestor(Adw.PreferencesGroup)
        if hostname_group is not None:
            hostname_group.add(self.hostname_message)
        self.hostname_check = FieldCheck(
            window, self.hostname_entry, "hostname",
            lambda text: {"hostname": text.strip()},
            self.hostname_message, on_change=self.__on_hostname_checked)

        self.btn_next.connect("clicked", self.__on_btn_next_clicked)
        self.btn_auto.connect("clicked", self.__on_auto_clicked)
        self.btn_exit.connect("clicked", self.__on_btn_exit_clicked)
        self.var_disk_switch.connect("notify::active", self.__on_var_disk_switch_toggled)

        # Populate filesystem picker and hostname from the selected image's metadata.
        # We do the initial setup now, but also refresh when this page becomes active
        # (image selection happens on the previous step, so __init__ runs too early).
        self.__filesystem_options = ["xfs"]
        self.__window.carousel.connect("page-changed", self.__on_carousel_page_changed)
        self.__refresh_from_image_step()
        self.__set_default_hostname()
        self.auto_select_single_disk()

        self.__check_battery()

    def __on_hostname_checked(self):
        self.__update_next_button()
        self.__update_action_buttons()

    def __on_carousel_page_changed(self, carousel, idx):
        if carousel.get_nth_page(idx) is self:
            self.__refresh_from_image_step()
            self.__check_battery()

    def __set_default_hostname(self):
        """Seed the hostname field with a hardware-derived name when no image
        step has provided a better default, so users see a unique, meaningful
        value rather than the generic 'localhost' placeholder."""
        current = self.hostname_entry.get_text().strip()
        if current not in ("", "localhost"):
            return
        try:
            generated = Systeminfo.generate_hostname()
            if generated:
                self.hostname_entry.set_text(generated)
        except Exception:
            logger.debug("Could not generate hostname", exc_info=True)

    def __check_battery(self):
        on_battery = False
        try:
            for supply in pathlib.Path("/sys/class/power_supply").iterdir():
                supply_type_file = supply / "type"
                if not supply_type_file.exists():
                    continue

                try:
                    supply_type = supply_type_file.read_text().strip()
                except OSError:
                    continue

                if supply_type not in ("Mains", "UPS"):
                    continue

                online_file = supply / "online"
                if not online_file.exists():
                    continue

                try:
                    if online_file.read_text().strip() == "0":
                        on_battery = True
                        break
                except OSError:
                    continue
        except Exception:
            logger.debug("Failed to determine power state", exc_info=True)

        self.battery_banner.set_revealed(on_battery)

    def __refresh_from_image_step(self):
        """Re-read image metadata and update filesystem picker and hostname."""
        image_step = getattr(self.__window, "image_step", None)
        if image_step is None:
            return
        finals = image_step.get_finals()
        if not isinstance(finals, dict):
            finals = {}
        supported = finals.get("supported_filesystems") or []
        default_hostname = finals.get("default_hostname") or ""
        if not isinstance(default_hostname, str):
            default_hostname = ""
        current = self.hostname_entry.get_text().strip()
        if default_hostname and current in ("", "localhost"):
            # Append a short hardware-derived suffix so the default hostname is
            # unique per machine (e.g. "bluefin-a7c3" instead of "bluefin").
            try:
                generated = Systeminfo.generate_hostname()
                suffix = generated.rsplit("-", 1)[-1] if "-" in generated else generated[-4:]
                unique_hostname = f"{default_hostname}-{suffix}"
            except Exception:
                unique_hostname = default_hostname
            self.hostname_entry.set_text(unique_hostname)
        self.__setup_filesystem_row(supported)

    # Maps filesystem type → (required tool, package name)
    _FS_TOOLS = {
        "xfs": ("mkfs.xfs", "xfsprogs"),
        "btrfs": ("mkfs.btrfs", "btrfs-progs"),
        "zfs": ("zpool", "zfsutils-linux"),
    }

    def __setup_filesystem_row(self, filesystems):
        """Show a filesystem picker when the selected image supports multiple rootfs types."""
        self.__filesystem_options = filesystems if filesystems else ["xfs"]
        if len(self.__filesystem_options) <= 1:
            self.filesystem_row.set_visible(False)
            self.__check_fs_tool(self.__filesystem_options[0] if self.__filesystem_options else "xfs")
            return

        _LABELS = {"xfs": "XFS", "btrfs": _("Btrfs (with subvolumes)"), "zfs": "ZFS"}
        model = Gtk.StringList.new([_LABELS.get(fs, fs.upper()) for fs in self.__filesystem_options])
        self.filesystem_row.set_model(model)
        self.filesystem_row.set_selected(0)
        self.filesystem_row.set_visible(True)
        self.filesystem_row.connect("notify::selected", self.__on_filesystem_changed)
        self.__check_fs_tool(self.__filesystem_options[0])

    def __on_filesystem_changed(self, row, _pspec):
        self.__check_fs_tool(self.__get_selected_filesystem())

    def __check_fs_tool(self, fs):
        """Highlight the filesystem row and block Next if the required mkfs tool is missing."""
        tool, pkg = self._FS_TOOLS.get(fs, (None, None))
        if tool is None:
            self.__fs_tool_ok = True
            self.filesystem_row.remove_css_class("error")
            self.filesystem_row.set_subtitle("")
            self.fs_tool_error_banner.set_visible(False)
            self.__update_next_button()
            return
        try:
            result = subprocess.run(
                ["flatpak-spawn", "--host", "sh", "-c", f"command -v {tool}"],
                capture_output=True,
                timeout=3,
            )
            available = result.returncode == 0
        except Exception:
            available = True  # assume available if check fails
        self.__fs_tool_ok = available
        if available:
            self.filesystem_row.remove_css_class("error")
            self.filesystem_row.set_subtitle("")
            self.fs_tool_error_banner.set_visible(False)
        else:
            self.filesystem_row.add_css_class("error")
            self.filesystem_row.set_subtitle(
                _('Install the "{}" package on the host to use this filesystem').format(pkg)
            )
            self.fs_tool_error_banner.set_title(
                _('Missing host tool: "{}" — install the "{}" package').format(tool, pkg)
            )
            self.fs_tool_error_banner.set_visible(True)
        self.__update_next_button()

    def __update_next_button(self):
        """Enable Next only when a partition recipe exists, the fs tool is
        present and fisherman knows no problem with the hostname."""
        ok = (self.__partition_recipe is not None and self.__fs_tool_ok
              and self.hostname_check.ok)
        self.btn_next.set_visible(ok)
        self.btn_next.set_sensitive(ok)

    def __get_selected_filesystem(self):
        if not self.filesystem_row.get_visible():
            return self.__filesystem_options[0] if self.__filesystem_options else "xfs"
        idx = self.filesystem_row.get_selected()
        if 0 <= idx < len(self.__filesystem_options):
            return self.__filesystem_options[idx]
        return "xfs"

    def __on_btn_exit_clicked(self, button):
        self.__window.get_application().quit()

    def should_show(self, context: dict) -> bool:
        # Skip only when exactly one disk was found and pre-selected. With
        # none, the page has to appear to explain why Install is unavailable.
        return context.get("disk_count", 2) != 1

    def _set_auto_partition_recipe(self, disk):
        self.__partition_recipe = build_auto_partition_recipe(disk)
        self.__update_next_button()

    def auto_select_single_disk(self):
        disks = self.__disks.all_disks()

        if len(disks) != 1:
            return False

        disk = disks[0]
        self.__use_virtual_disk = False

        if not self.__selected_disks or self.__selected_disks[0].disk != disk.disk:
            matched_entry = next(
                (entry for entry in self.__registry_disks if entry.disk.disk == disk.disk),
                None,
            )
            if matched_entry is not None:
                matched_entry.chk_button.set_active(True)
            else:
                self.__selected_disks = [disk]
                self.__selected_disks_sum = disk.size
                self.__update_action_buttons()

        self._set_auto_partition_recipe(disk)
        logger.info("Auto-selected only installable disk: %s", disk.disk)
        return True

    @property
    def installable_disk_count(self) -> int:
        return len(self.__registry_disks)

    def test_auto_advance(self):
        self.btn_auto.emit("clicked")

    def __select_virtual_disk(self):
        if self.__use_virtual_disk:
            return
        self.__use_virtual_disk = True
        self.__selected_disks = []
        self.__selected_disks_sum = 0
        self.btn_auto.set_sensitive(True)
        if self.__virtual_check is not None:
            self.__virtual_check.set_active(True)
        logger.info("Virtual disk selected")

    def __build_virtual_disk_row(self):
        row = Adw.ActionRow()
        row.set_title(_("Virtual disk (for VMs / testing)"))
        row.set_subtitle(
            _("Creates a %s disk image and attaches it as a loop device") % self._VIRTUAL_DISK_SIZE
        )

        icon = Gtk.Image.new_from_icon_name("computer-symbolic")
        row.add_prefix(icon)

        self.__virtual_check = Gtk.CheckButton()
        row.add_suffix(self.__virtual_check)
        row.set_activatable_widget(self.__virtual_check)

        # Wire activation to the row AND the check button for reliability
        row.connect("activated", self.__on_virtual_row_activated)
        self.__virtual_check.connect("toggled", self.__on_virtual_check_toggled)

        # Deselect virtual row when a real disk row is selected
        for entry in self.__registry_disks:
            entry.chk_button.set_group(self.__virtual_check)

        return row

    def __on_virtual_row_activated(self, row):
        self.__select_virtual_disk()

    def __on_virtual_check_toggled(self, widget):
        if widget.get_active():
            self.__select_virtual_disk()

    @staticmethod
    def _virtual_disk_img() -> str:
        """Where a virtual disk image is created: the user's cache, not a
        hardcoded home directory."""
        return os.path.join(GLib.get_user_cache_dir(), "bootc-installer", "virtual-disk.img")

    def __setup_loopback(self) -> str | None:
        """Create the disk image and attach it as a loop device. Returns the device path."""
        import subprocess

        # If a loop device was pre-created outside the sandbox, use it directly.
        pre_created = os.environ.get("BOOTC_VIRTUAL_DISK", "")
        if pre_created.startswith("/dev/"):
            logger.info(f"Using pre-created virtual disk: {pre_created}")
            return pre_created

        img = self._virtual_disk_img()
        os.makedirs(os.path.dirname(img), exist_ok=True)
        # Commands that need root must break out of the Flatpak sandbox via flatpak-spawn
        def host_run(cmd, **kw):
            return subprocess.run(["flatpak-spawn", "--host"] + cmd, **kw)

        def host_output(cmd, **kw):
            return subprocess.check_output(["flatpak-spawn", "--host"] + cmd, **kw)

        try:
            logger.info(f"Creating virtual disk image: {img} ({self._VIRTUAL_DISK_SIZE})")
            subprocess.run(["truncate", "-s", self._VIRTUAL_DISK_SIZE, img], check=True)
            host_run(["pkexec", "losetup", "-fP", img], check=True)
            out = host_output(
                ["losetup", "--list", "--output", "NAME,BACK-FILE", "--noheadings"],
                text=True,
            )
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == img:
                    logger.info(f"Loop device: {parts[0]}")
                    return parts[0]
            logger.error("Could not find loop device after setup")
            return None
        except Exception as e:
            logger.error(f"Failed to set up loop device: {e}")
            return None

    def get_finals(self):
        fs = self.__get_selected_filesystem()
        virtual_disk = None
        if self.__use_virtual_disk:
            virtual_disk = (
                self._virtual_disk_img(),
                getattr(self, "_BootcDefaultDisk__loop_device", None),
            )
        var_disk = None
        if self.var_disk_switch.get_active() and self.__var_disk_selected:
            var_disk = (
                self.__var_disk_selected.disk,
                self.var_disk_keep_switch.get_active()
                if self.group_var_disk_existing.get_visible()
                else False,
            )
        return build_disk_finals(
            self.__partition_recipe,
            fs,
            self.hostname_entry.get_text(),
            virtual_disk=virtual_disk,
            var_disk=var_disk,
        )

    def __on_auto_clicked(self, button):
        if self.__use_virtual_disk:
            loop_dev = self.__setup_loopback()
            if not loop_dev:
                logger.error("Virtual disk setup failed")
                return
            self.__loop_device = loop_dev
            self.__partition_recipe = {
                "auto": {
                    "disk": loop_dev,
                    "pretty_size": self._VIRTUAL_DISK_SIZE,
                    "size": 0,
                    "vgs_to_remove": [],
                    "pvs_to_remove": [],
                }
            }
        else:
            self._set_auto_partition_recipe(self.__selected_disks[0])
        # In test mode skip the confirm modal and advance directly
        if os.environ.get("BOOTC_TEST"):
            self.__window.next()
            return
        self.confirm_partition_changes()

    def __update_action_buttons(self):
        self.btn_auto.set_sensitive(len(self.__selected_disks) == 1
                                    and self.hostname_check.ok)

    def on_disk_entry_toggled(self, widget, disk):
        self.__use_virtual_disk = False
        if widget.get_active():
            self.__selected_disks.append(disk)
            self.__selected_disks_sum += disk.size
        else:
            self.__selected_disks.remove(disk)
            self.__selected_disks_sum -= disk.size
        self.__update_action_buttons()
        # Rebuild var disk picker to exclude newly selected system disk
        if self.var_disk_switch.get_active():
            self.__rebuild_var_disk_picker()

    def __on_var_disk_switch_toggled(self, switch, _param):
        if switch.get_active():
            self.group_var_disks.set_visible(True)
            self.__rebuild_var_disk_picker()
        else:
            self.group_var_disks.set_visible(False)
            self.group_var_disk_existing.set_visible(False)
            self.__var_disk_selected = None

    def __rebuild_var_disk_picker(self):
        """Repopulate group_var_disks excluding the currently selected system disk."""
        # Remove old entries
        for entry in self.__var_registry_disks:
            self.group_var_disks.remove(entry)
        self.__var_registry_disks.clear()
        self.__var_disk_selected = None
        self.group_var_disk_existing.set_visible(False)

        system_disk = (
            self.__selected_disks[0].disk if self.__selected_disks else None
        )
        for d in self.__disks.all_disks():
            if system_disk and d.disk == system_disk:
                continue
            entry = BootcDefaultDiskEntry(self, d, role="var")
            self.group_var_disks.add(entry)
            self.__var_registry_disks.append(entry)

    def on_var_disk_entry_toggled(self, widget, disk):
        """Called by BootcDefaultDiskEntry when role='var' and user toggles it."""
        if widget.get_active():
            self.__var_disk_selected = disk
            self.__check_var_disk_existing(disk)
        else:
            self.__var_disk_selected = None
            self.group_var_disk_existing.set_visible(False)

    def __check_var_disk_existing(self, disk):
        """Detect existing filesystem on disk and show the keep/format toggle."""
        import subprocess
        try:
            out = subprocess.check_output(
                ["flatpak-spawn", "--host", "lsblk", "-no", "FSTYPE", disk.disk],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            # If lsblk returns a non-empty fstype the disk has a filesystem
            has_existing = bool(out)
        except Exception:
            has_existing = False
        if has_existing:
            logger.info("Existing filesystem detected on /var disk %s", disk.disk)
            self.group_var_disk_existing.set_visible(True)
            self.var_disk_keep_switch.set_active(True)
        else:
            self.group_var_disk_existing.set_visible(False)

    def __on_btn_next_clicked(self, button):
        self.confirm_partition_changes()

    def confirm_partition_changes(self):
        modal = BootcDefaultDiskConfirmModal(self.__window, self.__partition_recipe)
        modal.present()
