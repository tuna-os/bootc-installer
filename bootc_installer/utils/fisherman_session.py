"""GTK-free fisherman process-lifecycle adapter.

Owns everything about running the privileged fisherman helper that is not
GTK: staging (delegated to fisherman_runner), argv construction (ditto),
launching and polling the subprocess, tailing its log file for new lines,
and securely deleting the recipe file once the install finishes.

`bootc_installer.views.progress.BootcProgress` is the GTK consumer: it owns
the widget state (progress bar, video, console) and the GLib timers that
call into this adapter, but it does not itself touch os.unlink, subprocess,
or file descriptors for the fisherman transport. That split is what makes
this module importable, and testable, without a display.

apply_progress_event() in progress_parser.py remains the protocol-translation
boundary; this module only decides *when* to hand it a line, not how to
interpret one.
"""

import logging
import os
import signal

from bootc_installer.utils import fisherman_runner

logger = logging.getLogger("Installer::FishermanSession")


class FishermanSession:
    """Runs one fisherman install, from launch to log drain to cleanup.

    Callers (a GTK widget, a headless test, an alternative frontend) drive
    this with their own scheduling — poll_process() and read_new_lines() are
    meant to be called from a timer, but this class does not start one.
    """

    def __init__(
        self,
        recipe_path: str,
        *,
        in_flatpak: bool = fisherman_runner.IN_FLATPAK,
        live_iso: bool = fisherman_runner.LIVE_ISO,
        stage_base: str = fisherman_runner.STAGE_BASE,
        cache_dir: str = fisherman_runner.CACHE_DIR,
        host_path: str = fisherman_runner.HOST_PATH,
        log_path: str = fisherman_runner.LOG_PATH,
        popen=None,
    ):
        self.recipe_path = recipe_path
        self._in_flatpak = in_flatpak
        self._live_iso = live_iso
        self._stage_base = stage_base
        self._cache_dir = cache_dir
        self._host_path = host_path
        self.log_path = log_path
        # Injectable for tests; defaults to the real subprocess.Popen.
        if popen is None:
            import subprocess
            popen = subprocess.Popen
        self._popen = popen

        self.proc = None
        self._log_file = None
        self._log_linebuf = ""

    def stage(self) -> bool:
        """Copy fisherman to a host-visible location, if running in Flatpak."""
        return fisherman_runner.stage_on_host(
            in_flatpak=self._in_flatpak,
            stage_base=self._stage_base,
            cache_dir=self._cache_dir,
            host_path=self._host_path,
        )

    def _reset_log_file(self):
        """Remove any stale log so a fresh open always starts at position 0.

        bash's '>' redirect truncates an existing file, but a Python handle
        opened before that truncation would still sit at the old EOF and
        read() would return empty even though new content is present.
        """
        try:
            os.unlink(self.log_path)
            logger.info("Deleted stale log file: %s", self.log_path)
        except FileNotFoundError:
            logger.info("No stale log file to delete")
        except OSError as e:
            logger.error("Failed to delete stale log: %s", e)

    def launch(self):
        """Stage fisherman if needed, then start it. Returns argv used, or None on staging failure."""
        if not self.stage():
            return None
        os.makedirs(self._cache_dir, exist_ok=True)
        self._reset_log_file()
        argv = fisherman_runner.build_argv(
            self.recipe_path,
            in_flatpak=self._in_flatpak,
            live_iso=self._live_iso,
            host_path=self._host_path,
            log_path=self.log_path,
        )
        logger.info("Launching fisherman: %s", argv)
        # bash handles writing stdout+stderr to the log file via shell
        # redirection. Do NOT pass stdout= here — flatpak-spawn uses D-Bus,
        # not a real pipe fd, so a Python-side pipe would never fill.
        self.proc = self._popen(argv)
        logger.info("Fisherman PID: %s", self.proc.pid)
        return argv

    def poll_process(self):
        """Return the exit code if fisherman has finished, else None."""
        if self.proc is None:
            return None
        return self.proc.poll()

    def open_log_for_tailing(self) -> bool:
        """Try to open the log file for tailing. Returns False if it does not exist yet (retry)."""
        if self._log_file is not None:
            return True
        if not os.path.exists(self.log_path):
            return False
        try:
            self._log_file = open(self.log_path, "r")  # noqa: SIM115 - kept open across polls, closed in drain_remaining()
            logger.info("Log watcher OPENED %s (pos=%d)", self.log_path, self._log_file.tell())
            return True
        except OSError as e:
            logger.error("Log watcher open FAILED: %s", e)
            return False

    def read_new_lines(self) -> list[str]:
        """Read any newly-written complete lines from the log file.

        Incomplete trailing data is buffered until the next call. Returns []
        if the log file is not open or has no new complete lines.
        """
        if self._log_file is None:
            return []
        new_text = self._log_file.read()
        if not new_text:
            return []
        self._log_linebuf += new_text
        lines = self._log_linebuf.split("\n")
        self._log_linebuf = lines[-1]
        return lines[:-1]

    def drain_remaining(self) -> list[str]:
        """Read whatever is left (including a final unterminated line) and close the log.

        Call once after poll_process() reports the process has exited, to
        pick up any bytes written between the last poll and process exit.
        """
        lines = []
        if self._log_file is not None:
            remaining = self._log_file.read()
            if remaining:
                self._log_linebuf += remaining
            combined = (self._log_linebuf + "\n").split("\n")
            self._log_linebuf = ""
            lines = [line for line in combined if line.strip()]
            self._log_file.close()
            self._log_file = None
        return lines

    def terminate(self):
        """Send SIGTERM to fisherman's process group (e.g. window closed).

        fisherman's own cleanup handler attempts to unmount filesystems and
        close LUKS devices; this only asks it to run that handler.
        """
        if self.proc is None:
            return
        if self.proc.poll() is not None:
            return
        logger.warning("Terminating fisherman (PID %s) due to window close", self.proc.pid)
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                self.proc.terminate()
            except OSError as e:
                logger.debug("Could not terminate fisherman process: %s", e)

    def cleanup_recipe_file(self):
        """Remove the recipe JSON file — it contains plaintext passphrases and
        passwords that must not persist on disk after install."""
        if not self.recipe_path:
            return
        try:
            os.unlink(self.recipe_path)
            logger.info("Deleted recipe file: %s", self.recipe_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Could not delete recipe file %s: %s", self.recipe_path, e)
