# progress.py
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

import json
import logging
import os
import pathlib
import subprocess
import threading
import time
from gettext import gettext as _

from bootc_installer.utils import copy as copy_text
from bootc_installer.utils import fisherman_runner


logger = logging.getLogger("Installer::Progress")

_IN_FLATPAK = fisherman_runner.IN_FLATPAK
_LIVE_ISO = fisherman_runner.LIVE_ISO
_RESOURCE_PREFIX = "/org/bootcinstaller/Installer"
_ASSET_DIR = pathlib.Path(__file__).resolve().parent.parent / "assets"

# Where to stage fisherman so the host can see it (shared via --filesystem=host)
#
# The fallback used to be "/tmp", which put the staging directory — and so the
# binary this module goes on to run under pkexec — somewhere every local user
# on the machine can write. Fall back to the per-user runtime directory
# instead: /run/user/<uid> is created 0700 and owned by the user, so the
# HOME-unset case degrades to "private to us" rather than "world-writable".
_FISHERMAN_STAGE_BASE = fisherman_runner.default_stage_base()
_FISHERMAN_CACHE_DIR = os.path.join(_FISHERMAN_STAGE_BASE, ".cache", "bootc-installer")
_FISHERMAN_HOST_PATH = os.path.join(_FISHERMAN_CACHE_DIR, "fisherman")
_FISHERMAN_LOG_PATH = os.path.join(_FISHERMAN_CACHE_DIR, "fisherman-output.log")

from bootc_installer.utils.progress_parser import apply_progress_event, new_progress_state, set_product_name, set_install_label, get_product_name, _RE_LAYER_PROGRESS  # noqa: E402
from bootc_installer.utils.codec_check import check_codecs_present  # noqa: E402


def _media_stream_is_prepared(media_stream) -> bool:
    return media_stream is not None and media_stream.is_prepared()


def _fisherman_argv_direct(recipe: str) -> list:
    """Build an argv that captures fisherman stdout+stderr into the log file.

    For Flatpak: run bash on the HOST via flatpak-spawn so the shell redirect
    happens where fisherman actually runs. If we redirect inside the sandbox,
    flatpak-spawn's D-Bus proxy doesn't forward the host process stdout back
    through the redirect — the log file stays empty even though fisherman runs.
    """
    return fisherman_runner.build_argv(
        recipe,
        in_flatpak=_IN_FLATPAK,
        live_iso=_LIVE_ISO,
        host_path=_FISHERMAN_HOST_PATH,
        log_path=_FISHERMAN_LOG_PATH,
    )


def _path_is_private(path: str, check_mode: bool = True) -> bool:
    """True when `path` is safe to stage a pkexec target into.

    The staged binary is executed as root, so anything about its path that
    another account can influence is a privilege-escalation primitive. A path
    that does not exist yet is fine — we are about to create it, and
    `os.makedirs`/`shutil.copy2` below create with modes no one else can
    write. What must be rejected is a path that already exists and is NOT
    exclusively ours: a symlink someone else planted, a directory owned by
    another account, or anything group- or other-writable.

    `check_mode=False` skips the group/other-writable test, for paths we do
    not create and whose permissions are the user's own business — a home
    directory is 0775 under a user-private-group scheme on some distributions,
    and refusing to install over that would be a false positive. The
    directories this module creates are held to the full standard.

    This does NOT make staging safe against the invoking user's own uid —
    nothing checked here can, because the check and the eventual execve are
    separated by a window. It closes the pre-created-directory and cross-user
    cases, and turns the HOME-unset case into a refusal instead of a root
    exec. See the tracking issue for the structural fix.
    """
    return fisherman_runner.path_is_private(path, check_mode)


def _stage_fisherman_on_host() -> bool:
    """Copy fisherman binary to a host-visible cache dir so pkexec can find it."""
    return fisherman_runner.stage_on_host(
        in_flatpak=_IN_FLATPAK,
        stage_base=_FISHERMAN_STAGE_BASE,
        cache_dir=_FISHERMAN_CACHE_DIR,
        host_path=_FISHERMAN_HOST_PATH,
    )

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402



def _friendly_substep(msg: str) -> str:
    """Convert a raw fisherman substep message to human-friendly text.

    Called by __parse_progress_line() before setting progress_substep label.
    Unknown messages are returned as-is to preserve forward-compatibility.
    """
    m = _RE_LAYER_PROGRESS.match(msg)
    if m:
        done, total = m.group(1), m.group(2)
        return _("Downloading\u2026 (%s of %s parts)") % (done, total)
    if msg.startswith("Pulling container image"):
        return _("Downloading system image\u2026")
    if msg.startswith("Pulling image"):
        return _("Downloading system image\u2026")
    if "squash" in msg.lower() or "compress" in msg.lower():
        return _("Compressing\u2026")
    if "fstrim" in msg.lower() or "fsfreeze" in msg.lower():
        return _("Optimizing drive\u2026")
    return msg


@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/progress.ui")
class BootcProgress(Gtk.Box):
    __gtype_name__ = "BootcProgress"

    media_box = Gtk.Template.Child()
    install_video = Gtk.Template.Child()
    video_fallback_box = Gtk.Template.Child()
    fallback_dino = Gtk.Template.Child()
    fallback_store_qr = Gtk.Template.Child()
    lbl_store = Gtk.Template.Child()
    progressbar = Gtk.Template.Child()
    progressbar_text = Gtk.Template.Child()
    progress_percentage = Gtk.Template.Child()
    progress_elapsed = Gtk.Template.Child()
    progress_eta = Gtk.Template.Child()
    progress_substep = Gtk.Template.Child()
    progress_note = Gtk.Template.Child()
    console_button = Gtk.Template.Child()
    media_button = Gtk.Template.Child()
    console_box = Gtk.Template.Child()
    log_view = Gtk.Template.Child()
    copy_log_button = Gtk.Template.Child()

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        # Tell the parser what we are installing, so its step labels say the
        # product's name instead of a hardcoded one. Done here because this is
        # the first point the recipe is in hand; the parser itself stays free
        # of recipe and file IO.
        try:
            set_product_name(window.recipe.get("distro_name", ""))
        except Exception:
            pass  # labels fall back to the neutral default
        # The image-writing step's label is the branding contract's
        # progress_title, so a product can say what it is installing.
        set_install_label(copy_text.text(window, "progress_title"))
        self.__proc = None       # subprocess handle for fisherman
        self.__log_out = None    # open file handle for fisherman stdout/stderr
        self.__log_buf = None    # GtkTextBuffer — set after super().__init__
        self.__pulse_active = True  # whether the progress bar is in pulse mode
        self.__log_file = None      # open handle to fisherman-output.log for tailing
        self.__log_linebuf = ""     # incomplete line buffer for the log watcher
        self.__progress_state = new_progress_state()
        self.__boot_id = ""  # EFI boot entry ID from fisherman complete event
        self.__recovery_key = ""
        self.__recipe_path = None   # path to recipe JSON (for cleanup)
        self.__start_time = None
        self.__elapsed_timer_id = None
        self.__last_fraction = 0.0  # for ETA computation
        self._video_configured = False
        self._video_fallback_timeout_id = None

        self._video_tmp_path = None
        self._video_spinner = None
        self._media_overlay = None

        self.__build_ui()
        self.__log_buf = self.log_view.get_buffer()
        # "Do not power off the computer." Empty hides it.
        note = copy_text.text(window, "progress_note")
        self.progress_note.set_label(note)
        self.progress_note.set_visible(bool(note))

        self.console_button.connect("clicked", self.__on_console_button)
        self.media_button.connect("clicked", self.__on_media_button)
        self.copy_log_button.connect("clicked", self.__on_copy_log)


    def __configure_install_video(self):
        """Set up video playback."""
        self._video_file = None
        self.install_video.connect("notify::media-stream", self.__on_media_stream_changed)
        self.__hide_video_fallback()

        # Check if GStreamer VP9/AV1 decoders are available
        codecs = check_codecs_present()
        if not (codecs["vp9"] or codecs["av1"]):
            logger.warning("GStreamer VP9 or AV1 decoders not available. Video playback not available.")
            GLib.idle_add(self.__show_video_fallback)
            return

        self.__arm_video_fallback_timeout()
        threading.Thread(target=self.__extract_and_play_video, daemon=True).start()

    def __on_video_widget_realized(self, *_):
        pass  # unused — kept for safety if connected externally

    def __extract_and_play_video(self):
        """Play the branding's install video (a host path, or a GResource path
        extracted to a temp file). No video configured means the fallback
        panel, not somebody else's film."""
        import tempfile
        try:
            spec = self.__window.recipe.get("install_video", "") if isinstance(
                getattr(self.__window, "recipe", None), dict) else ""
            if not spec:
                raise FileNotFoundError("no install_video in the branding")
            if spec.startswith("/org/"):
                data = Gio.resources_lookup_data(spec, Gio.ResourceLookupFlags.NONE)
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".webm", prefix="bootc-installer-video-", delete=False
                )
                tmp.write(data.get_data())
                tmp.flush()
                tmp.close()
                self._video_tmp_path = tmp.name
                video_file = Gio.File.new_for_path(tmp.name)
            else:
                if not os.path.exists(spec):
                    raise FileNotFoundError(spec)
                video_file = Gio.File.new_for_path(spec)

            def _done():
                self._video_file = video_file
                # GTK4 gtk_video_set_file() handles both cases:
                #   realized   → starts GStreamer immediately
                #   unrealized → stores file; gtk_video_realize() starts it later
                self.install_video.set_file(video_file)
                return False

            GLib.idle_add(_done)
        except Exception as e:
            logger.warning("Failed to extract installer video: %s", e)
            GLib.idle_add(self.__show_video_fallback)

    def __on_media_stream_changed(self, *_args):
        """Called when the Gtk.Video gets its MediaStream. Hook into prepared
        notification to defer mute until GstPlayer is actually ready."""
        media_stream = self.install_video.get_media_stream()
        if media_stream is None:
            return
        if _media_stream_is_prepared(media_stream):
            self.__cancel_video_fallback_timeout()
            self.__hide_video_fallback()
            GLib.idle_add(self.__mute_install_video)
        else:
            media_stream.connect("notify::prepared", self.__on_media_prepared)
            media_stream.connect("notify::error", self.__on_media_error)
            self.__arm_video_fallback_timeout()

    def __on_media_prepared(self, media_stream, *_args):
        if _media_stream_is_prepared(media_stream):
            self.__cancel_video_fallback_timeout()
            self.__hide_video_fallback()
            GLib.idle_add(self.__mute_install_video)

    def __on_media_error(self, media_stream, *_args):
        err = media_stream.get_error()
        logger.warning("Media stream error: %s", err)
        self.__cancel_video_fallback_timeout()
        self.__show_video_fallback()

    def __mute_install_video(self):
        media_stream = self.install_video.get_media_stream()
        if _media_stream_is_prepared(media_stream):
            media_stream.set_muted(True)

    def __play_install_video(self):
        media_stream = self.install_video.get_media_stream()
        if _media_stream_is_prepared(media_stream):
            media_stream.play()
            media_stream.set_muted(True)

    def __pause_install_video(self):
        media_stream = self.install_video.get_media_stream()
        if _media_stream_is_prepared(media_stream):
            media_stream.pause()

    def __arm_video_fallback_timeout(self):
        self.__cancel_video_fallback_timeout()
        self.__show_video_spinner()
        self._video_fallback_timeout_id = GLib.timeout_add_seconds(15, self.__on_video_prepare_timeout)

    def __cancel_video_fallback_timeout(self):
        self.__hide_video_spinner()
        if self._video_fallback_timeout_id is not None:
            context = GLib.MainContext.default()
            if context is not None and context.find_source_by_id(self._video_fallback_timeout_id):
                GLib.source_remove(self._video_fallback_timeout_id)
            self._video_fallback_timeout_id = None

    def __on_video_prepare_timeout(self):
        if not _media_stream_is_prepared(self.install_video.get_media_stream()):
            logger.warning("Install video was not prepared in time; showing fallback")
            self.__show_video_fallback()
        self._video_fallback_timeout_id = None
        return False

    def __show_video_fallback(self):
        self.__hide_video_spinner()
        self.video_fallback_box.set_visible(True)
        self.__pause_install_video()

    def __hide_video_fallback(self):
        self.video_fallback_box.set_visible(False)

    def __show_selected_media_view(self):
        self.console_box.set_visible(False)
        self.media_button.set_visible(False)
        self.console_button.set_visible(True)
        self.media_box.set_visible(True)
        self.__play_install_video()

    def __show_media_view(self):
        self.__show_selected_media_view()

    def __show_console_view(self):
        self.media_box.set_visible(False)
        self.console_box.set_visible(True)
        self.media_button.set_visible(True)
        self.console_button.set_visible(False)
        self.__pause_install_video()

    def __on_console_button(self, *args):
        self.__show_console_view()

    def __on_media_button(self, *args):
        self.__show_selected_media_view()

    def __on_copy_log(self, *args):
        """Copy the fisherman log to the clipboard."""
        try:
            with open(_FISHERMAN_LOG_PATH) as f:
                text = f.read()
        except OSError:
            text = self.__log_buf.get_text(
                self.__log_buf.get_start_iter(),
                self.__log_buf.get_end_iter(),
                False,
            )
        if not text:
            return
        try:
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set(text)
        except Exception as e:
            logger.error("Failed to copy log: %s", e)
            return
        self.copy_log_button.set_icon_name("emblem-ok-symbolic")
        GLib.timeout_add(1500, lambda: self.copy_log_button.set_icon_name("edit-copy-symbolic"))

    def __build_ui(self):
        self.__install_progress_css()
        self.__setup_fallback_panel()

    def __setup_fallback_panel(self):
        """Populate the video-unavailable fallback panel with the dino image and store QR."""
        recipe = self.__window.recipe

        # Artwork and store come from the branding contract (via the recipe
        # overlay); with none configured the panel shows the product logo and
        # no store. Nothing here names a product.
        from bootc_installer.utils import copy as copy_text
        art = (
            recipe.get("tour", {}).get("welcome", {}).get("image", "")
            if isinstance(recipe.get("tour"), dict)
            else ""
        )
        if art and art.startswith("/org/"):
            self.fallback_dino.set_resource(art)
        elif art and os.path.exists(art):
            self.fallback_dino.set_filename(art)
        else:
            self.fallback_dino.set_visible(False)

        qr_resource = recipe.get("store_qr_resource", "")
        if recipe.get("store_url") and qr_resource:
            if qr_resource.startswith("/org/"):
                self.fallback_store_qr.set_resource(qr_resource)
            else:
                self.fallback_store_qr.set_filename(qr_resource)
            self.lbl_store.set_label(copy_text.text(self.__window, "store_label"))
        else:
            self.fallback_store_qr.set_visible(False)
            self.lbl_store.set_visible(False)

    def __show_video_spinner(self):
        pass

    def __hide_video_spinner(self):
        pass

    def __install_progress_css(self):
        display = Gdk.Display.get_default()
        if display is None:
            return
        css = Gtk.CssProvider()
        css.load_from_string(
            ".thick-progress trough, .thick-progress progress { min-height: 8px; }"
            " .thick-progress progress { transition: all 300ms ease-in-out; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            display,
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def __set_progress_fraction(self, fraction: float):
        fraction = max(0.0, min(fraction, 1.0))
        self.progressbar.set_fraction(fraction)
        self.progress_percentage.set_label(f"{int(fraction * 100)}%")
        self.__last_fraction = fraction
        self.__update_eta(fraction)

    def __format_elapsed(self, elapsed_seconds: float) -> str:
        total_seconds = max(0, int(elapsed_seconds))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def __update_eta(self, fraction: float):
        """Compute and display estimated time remaining."""
        if self.__start_time is None or fraction < 0.05:
            # Not enough data to estimate yet
            self.progress_eta.set_label("")
            return
        elapsed = time.monotonic() - self.__start_time
        if elapsed < 5:
            return  # wait at least 5s before showing ETA
        remaining = (elapsed / fraction) * (1.0 - fraction)
        remaining = max(0, int(remaining))
        if remaining < 60:
            eta_text = _("~%d sec remaining") % remaining
        else:
            minutes = remaining // 60
            eta_text = _("~%d min remaining") % minutes
        self.progress_eta.set_label(eta_text)

    def __update_elapsed_label(self):
        if self.__start_time is None:
            return False
        elapsed = self.__format_elapsed(time.monotonic() - self.__start_time)
        self.progress_elapsed.set_label(_("%s elapsed") % elapsed)
        # Also refresh ETA on the timer tick
        self.__update_eta(self.__last_fraction)
        return True

    def __start_elapsed_timer(self):
        self.__stop_elapsed_timer(clear_start_time=False)
        self.__start_time = time.monotonic()
        self.__update_elapsed_label()
        self.__elapsed_timer_id = GLib.timeout_add(1000, self.__update_elapsed_label)

    def __stop_elapsed_timer(self, clear_start_time: bool = True):
        if self.__elapsed_timer_id is not None:
            GLib.source_remove(self.__elapsed_timer_id)
            self.__elapsed_timer_id = None
        if clear_start_time:
            self.__start_time = None

    def __pulse_progress(self):
        if self.__pulse_active:
            self.progressbar.pulse()
        return self.__pulse_active

    def _start_log_watcher(self):
        """Begin tailing fisherman-output.log for JSON progress events.

        Polls until the file exists, then reads new data every 100ms.
        GLib.io_add_watch does not work on regular files (only pipes/sockets),
        so we use a timer-based poll instead.
        """
        self.__watcher_lines = 0
        logger.info("_start_log_watcher: scheduling try_open for %s", _FISHERMAN_LOG_PATH)
        GLib.timeout_add(200, self.__try_open_log_for_watching)

    def __try_open_log_for_watching(self) -> bool:
        exists = os.path.exists(_FISHERMAN_LOG_PATH)
        if not exists:
            return True  # retry
        try:
            self.__log_file = open(_FISHERMAN_LOG_PATH, "r")
            GLib.timeout_add(100, self.__poll_log_file)
            logger.info("Log watcher OPENED %s (pos=%d)", _FISHERMAN_LOG_PATH, self.__log_file.tell())
            return False  # stop retrying
        except OSError as e:
            logger.error("Log watcher open FAILED: %s", e)
            return True  # retry

    def __poll_log_file(self) -> bool:
        """Read any new data from the log file into the TextView. Runs every 100ms."""
        if self.__log_file is None:
            return False
        new_text = self.__log_file.read()
        if new_text:
            self.__log_linebuf += new_text
            lines = self.__log_linebuf.split("\n")
            self.__log_linebuf = lines[-1]
            for line in lines[:-1]:
                self.__watcher_lines += 1
                self.__parse_progress_line(line.strip())
                self.__append_log_line(line)
            if self.__watcher_lines <= 5 or self.__watcher_lines % 50 == 0:
                logger.info("Log watcher: %d lines appended to buffer (buf chars=%d)",
                            self.__watcher_lines, self.__log_buf.get_char_count())
        return True  # keep polling until __finish_install sets __log_file = None

    def __append_log_line(self, line: str):
        """Append a line to the TextView buffer and auto-scroll."""
        end = self.__log_buf.get_end_iter()
        self.__log_buf.insert(end, line + "\n")
        if self.console_box.get_visible():
            GLib.idle_add(self.__scroll_log_to_bottom)

    def __scroll_log_to_bottom(self):
        end = self.__log_buf.get_end_iter()
        self.log_view.scroll_to_iter(end, 0.0, False, 0.0, 1.0)
        return False

    def __poll_proc(self) -> bool:
        """Poll fisherman subprocess exit status every 500ms."""
        if self.__proc is None:
            return False
        ret = self.__proc.poll()
        if ret is None:
            return True  # still running
        # Give the log poller 300ms to drain any last bytes before finishing.
        GLib.timeout_add(300, self.__finish_install, ret)
        return False

    def __finish_install(self, ret: int) -> bool:
        """Final log drain then hand off to the done screen."""
        if self.__log_file:
            remaining = self.__log_file.read()
            if remaining:
                self.__log_linebuf += remaining
            lines = (self.__log_linebuf + "\n").split("\n")
            self.__log_linebuf = ""
            for line in lines:
                if line.strip():
                    self.__parse_progress_line(line.strip())
                    self.__append_log_line(line)
            self.__log_file.close()
            self.__log_file = None
        # Compute elapsed before stopping the timer
        elapsed_secs = 0
        if self.__start_time is not None:
            elapsed_secs = int(time.monotonic() - self.__start_time)
        self.__stop_elapsed_timer()
        self.__cancel_video_fallback_timeout()
        self.__pause_install_video()
        # Securely delete the recipe file — it contains plaintext passphrases
        # and passwords that must not persist on disk after install.
        self.__cleanup_recipe_file()
        self.__cleanup_video_tmp()
        self.__window.set_installation_result(
            ret == 0, None, self.__boot_id, self.__recovery_key, elapsed_secs
        )
        return False

    def __cleanup_recipe_file(self):
        """Remove the temporary recipe JSON file containing sensitive credentials."""
        recipe_path = getattr(self, "_BootcProgress__recipe_path", None)
        if not recipe_path:
            return
        try:
            os.unlink(recipe_path)
            logger.info("Deleted recipe file: %s", recipe_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Could not delete recipe file %s: %s", recipe_path, e)

    def __cleanup_video_tmp(self):
        """Remove the temp video file extracted from GResource."""
        if self._video_tmp_path:
            try:
                os.unlink(self._video_tmp_path)
            except OSError:
                pass
            self._video_tmp_path = None

    def __parse_progress_line(self, line: str):
        """Parse a single fisherman log line and apply any resulting UI update."""
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            event = {}

        update = apply_progress_event(line, self.__progress_state)
        if event.get("type") == "recovery_key":
            self.__recovery_key = self.__progress_state.get("recovery_key", "")
            logger.info("Fisherman reported recovery key")
        if update is None:
            return

        if update["fraction"] is not None:
            self.__set_progress_fraction(update["fraction"])
        if update["label"] is not None:
            self.progressbar_text.set_label(_(update["label"]))
        if event.get("type") == "step":
            self.progress_substep.set_label("")
        elif event.get("type") == "substep":
            raw_msg = event.get("message", "")
            self.progress_substep.set_label(_friendly_substep(raw_msg))
        if not update["pulse"]:
            self.__pulse_active = False

        if update["complete"]:
            self.__stop_elapsed_timer()
            self.__cancel_video_fallback_timeout()
            self.__pause_install_video()
            self.progress_substep.set_label("")
            self.__boot_id = self.__progress_state["boot_id"]
            self.__recovery_key = self.__progress_state.get("recovery_key", "")
            logger.info("Fisherman reported completion")
        elif update.get("label"):
            logger.info("UI update: %s (fraction=%.2f)", update["label"],
                        update["fraction"] if update["fraction"] is not None else -1)

    def configure_video_preview(self):
        """Configure video playback for the preview/demo mode (BOOTC_PREVIEW_SCREEN=progress).
        Called by main_window when the progress page is shown without a real install."""
        if not self._video_configured:
            self._video_configured = True
            self.__configure_install_video()

    def start_demo(self):
        """Fake install sequence for UI design / demo mode (BOOTC_DEMO=1).

        Walks through 9 steps over ~5 seconds, then calls set_installation_result.
        No fisherman is launched. No disk is touched.
        """
        logger.info("start_demo() called")
        installing = copy_text.text(self.__window, "progress_title") or \
            _("Installing {}\u2026").format(get_product_name())
        # Demo steps: (delay_seconds, bar_fraction, label)
        # Mirrors real-install proportions: disk prep is fast (<10%),
        # OS install dominates (~87% of bar, most of the time),
        # then a quick burst to 100% for apps + config.
        _STEPS = [
            (0.3,  0.01, "Checking your drive\u2026"),
            (0.6,  0.02, "Setting up your drive\u2026"),
            (0.9,  0.04, "Preparing the boot system\u2026"),
            (1.2,  0.05, "Formatting your drive\u2026"),
            (1.5,  0.06, "Mounting your drive\u2026"),
            (2.0,  0.10, installing),
            (3.5,  0.45, installing),
            (5.2,  0.86, installing),
            (5.8,  0.93, "Installing your apps\u2026"),
            (6.3,  0.97, "Configuring your system\u2026"),
            (6.8,  0.99, "Finishing up\u2026"),
        ]
        self.__pulse_active = False
        self.__set_progress_fraction(0.0)
        self.progress_substep.set_label("")
        self.progress_elapsed.set_label(_("0:00 elapsed"))
        self.__hide_video_fallback()
        self.__show_media_view()
        if not self._video_configured:
            self._video_configured = True
            self.__configure_install_video()

        def _fire_step(index):
            if index >= len(_STEPS):
                self.__set_progress_fraction(1.0)
                self.__pause_install_video()
                self.progress_substep.set_label("")
                self.progressbar_text.set_label(_("Installation complete!"))
                GLib.timeout_add(600, lambda: self.__window.set_installation_result(True, None, "") or False)
                return False
            _delay, fraction, label = _STEPS[index]
            self.__set_progress_fraction(fraction)
            self.progress_substep.set_label("")
            self.progressbar_text.set_label(_(label))
            return False

        for i, (delay, _frac, _label) in enumerate(_STEPS):
            GLib.timeout_add(int(delay * 1000), _fire_step, i)
        GLib.timeout_add(int((_STEPS[-1][0] + 0.6) * 1000), _fire_step, len(_STEPS))

    def start(self, recipe):
        # If VANILLA_FAKE was passed as argument
        if not recipe:
            self.__window.set_installation_result(False, None)
            return

        if not _stage_fisherman_on_host():
            self.__window.set_installation_result(False, None)
            return

        # Track the recipe path so we can securely delete it after install.
        # The recipe contains plaintext passphrases and passwords.
        self.__recipe_path = recipe

        argv = _fisherman_argv_direct(recipe)
        os.makedirs(_FISHERMAN_CACHE_DIR, exist_ok=True)
        # Remove any stale log file before launching so the watcher always opens
        # a fresh file at position 0. If the old file exists, bash's '>' redirect
        # truncates it but Python's file handle would still sit at the old EOF,
        # causing read() to return empty even though new content is present.
        try:
            os.unlink(_FISHERMAN_LOG_PATH)
            logger.info("Deleted stale log file: %s", _FISHERMAN_LOG_PATH)
        except FileNotFoundError:
            logger.info("No stale log file to delete")
        except Exception as e:
            logger.error("Failed to delete stale log: %s", e)
        self.__progress_state = new_progress_state()
        self.__boot_id = ""
        self.__recovery_key = ""
        self.__pulse_active = True
        self.__set_progress_fraction(0.0)
        self.progressbar_text.set_label(
            copy_text.text(self.__window, "progress_title") or _("Installing"))
        self.progress_substep.set_label("")
        self.__hide_video_fallback()
        self.__show_media_view()
        if not self._video_configured:
            self._video_configured = True
            self.__configure_install_video()
        GLib.timeout_add(200, self.__pulse_progress)
        logger.info("Launching fisherman: %s", argv)
        self.__start_elapsed_timer()
        # bash handles writing stdout+stderr to the log file via shell redirection.
        # Do NOT pass stdout= here — flatpak-spawn uses D-Bus, not a real pipe fd.
        self.__proc = subprocess.Popen(argv)
        logger.info("Fisherman PID: %s", self.__proc.pid)
        GLib.timeout_add(500, self.__poll_proc)
        self._start_log_watcher()

    def terminate(self):
        """Terminate fisherman if it is still running (e.g. window closed).

        This sends SIGTERM to the bash wrapper process group. fisherman's cleanup
        handler will attempt to unmount filesystems and close LUKS devices.
        """
        self.__stop_carousel_timer()
        self.__cancel_video_fallback_timeout()
        if self.__proc is None:
            return
        if self.__proc.poll() is not None:
            return
        logger.warning("Terminating fisherman (PID %s) due to window close", self.__proc.pid)
        try:
            import signal
            os.killpg(os.getpgid(self.__proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                self.__proc.terminate()
            except OSError as e:
                logger.debug("Could not terminate fisherman process: %s", e)
        self.__cleanup_recipe_file()
