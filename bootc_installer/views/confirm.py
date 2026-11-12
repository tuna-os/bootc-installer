# dialog.py
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

import logging
import re
import threading
from gettext import gettext as _

from bootc_shared import plan as install_plan
from bootc_shared import source_check

from bootc_installer.utils import copy as copy_text
from bootc_installer.utils.field_check import FieldCheck
from bootc_installer.utils.processor import Processor

from gi.repository import Adw, GLib, GObject, Gtk

logger = logging.getLogger("Installer::Confirm")


# What the summary calls each root filesystem: the names the disk page's
# picker and the filesystems' own tools use.
_FILESYSTEM_LABELS = {"xfs": "XFS", "ext4": "ext4", "btrfs": "Btrfs", "zfs": "ZFS"}


def filesystem_label(fs: str, text=None) -> str:
    """The name of a root filesystem. ZFS is the branding copy
    `filesystem_zfs_label` through `text(key)`, when given: fisherman
    accepts it only as experimental, and the name says so."""
    if fs == "zfs" and text is not None:
        return text("filesystem_zfs_label") or _FILESYSTEM_LABELS["zfs"]
    return _FILESYSTEM_LABELS.get(fs, fs)


def disk_summary(auto: dict) -> str:
    """The Target disk row's value: the model and the device path, so the
    user can tell which physical disk is about to be erased, then its size.
    The model is the probe's (shared/probe); a disk without one shows its
    path alone."""
    path = auto.get("disk", "")
    size = auto.get("pretty_size", "")
    model = (auto.get("model") or "").strip()
    if model and model != path:
        return f"{model} ({path}, {size})" if size else f"{model} ({path})"
    return f"{path} ({size})" if size else path


def recipe_image(recipe: dict) -> str:
    """The image a recipe installs when no image step chose one, resolved
    in Processor.gen_install_recipe's order: imgref, the image marked
    default, the first image."""
    if recipe.get("imgref"):
        return recipe["imgref"]
    images = [i for i in recipe.get("images") or [] if isinstance(i, dict)]
    for img in images:
        if img.get("default"):
            return img.get("imgref", "")
    return images[0].get("imgref", "") if images else ""


def user_summary(user) -> str:
    """The account row's value: "name (Full Name)", or "" when the user
    step made no account."""
    if not isinstance(user, dict):
        return ""
    username = (user.get("username") or "").strip()
    if not username:
        return ""
    fullname = (user.get("fullname") or "").strip()
    return f"{username} ({fullname})" if fullname else username


def var_disk_summary(var_disk) -> tuple[str, bool]:
    """The /var disk row's value and whether that disk is erased.

    ("", False) when the install uses no second disk. Processor writes
    `keepExisting` from the same `keep_existing` flag, so the row says what
    fisherman does.
    """
    if not isinstance(var_disk, dict) or not var_disk.get("disk"):
        return "", False
    erased = not bool(var_disk.get("keep_existing", False))
    state = _("will be erased") if erased else _("kept, its data is not erased")
    return f"{var_disk['disk']}: {state}", erased


def keyboard_summary(keyboard) -> str:
    """The Keyboard row's value: the XKB layout, and its variant after a
    "+" ("de+nodeadkeys"), as the live session names it. "" when the
    keyboard step selected none."""
    if not isinstance(keyboard, dict) or not keyboard.get("layout"):
        return ""
    variant = keyboard.get("variant") or ""
    return f"{keyboard['layout']}+{variant}" if variant else keyboard["layout"]


def request_plan(recipe):
    """(result, error) of `fisherman plan --json -` for `recipe`: the
    parsed plan result and None, or None and why fisherman could not be
    asked. Runs fisherman unprivileged on the host, as the validate checks
    do, with the recipe on stdin. Call it off the UI thread: it waits up to
    install_plan.TIMEOUT_SECONDS."""
    from bootc_installer.utils import fisherman_runner
    try:
        if fisherman_runner.IN_FLATPAK and not fisherman_runner.stage_on_host():
            raise install_plan.PlanError("could not stage fisherman on the host")
        command = install_plan.argv(fisherman_runner.fisherman_argv())
        return install_plan.run(command, recipe), None
    except install_plan.PlanError as exc:
        return None, str(exc)


def erased_disks_text(disks: list) -> str:
    """The {disk} of the erase warning: every disk the install formats."""
    disks = [d for d in disks if d]
    if len(disks) <= 1:
        return disks[0] if disks else ""
    return _("{first} and {second}").format(first=", ".join(disks[:-1]), second=disks[-1])


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/widget-choice.ui")
class BootcChoiceEntry(Adw.ActionRow):
    __gtype_name__ = "BootcChoiceEntry"

    img_choice = Gtk.Template.Child()

    def __init__(self, title, subtitle, icon_name, **kwargs):
        super().__init__(**kwargs)
        self.set_title(title)
        self.set_subtitle(subtitle)
        self.img_choice.set_from_icon_name(icon_name)


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/widget-choice-expander.ui")
class BootcChoiceExpanderEntry(Adw.ExpanderRow):
    __gtype_name__ = "BootcChoiceExpanderEntry"

    img_choice = Gtk.Template.Child()

    def __init__(self, title, subtitle, icon_name, **kwargs):
        super().__init__(**kwargs)
        self.set_title(title)
        self.set_subtitle(subtitle)
        self.img_choice.set_from_icon_name(icon_name)




@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/confirm.ui")
class BootcConfirm(Adw.Bin):
    __gtype_name__ = "BootcConfirm"
    __gsignals__ = {
        "installation-confirmed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    group_warning = Gtk.Template.Child()
    row_warning = Gtk.Template.Child()
    group_changes = Gtk.Template.Child()
    group_source = Gtk.Template.Child()
    group_reuse = Gtk.Template.Child()
    group_plan = Gtk.Template.Child()
    btn_confirm = Gtk.Template.Child()
    lbl_body = Gtk.Template.Child()
    page_header = Gtk.Template.Child()

    # The source check (#266): each visit starts one, and a reply for an
    # older visit is dropped (the generation, then the reader's own
    # source/target binding). Class defaults, so that a view built without
    # __init__ (the unit tests) has them too.
    _source_generation = 0
    _source_rows = ()
    _source_blocked = False
    # The install source (#267): the item of this computer's bootc storage
    # that may replace the download (None when there is none), whether the
    # user chose it, and fisherman's problems with that choice.
    _reuse_source = None
    _reuse_selected = False
    _reuse_widgets = ()
    _reuse_problems = ()
    _reuse_check = None
    # The install plan (tuna-os/fisherman#371): fisherman's own account of
    # what the install destroys and which disk it writes to. Each visit
    # asks once; a reply for an older visit is dropped. `_plan` is the plan
    # of this visit when fisherman gave a valid one, else None: the page
    # then works as it did before plans, and the install is not bound.
    _plan_generation = 0
    _plan = None
    _plan_invalid = False
    _plan_widgets = ()
    _plan_request = staticmethod(request_plan)
    _plan_start = staticmethod(lambda fn: threading.Thread(target=fn, daemon=True).start())

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.delta = False
        self._hostname_entry_row = None
        self._hostname_check = None
        # Connected once. update() used to connect a handler on each visit
        # and the click removed only the newest, so three visits and one
        # click started fisherman twice (#308).
        self._armed = False
        self.btn_confirm.connect("clicked", self.__on_confirm)

    def update(self, finals):
        self._hostname_entry_row = None  # reset on every update
        self._hostname_check = None
        try:
            for widget in self.active_widgets:
                self.group_changes.remove(widget)
        except AttributeError:
            pass
        self.active_widgets = []

        selected_language = None
        # The facts every frontend's summary leads with, in the order KDE,
        # COSMIC and Niri list them: Target disk, Filesystem, Encryption,
        # Hostname, Image. GNOME's extra steps (language, keyboard, timezone,
        # users) and the GPU follow them, in step order.
        primary = {"disk": [], "filesystem": [], "encryption": [],
                   "hostname": [], "image": []}
        erase_disk = None
        erase_disk_removable = False
        var_disk_row = None
        var_disk_erased = None

        for final in finals:
            for key, value in final.items():
                # The language, keyboard and time zone rows are the
                # recipe's `locale`, `keyboard` and `timezone` (#292): a row
                # for each value the install writes, none for the others.
                if key == "language" and value:
                    selected_language = value
                    self.active_widgets.append(
                        BootcChoiceEntry(
                            _("Language"), value, "preferences-desktop-locale-symbolic"
                        )
                    )
                elif key == "keyboard":
                    summary = keyboard_summary(value)
                    if summary:
                        self.active_widgets.append(
                            BootcChoiceEntry(
                                _("Keyboard"), summary, "input-keyboard-symbolic"
                            )
                        )
                elif key == "timezone" and isinstance(value, str) and value:
                    self.active_widgets.append(
                        BootcChoiceEntry(
                            _("Time zone"),
                            value,
                            "preferences-system-time-symbolic",
                        )
                    )
                elif key == "user":
                    # The user step emits `user`. This read `users`, so the
                    # account never reached the summary (#313).
                    account = user_summary(value)
                    if account:
                        self.active_widgets.append(
                            BootcChoiceEntry(
                                _("Users"),
                                account,
                                "system-users-symbolic",
                            )
                        )
                elif key == "var_disk":
                    # A second disk for /var is formatted too, unless the
                    # user keeps it (#313).
                    summary, erased = var_disk_summary(value)
                    if summary:
                        var_disk_row = BootcChoiceEntry(
                            _("/var disk"),
                            summary,
                            "drive-harddisk-symbolic",
                        )
                        if erased:
                            var_disk_erased = value["disk"]
                elif key == "disk":
                    if "auto" in value:
                        auto = value["auto"]
                        erase_disk = auto.get("disk", "")
                        erase_disk_removable = bool(auto.get("removable", False))
                        primary["disk"].append(
                            BootcChoiceEntry(
                                _("Target disk"),
                                disk_summary(auto),
                                "drive-harddisk-system-symbolic",
                            )
                        )
                        fs = value.get("filesystem")
                        if fs:
                            primary["filesystem"].append(
                                BootcChoiceEntry(
                                    _("Filesystem"),
                                    filesystem_label(
                                        fs, lambda key: copy_text.text(self.__window, key)),
                                    "drive-multidisk-symbolic",
                                )
                            )
                    else:
                        disks = {}
                        # block, device_block
                        for part, info in value.items():
                            if not isinstance(info, dict):
                                continue
                            part_disk = re.match(
                                "^/dev/[a-zA-Z]+([0-9]+[a-z][0-9]+)?",
                                part,
                                re.MULTILINE,
                            )[0]
                            if part_disk not in disks:
                                disks[part_disk] = BootcChoiceExpanderEntry(
                                    _("Target disk"),
                                    part_disk,
                                    "drive-harddisk-system-symbolic",
                                )
                                primary["disk"].append(disks[part_disk])

                            disks[part_disk].add_row(
                                BootcChoiceEntry(
                                    part,
                                    f"{info['fs']} {info['mp']} ({info['pretty_size']})",
                                    "drive-harddisk-system-symbolic",
                                )
                            )
                elif key == "encryption":
                    enc_type = value.get("type", "none") if isinstance(value, dict) else str(value)
                    # The shared copy key (encryption_<type>_label), so this row
                    # uses the same words as the encryption page and the other
                    # frontends' confirm pages.
                    label = copy_text.encryption_text(self.__window, enc_type, "_label") or enc_type
                    primary["encryption"].append(
                        BootcChoiceEntry(
                            _("Encryption"),
                            label,
                            "channel-secure-symbolic",
                        )
                    )
                elif key == "hostname":
                    entry_row = Adw.EntryRow()
                    entry_row.set_title(_("Hostname"))
                    entry_row.set_text(value or "")
                    entry_row.set_show_apply_button(False)
                    self._hostname_entry_row = entry_row
                    primary["hostname"].append(entry_row)
                    # An edit here is the hostname that gets installed, so
                    # fisherman checks it as the disk page's field is.
                    # A row of its own, under the entry, like the summary.
                    message = Adw.ActionRow()
                    message.set_use_markup(False)
                    message.set_title_lines(0)
                    message.add_css_class("error")
                    primary["hostname"].append(message)
                    self._hostname_check = FieldCheck(
                        self.__window, entry_row, "hostname",
                        lambda text: {"hostname": text.strip()},
                        message, on_change=self.__on_hostname_checked)
                elif key == "selected_image" and value:
                    pn = final.get("pretty_name") or value
                    primary["image"].append(
                        BootcChoiceEntry(
                            _("Image"),
                            pn,
                            "application-x-appliance-symbolic",
                        )
                    )
                elif key == "custom_image" and value:
                    primary["image"].append(
                        BootcChoiceEntry(
                            _("Image"),
                            value,
                            "image-missing-symbolic"
                        )
                    )

        if var_disk_row is not None:
            primary["disk"].append(var_disk_row)

        # No image step (live media, or a recipe with one image): the image
        # is the one the recipe names, resolved as Processor does.
        recipe = getattr(self.__window, "recipe", None)
        recipe = recipe if isinstance(recipe, dict) else {}
        if not primary["image"]:
            imgref = recipe_image(recipe)
            if imgref:
                primary["image"].append(
                    BootcChoiceEntry(
                        _("Image"),
                        imgref,
                        "application-x-appliance-symbolic",
                    )
                )

        # The image that is installed is not always the one chosen: a
        # catalog entry with an NVIDIA variant installs that variant on a
        # machine with an NVIDIA GPU, or from live media that carries only
        # it. The row then names what is written to the disk, and a second
        # row names what updates follow when that differs (#314).
        try:
            plan = Processor.image_plan(finals, recipe)
        except (AttributeError, KeyError, TypeError, ValueError):
            plan = None
        if plan and plan["install"] and plan["install"] != plan["selected"]:
            primary["image"] = [
                BootcChoiceEntry(
                    _("Image"),
                    plan["install"],
                    "application-x-appliance-symbolic",
                )
            ]
            if plan["track"] and plan["track"] != plan["install"]:
                primary["image"].append(
                    BootcChoiceEntry(
                        _("Updates follow"),
                        plan["track"],
                        "software-update-available-symbolic",
                    )
                )

        extras = self.active_widgets
        self.active_widgets = [w for rows in primary.values() for w in rows]
        self.active_widgets.extend(extras)

        # Hardware-detected GPU badge (always shown if a GPU is found)
        from bootc_installer.core.system import Systeminfo
        gpu_label = Systeminfo.gpu_display_string()
        if gpu_label:
            gpu_icon = Systeminfo.gpu_icon_name()
            self.active_widgets.append(
                BootcChoiceEntry(
                    _("Graphics"),
                    gpu_label,
                    gpu_icon,
                )
            )

        # Destructive action warning: the branding contract's confirm_warning,
        # with {disk} filled in, in a row of its own above the summary. Plain
        # text, not markup -- the line can come from a product's branding
        # file. Unlike other copy keys an empty line does not hide it: a
        # whole-disk erase is always announced. A removable disk (#251: USB
        # stick or other external drive, flagged by fisherman's probe) gets
        # confirm_warning_removable instead, so the one moment that commits
        # to erasing it says so plainly.
        # A second disk for /var that is formatted is named too (#313): in
        # the same sentence, or in a sentence of its own after the
        # removable-drive line, which is about one disk.
        fallback = _("All data on this disk will be erased. This cannot be undone.")
        parts = []
        if erase_disk and erase_disk_removable:
            parts.append(copy_text.text(
                self.__window, "confirm_warning_removable", disk=erase_disk) or fallback)
            if var_disk_erased:
                parts.append(copy_text.text(
                    self.__window, "confirm_warning", disk=var_disk_erased) or fallback)
        elif erase_disk or var_disk_erased:
            parts.append(copy_text.text(
                self.__window, "confirm_warning",
                disk=erased_disks_text([erase_disk, var_disk_erased])) or fallback)
        warning = " ".join(parts)
        self.row_warning.set_title(warning)
        self.group_warning.set_visible(bool(warning))

        # Flavour text from the branding contract (shared/branding): a
        # locale-specific quote when the product ships one for the selected
        # language, else its confirm_subtitle; the body line and the button
        # label likewise. Nothing here names a product.
        self.page_header.title = copy_text.text(self.__window, "confirm_title")
        self.page_header.subtitle = copy_text.confirm_subtitle(self.__window, selected_language or "")
        body = copy_text.text(self.__window, "confirm_body")
        self.lbl_body.set_label(body)
        self.lbl_body.set_visible(bool(body))
        self.btn_confirm.set_label(copy_text.text(self.__window, "confirm_button") or _("Install"))

        for widget in self.active_widgets:
            self.group_changes.add(widget)
        self.__start_source_check()
        self.__update_confirm_button()
        # One confirmation for each visit to the page.
        self._armed = True

    def __start_source_check(self):
        """Ask fisherman what the selected source's bootc can do, off the
        UI thread. The probe gets the image references only; the recipe
        that names them is built here and dropped (it holds the
        passphrase)."""
        self._source_generation += 1
        generation = self._source_generation
        self._source_blocked = False
        # No plan of an earlier visit or source may bind this install.
        self.__clear_plan()
        window = self.__window
        try:
            from bootc_installer.core.system import Systeminfo
            recipe = Processor.gen_install_recipe(
                "", getattr(window, "finals", []) or [], getattr(window, "recipe", {}) or {})
            self.__update_reuse(Systeminfo.probe(), recipe)
            recipe = self.apply_source(recipe)
            self.__start_plan(self.__with_hostname(recipe))
            req = source_check.recipe_request(recipe, Systeminfo.is_live())
            del recipe
        except Exception as exc:  # noqa: BLE001 - the install refuses it with its own message
            logger.info("no source check: %s", exc)
            self.__show_source_rows([])
            return
        args = source_check.probe_args(req)
        if not args:
            self.__show_source_rows([])
            return
        self.__show_source_rows(source_check.rows(None, None, self.__text))

        def work():
            result = Systeminfo.probe_source(args)
            GLib.idle_add(self.__on_source_reply, generation, req, result)

        threading.Thread(target=work, daemon=True).start()

    def __on_source_reply(self, generation, req, result):
        if generation != self._source_generation:
            return False
        view = source_check.source_check(result, req)
        if view["state"] == "stale":
            return False
        self._source_blocked = source_check.blocks_install(view)
        self.__show_source_rows(source_check.rows(
            view, source_check.bootc_store(result), self.__text,
            reuse=self.reuse_selected))
        self.__update_confirm_button()
        return False

    def __text(self, key):
        return copy_text.text(self.__window, key)

    def __show_source_rows(self, rows):
        for row in self._source_rows:
            self.group_source.remove(row)
        self._source_rows = []
        for title, subtitle in rows:
            row = Adw.ActionRow()
            row.set_use_markup(False)
            row.set_title_lines(0)
            row.set_subtitle_lines(0)
            row.set_title(title)
            row.set_subtitle(subtitle)
            self.group_source.add(row)
            self._source_rows.append(row)
        self.group_source.set_visible(bool(rows))

    @property
    def reuse_selected(self):
        """The user chose to copy this computer's system (#267)."""
        return bool(self._reuse_selected and self._reuse_source)

    def apply_source(self, recipe):
        """`recipe` with the install source that this page selected: the
        same recipe for the download, or one with `sourceReuse`, the
        `bootc_store_reuse` opt-in, an empty `image` and the catalog's
        update reference as `targetImgref`."""
        if not self.reuse_selected:
            return recipe
        return source_check.apply_reuse(recipe, self._reuse_source)

    def __update_reuse(self, probe, recipe):
        """Offer this computer's system as a second install source when
        fisherman's probe has an item that qualifies. The download stays
        selected until the user picks the item; a different item, or none,
        drops the choice."""
        update_ref = recipe.get("targetImgref") or recipe.get("image") or ""
        source = source_check.reuse_source(probe, update_ref)
        if not source or (self._reuse_source or {}).get("digest") != source["digest"]:
            self._reuse_selected = False
            self._reuse_problems = ()
        self._reuse_source = source
        self.__show_reuse_rows(update_ref)
        if self.reuse_selected:
            self.__check_reuse(recipe)

    def __show_reuse_rows(self, update_ref):
        for widget in self._reuse_widgets:
            self.group_reuse.remove(widget)
        self._reuse_widgets = []
        rows = source_check.reuse_rows(self._reuse_source, update_ref, self.__text)
        self.group_reuse.set_title(self.__text("source_reuse_title") if rows else "")
        group = None
        for key, title, detail in rows:
            row = Adw.ActionRow()
            row.set_use_markup(False)
            row.set_title_lines(0)
            row.set_subtitle_lines(0)
            row.set_title(title)
            row.set_subtitle(detail)
            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            if group is None:
                group = check
            else:
                check.set_group(group)
            check.set_active((key == "local") == self.reuse_selected)
            check.connect("toggled", self.__on_reuse_toggled, key)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self.group_reuse.add(row)
            self._reuse_widgets.append(row)
        for problem in self._reuse_problems:
            row = Adw.ActionRow()
            row.set_use_markup(False)
            row.set_title_lines(0)
            row.add_css_class("error")
            row.set_title(problem)
            self.group_reuse.add(row)
            self._reuse_widgets.append(row)
        self.group_reuse.set_visible(bool(rows))

    def __on_reuse_toggled(self, check, key):
        if not check.get_active() or (key == "local") == self.reuse_selected:
            return
        self._reuse_selected = key == "local"
        self._reuse_problems = ()
        self.__update_confirm_button()
        # After the signal: the check runs again and rebuilds these rows.
        GLib.idle_add(self.__restart_source_check)

    def __restart_source_check(self):
        self.__start_source_check()
        self.__update_confirm_button()
        return False

    def __check_reuse(self, recipe):
        """`fisherman validate --json --partial -` for the reuse fields;
        each problem shows in the words of `validate_<code>`, and holds
        Install."""
        if self._reuse_check is None:
            from bootc_installer.utils.field_check import _glib_live_check
            self._reuse_check = _glib_live_check(self.__on_reuse_checked)
        self._reuse_check.submit(source_check.reuse_fragment(
            source_check.apply_reuse(recipe, self._reuse_source)))

    def __on_reuse_checked(self, problems, error):
        if error is not None:
            logger.warning("fisherman validate could not run: %s", error)
            problems = []
        if not self.reuse_selected:
            return
        from bootc_shared import validate as fisherman_validate
        self._reuse_problems = tuple(
            fisherman_validate.render(p, self.__text) for p in problems or [])
        self.__show_reuse_rows(self._reuse_source["ref"])
        self.__update_confirm_button()

    def __with_hostname(self, recipe):
        """`recipe` with the hostname typed on this page, as the window
        writes it at confirmation."""
        override = self.get_hostname_override()
        if override and isinstance(recipe, dict) and "hostname" in recipe:
            recipe = dict(recipe, hostname=override)
        return recipe

    def __plan_text(self, key, **values):
        return copy_text.text(self.__window, key, **values)

    def __clear_plan(self):
        """Forget the plan; a reply that is still on its way is dropped."""
        self._plan_generation += 1
        self._plan = None
        self._plan_invalid = False
        self.__show_plan_rows([])

    def __start_plan(self, recipe):
        """Ask `fisherman plan --json -` about the recipe the install will
        use, off the UI thread. The recipe goes to fisherman on stdin; the
        worker drops it with its answer."""
        self.__clear_plan()
        generation = self._plan_generation
        request = self._plan_request

        def work():
            answer = request(recipe)
            GLib.idle_add(self.__on_plan_reply, generation, answer)

        self._plan_start(work)

    def __on_plan_reply(self, generation, answer):
        if generation != self._plan_generation:
            return False
        result, error = answer
        if error is not None:
            # An older fisherman has no plan; the page works as before.
            logger.info("no install plan: %s", error)
            return False
        if not result.get("valid"):
            # The field checks name the problem; the install refuses it.
            codes = sorted({str(e.get("code", "")) for e in result.get("errors") or []
                            if isinstance(e, dict)})
            logger.info("fisherman plan refused the recipe: %s", ", ".join(codes))
            self._plan_invalid = True
            return False
        self._plan = result["plan"]
        logger.info("install plan: %d device(s) destroyed, disk identity %s",
                    len(install_plan.destroys(self._plan)),
                    sorted(install_plan.disk_identity(self._plan)) or "unknown")
        self.__show_plan_rows(install_plan.rows(self._plan, self.__plan_text))
        return False

    def __show_plan_rows(self, rows):
        for row in self._plan_widgets:
            self.group_plan.remove(row)
        self._plan_widgets = []
        for title, subtitle in rows:
            row = Adw.ActionRow()
            row.set_use_markup(False)
            row.set_title_lines(0)
            row.set_subtitle_lines(0)
            row.set_title(title)
            row.set_subtitle(subtitle)
            self.group_plan.add(row)
            self._plan_widgets.append(row)
        self.group_plan.set_title(self.__plan_text("confirm_plan_title") if rows else "")
        self.group_plan.set_visible(bool(rows))

    def __on_hostname_checked(self):
        self.__update_confirm_button()
        # A plan that fisherman refused for the hostname is asked again
        # once the hostname passes.
        if self._plan_invalid and self._hostname_check is not None and self._hostname_check.ok:
            self.__restart_plan()

    def __restart_plan(self):
        window = self.__window
        try:
            recipe = self.apply_source(Processor.gen_install_recipe(
                "", getattr(window, "finals", []) or [], getattr(window, "recipe", {}) or {}))
        except Exception as exc:  # noqa: BLE001 - the install refuses it with its own message
            logger.info("no install plan: %s", exc)
            return
        self.__start_plan(self.__with_hostname(recipe))

    @property
    def install_plan(self):
        """fisherman's plan for this visit, or None."""
        return self._plan

    def bind_disk(self, recipe):
        """`recipe` bound to the disk that the plan on this page showed:
        with `diskIdentity` (the serial, WWN and size that fisherman
        reported), so that fisherman refuses the install if another device
        is at that path (`disk_identity_mismatch`). `recipe` unchanged when
        there is no plan, when the plan is for another disk, or when the
        disk reports nothing to bind to."""
        if self._plan is None:
            return recipe
        return install_plan.bind(recipe, self._plan)

    def __update_confirm_button(self):
        self.btn_confirm.set_sensitive(
            (self._hostname_check is None or self._hostname_check.ok)
            and not self._source_blocked
            and not (self.reuse_selected and self._reuse_problems))

    def test_auto_advance(self):
        self.btn_confirm.emit("clicked")

    def get_hostname_override(self):
        """Return the hostname the user typed on the confirm screen, or None.

        Returns None if the confirm screen was never shown a hostname field
        (e.g. the disk step is hidden or no hostname was in finals).
        """
        if self._hostname_entry_row is None:
            return None
        text = self._hostname_entry_row.get_text().strip()
        return text if text else None

    def __on_confirm(self, widget):
        if not self._armed:
            return
        self._armed = False
        self.emit("installation-confirmed")

    def rearm(self):
        """Accept one more click: the window calls this when it refused to
        start (an invalid recipe, no disk), so the user can correct the
        problem on this page and confirm again."""
        self._armed = True
