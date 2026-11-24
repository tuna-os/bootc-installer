"""GTK-free fisherman process-lifecycle adapter.

Owns everything about running the privileged fisherman helper that is not
GTK: staging (delegated to fisherman_runner), argv construction (ditto),
launching and polling the subprocess, handing it the recipe on stdin, and
reading its output from the stdout pipe. No recipe file is written: fisherman
reads the recipe from stdin (`fisherman -`, tuna-os/fisherman#276), so the
passphrase and the user password never touch the disk.

fisherman's output comes back over a pipe, as in the other four frontends
(#429). Each line goes through bootc_shared.redact.LogRedactor before it is
written to the log file, so the TPM recovery key never reaches the disk. The
progress page gets the line as fisherman wrote it: it reads the key from the
`recovery_key` event for the recovery-key page.

`bootc_installer.views.progress.BootcProgress` is the GTK consumer: it owns
the widget state (progress bar, video, console) and the GLib timers that
call into this adapter, but it does not itself touch os.unlink, subprocess,
or file descriptors for the fisherman transport. That split is what makes
this module importable, and testable, without a display.

apply_progress_event() in bootc_shared.progress remains the protocol-translation
boundary; this module only decides *when* to hand it a line, not how to
interpret one.
"""

import json
import logging
import os
import queue
import signal
import subprocess
import threading

from bootc_installer.utils import fisherman_runner

logger = logging.getLogger("Installer::FishermanSession")


# The recovery key does not stay in a log (#316, #337). The redaction is in
# bootc_shared.redact, which XFCE also uses; the names stay importable from
# here for the progress page and the log dialog.
from bootc_shared.redact import (  # noqa: E402,F401
    REDACTED,
    LogRedactor,
    read_log_redacted,
    redact_recovery_key,
    scrub_log_file,
)


class FishermanSession:
    """Runs one fisherman install, from launch to log drain to cleanup.

    Callers (a GTK widget, a headless test, an alternative frontend) drive
    this with their own scheduling — poll_process() and read_new_lines() are
    meant to be called from a timer, but this class does not start one.
    """

    def __init__(
        self,
        recipe: dict,
        *,
        in_flatpak: bool = fisherman_runner.IN_FLATPAK,
        use_sudo: bool = False,
        stage_base: str = fisherman_runner.STAGE_BASE,
        cache_dir: str = fisherman_runner.CACHE_DIR,
        host_path: str = fisherman_runner.HOST_PATH,
        log_path: str = fisherman_runner.LOG_PATH,
        popen=None,
    ):
        self._recipe = recipe
        self._in_flatpak = in_flatpak
        self._use_sudo = use_sudo
        self._stage_base = stage_base
        self._cache_dir = cache_dir
        self._host_path = host_path
        self.log_path = log_path
        # Injectable for tests; defaults to the real subprocess.Popen.
        if popen is None:
            popen = subprocess.Popen
        self._popen = popen

        self.proc = None
        # fisherman's output, line by line, as the reader thread took it
        # from the pipe; read_new_lines() hands it to the caller.
        self._lines = queue.Queue()
        self._reader = None

    def stage(self) -> bool:
        """Copy fisherman to a host-visible location, if running in Flatpak."""
        return fisherman_runner.stage_on_host(
            in_flatpak=self._in_flatpak,
            stage_base=self._stage_base,
            cache_dir=self._cache_dir,
            host_path=self._host_path,
        )

    def _reset_log_file(self):
        """Remove the log of an earlier run before this one writes its own.

        A log left by an older version can still hold a recovery key; it is
        removed, not kept beside the new one.
        """
        try:
            os.unlink(self.log_path)
            logger.info("Deleted stale log file: %s", self.log_path)
        except FileNotFoundError:
            logger.info("No stale log file to delete")
        except OSError as e:
            logger.error("Failed to delete stale log: %s", e)

    def _create_private_log(self):
        """Open the log for writing, created 0600 and empty; None when it
        cannot be opened (the install still runs, with no log).

        The log carries fisherman's output with the recovery key redacted,
        and the user attaches it to bug reports: it is still nobody else's
        to read. O_NOFOLLOW refuses a symlink planted at the path; fchmod
        covers a stale file that _reset_log_file() could not remove.
        """
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        try:
            fd = os.open(self.log_path, flags, 0o600)
        except OSError as e:
            logger.error("Could not create private log %s: %s", self.log_path, e)
            return None
        try:
            os.fchmod(fd, 0o600)
            return os.fdopen(fd, "w", encoding="utf-8")
        except OSError as e:
            logger.error("Could not open private log %s: %s", self.log_path, e)
            os.close(fd)
            return None

    def launch(self):
        """Stage fisherman if needed, then start it. Returns argv used, or None on staging failure."""
        if not self.stage():
            return None
        os.makedirs(self._cache_dir, exist_ok=True)
        self._reset_log_file()
        log = self._create_private_log()
        # No log_path: the wrapper does no redirection, and fisherman's
        # stdout and stderr come back on the pipe below.
        argv = fisherman_runner.build_argv(
            in_flatpak=self._in_flatpak,
            use_sudo=self._use_sudo,
            host_path=self._host_path,
            log_path=None,
        )
        logger.info("Launching fisherman: %s", argv)
        # stdin, stdout and stderr are pipes. flatpak-spawn forwards its fds
        # to the host bash, as for XFCE, and bash, pkexec and sudo hand them
        # on to fisherman. stdin carries the recipe, and fisherman reads it
        # to EOF. stderr joins stdout, so the lines keep their order.
        #
        # start_new_session: the wrapper (bash, or flatpak-spawn) leads its
        # own process group, which terminate() signals. Without it the
        # wrapper shared the GUI's group, and terminate()'s
        # killpg(getpgid(wrapper)) sent SIGTERM to the installer itself.
        # fisherman runs as root under pkexec, so the wrapper is all this
        # process can signal; fisherman cancels when its parent dies.
        try:
            self.proc = self._popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        except BaseException:
            if log is not None:
                log.close()
            raise
        logger.info("Fisherman PID: %s", self.proc.pid)
        self._reader = threading.Thread(
            target=self._read_output, args=(getattr(self.proc, "stdout", None), log),
            name="fisherman-output", daemon=True)
        self._reader.start()
        self._write_recipe()
        return argv

    def _read_output(self, stream, log):
        """The reader thread: each line of fisherman's output goes to the log
        without the recovery key, and to the caller as fisherman wrote it.

        Runs until fisherman closes its stdout. The log file is this
        thread's alone, and it closes it.
        """
        redactor = LogRedactor()
        try:
            for raw in stream if stream is not None else ():
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                line = raw.rstrip("\n")
                if log is not None:
                    try:
                        log.write(redactor.line(line) + "\n")
                        log.flush()
                    except (OSError, ValueError) as e:
                        logger.error("Could not write to %s: %s", self.log_path, e)
                        log = None
                self._lines.put(line)
        except (OSError, ValueError) as e:
            logger.error("Could not read fisherman's output: %s", e)
        finally:
            if log is not None:
                try:
                    log.close()
                except OSError:
                    pass

    def _write_recipe(self):
        """Write the recipe to fisherman's stdin and close it.

        A recipe is a few KiB, well under a pipe's buffer, so the write does
        not wait for fisherman (or the polkit prompt in front of it) to read.
        If the wrapper is already gone, fisherman never ran and its exit code
        says why; nothing is written anywhere else.
        """
        stdin = getattr(self.proc, "stdin", None)
        if stdin is None:
            return
        try:
            stdin.write(json.dumps(self._recipe).encode("utf-8"))
        except (BrokenPipeError, OSError) as e:
            logger.error("Could not hand the recipe to fisherman: %s", e)
        finally:
            try:
                stdin.close()
            except OSError:
                pass
            # The recipe holds the LUKS passphrase and the account password.
            # fisherman has it now; this process has no more use for it.
            self._recipe = None

    def poll_process(self):
        """Return the exit code if fisherman has finished, else None."""
        if self.proc is None:
            return None
        return self.proc.poll()

    def open_log_for_tailing(self) -> bool:
        """Whether there is output to read: True once launch() has started
        fisherman. The name is the one the progress page has always called."""
        return self._reader is not None

    def _take_lines(self) -> list[str]:
        lines = []
        while True:
            try:
                lines.append(self._lines.get_nowait())
            except queue.Empty:
                return lines

    def read_new_lines(self) -> list[str]:
        """The complete lines fisherman has written since the last call, as
        it wrote them (the recovery key included: the page needs it).
        [] before launch() or when there is nothing new."""
        return self._take_lines()

    # How long drain_remaining() waits for fisherman's stdout to close.
    DRAIN_TIMEOUT = 5.0

    def drain_remaining(self) -> list[str]:
        """The lines left after fisherman exits, the last unterminated one
        included; blank lines are dropped.

        Call once after poll_process() reports the process has exited: the
        exit can come before the reader thread has taken the last lines.
        The wait is bounded, so a child of fisherman that keeps the pipe
        open does not hold up the done page.
        """
        if self._reader is not None:
            self._reader.join(timeout=self.DRAIN_TIMEOUT)
            if self._reader.is_alive():
                logger.warning("fisherman's output is still open %.0fs after it exited",
                               self.DRAIN_TIMEOUT)
        return [line for line in self._take_lines() if line.strip()]

    def scrub_log(self, known_key: str = "") -> bool:
        """Remove the recovery key from this session's log file. The session
        writes the log redacted; this is for a log an older version left."""
        return scrub_log_file(self.log_path, known_key)

    # How long terminate() waits for the wrapper to exit after SIGTERM.
    TERMINATE_TIMEOUT = 5.0

    def request_cancel(self) -> bool:
        """Ask the install to stop and return at once: SIGTERM the wrapper's
        group, as terminate() does, without the wait. The caller keeps its
        poll_process() timer, which sees the wrapper's exit. True when a
        signal was sent."""
        if self.proc is None or self.proc.poll() is not None:
            return False
        logger.warning("Cancelling fisherman (PID %s) on the user's request", self.proc.pid)
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                self.proc.terminate()
            except OSError as e:
                logger.debug("Could not terminate fisherman process: %s", e)
                return False
        return True

    def terminate(self):
        """Cancel the install (e.g. window closed): SIGTERM the wrapper's group.

        launch() starts the wrapper as the leader of its own process group,
        so the group id is its pid. That is signalled directly rather than
        through os.getpgid(): if the wrapper were ever in this process's
        group, getpgid() would name the installer's own group (which is what
        used to happen), while killpg(pid) fails with ESRCH and falls back
        to signalling the wrapper alone.

        fisherman runs as root via pkexec, so it cannot be signalled from
        here; it notices its parent's death and runs its cleanup handler
        (unmount, close LUKS), exiting 130. The wrapper is then reaped with
        a bounded wait so its exit status is collected, not left a zombie.
        """
        if self.proc is None:
            return
        if self.proc.poll() is not None:
            return
        logger.warning("Terminating fisherman (PID %s) due to window close", self.proc.pid)
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                self.proc.terminate()
            except OSError as e:
                logger.debug("Could not terminate fisherman process: %s", e)
        try:
            code = self.proc.wait(timeout=self.TERMINATE_TIMEOUT)
            logger.info("fisherman wrapper exited with %s after SIGTERM", code)
        except subprocess.TimeoutExpired:
            logger.warning("fisherman wrapper (PID %s) still running %.0fs after SIGTERM",
                           self.proc.pid, self.TERMINATE_TIMEOUT)
