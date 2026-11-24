"""Headless contract tests for FishermanSession — no GTK; a real subprocess
only where the test says so."""
import io
import json
import os
import pathlib
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from bootc_installer.utils.fisherman_session import FishermanSession


def _fake_popen(pid=4242, poll_sequence=(None, None, 0)):
    """Build a MagicMock standing in for subprocess.Popen's return value.

    poll_sequence is consumed one call at a time, then repeats the last value.
    """
    proc = MagicMock()
    proc.pid = pid
    seq = list(poll_sequence)

    def _poll():
        if seq:
            value = seq.pop(0)
        else:
            value = poll_sequence[-1]
        return value

    proc.poll.side_effect = _poll
    return proc


# The recipe the session hands to fisherman on stdin; never a file.
_RECIPE = {"disk": "/dev/vda", "hostname": "h",
           "encryption": {"type": "luks-passphrase", "passphrase": "s3cret"}}


class FishermanSessionLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.log_path = os.path.join(self.cache_dir, "fisherman-output.log")

    def _session(self, popen=None, in_flatpak=False):
        return FishermanSession(
            _RECIPE,
            in_flatpak=in_flatpak,
            stage_base=self.tmp,
            cache_dir=self.cache_dir,
            host_path=os.path.join(self.cache_dir, "fisherman"),
            log_path=self.log_path,
            popen=popen or (lambda argv, **kw: _fake_popen()),
        )

    def test_launch_creates_cache_dir_and_starts_process(self):
        popen = MagicMock(side_effect=lambda argv, **kw: _fake_popen())
        session = self._session(popen=popen)
        argv = session.launch()
        self.assertIsNotNone(argv)
        self.assertTrue(os.path.isdir(self.cache_dir))
        popen.assert_called_once()
        self.assertIsNotNone(session.proc)

    def test_launch_removes_stale_log_before_starting(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self.log_path, "w") as f:
            f.write("stale content from a previous run\n")
        session = self._session()
        session.launch()
        # The stale content is gone; launch() recreates the file empty (and
        # 0600, see FishermanSessionLogModeTests) and writes it itself.
        with open(self.log_path) as f:
            self.assertEqual(f.read(), "")

    def test_launch_returns_none_when_staging_fails(self):
        # in_flatpak=True + a stage_base that fails the private-path check
        # (world-writable) makes stage_on_host() refuse.
        os.chmod(self.tmp, 0o777)
        session = self._session(in_flatpak=True)
        self.addCleanup(os.chmod, self.tmp, 0o700)
        argv = session.launch()
        self.assertIsNone(argv)
        self.assertIsNone(session.proc)


class FishermanSessionLogModeTests(unittest.TestCase):
    """bash's `>` used to create the log, so its mode followed the umask:
    0644 under 022, world-readable. The session creates it 0600 itself."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.log_path = os.path.join(self.cache_dir, "fisherman-output.log")
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)

    def _launch(self):
        session = FishermanSession(
            _RECIPE,
            in_flatpak=False,
            stage_base=self.tmp,
            cache_dir=self.cache_dir,
            host_path=os.path.join(self.cache_dir, "fisherman"),
            log_path=self.log_path,
            popen=lambda argv, **kw: _fake_popen(),
        )
        return session.launch()

    def _mode(self):
        return os.stat(self.log_path).st_mode & 0o777

    def test_log_is_created_0600_before_the_process_starts(self):
        self._launch()
        self.assertEqual(self._mode(), 0o600)

    def test_the_wrapper_does_not_redirect_to_the_log(self):
        # #429: the wrapper's `>LOG` put fisherman's raw output, the key
        # included, on disk. The output now comes back on the pipe.
        argv = self._launch()
        self.assertNotIn(">", argv[-1])
        self.assertNotIn(self.log_path, " ".join(argv))

    def test_stale_world_readable_log_is_tightened(self):
        # _reset_log_file() cannot remove it (simulated): the mode is still
        # forced to 0600 and the old content dropped.
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self.log_path, "w") as f:
            f.write("old key\n")
        os.chmod(self.log_path, 0o644)
        with patch.object(FishermanSession, "_reset_log_file"):
            self._launch()
        self.assertEqual(self._mode(), 0o600)
        with open(self.log_path) as f:
            self.assertEqual(f.read(), "")

    def test_symlink_at_log_path_is_not_followed(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        target = os.path.join(self.tmp, "elsewhere")
        with open(target, "w") as f:
            f.write("keep\n")
        os.symlink(target, self.log_path)
        with patch.object(FishermanSession, "_reset_log_file"):
            self._launch()
        with open(target) as f:
            self.assertEqual(f.read(), "keep\n")


class FishermanSessionPollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def _launched_session(self, poll_sequence=(None, None, 0)):
        def popen(argv, **kw):
            return _fake_popen(poll_sequence=poll_sequence)

        session = FishermanSession(
            _RECIPE,
            in_flatpak=False,
            stage_base=self.tmp,
            cache_dir=self.tmp,
            host_path=os.path.join(self.tmp, "fisherman"),
            log_path=os.path.join(self.tmp, "fisherman-output.log"),
            popen=popen,
        )
        session.launch()
        return session

    def test_poll_process_returns_none_before_exit(self):
        session = self._launched_session(poll_sequence=(None,))
        self.assertIsNone(session.poll_process())

    def test_poll_process_returns_exit_code(self):
        session = self._launched_session(poll_sequence=(0,))
        self.assertEqual(session.poll_process(), 0)

    def test_poll_process_without_launch_is_none(self):
        session = FishermanSession(_RECIPE)
        self.assertIsNone(session.poll_process())


def _piped_popen(output: bytes, poll_sequence=(0,)):
    """A Popen stand-in whose stdout is `output`, then EOF."""
    def popen(argv, **kw):
        proc = _fake_popen(poll_sequence=poll_sequence)
        proc.stdout = io.BytesIO(output)
        return proc
    return popen


class FishermanSessionOutputTests(unittest.TestCase):
    """fisherman's output comes back over the stdout pipe (#429); the session
    hands each line to the caller and writes it to the log."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.log_path = os.path.join(self.tmp, "fisherman-output.log")

    def _session(self, popen):
        return FishermanSession(
            _RECIPE, in_flatpak=False, stage_base=self.tmp, cache_dir=self.tmp,
            host_path=os.path.join(self.tmp, "fisherman"), log_path=self.log_path,
            popen=popen)

    def test_the_output_is_read_from_a_stdout_pipe_with_stderr_joined(self):
        popen = MagicMock(side_effect=lambda argv, **kw: _fake_popen())
        self._session(popen).launch()
        self.assertIs(popen.call_args.kwargs.get("stdout"), subprocess.PIPE)
        self.assertIs(popen.call_args.kwargs.get("stderr"), subprocess.STDOUT)

    def test_open_log_for_tailing_is_true_once_launched(self):
        session = self._session(_piped_popen(b""))
        self.assertFalse(session.open_log_for_tailing())
        session.launch()
        self.assertTrue(session.open_log_for_tailing())
        self.assertTrue(session.open_log_for_tailing())

    def test_lines_arrive_in_order_without_their_newline(self):
        session = self._session(_piped_popen(b"line one\nline two\n"))
        session.launch()
        session._reader.join(timeout=5)
        self.assertEqual(session.read_new_lines(), ["line one", "line two"])
        self.assertEqual(session.read_new_lines(), [])

    def test_read_new_lines_without_launch_is_empty(self):
        self.assertEqual(self._session(_piped_popen(b"")).read_new_lines(), [])

    def test_drain_remaining_returns_the_final_unterminated_line(self):
        session = self._session(_piped_popen(b"first\n\nfinal no newline"))
        session.launch()
        self.assertEqual(session.drain_remaining(), ["first", "final no newline"])
        # Nothing left: a second drain returns nothing rather than erroring.
        self.assertEqual(session.drain_remaining(), [])

    def test_drain_remaining_without_launch_is_empty(self):
        self.assertEqual(self._session(_piped_popen(b"")).drain_remaining(), [])

    def test_the_log_holds_every_line(self):
        session = self._session(_piped_popen(b"a\nb\n"))
        session.launch()
        session.drain_remaining()
        with open(self.log_path) as f:
            self.assertEqual(f.read(), "a\nb\n")

    def test_the_install_runs_when_the_log_cannot_be_opened(self):
        with patch.object(FishermanSession, "_create_private_log", return_value=None):
            session = self._session(_piped_popen(b"step\n"))
            self.assertIsNotNone(session.launch())
        self.assertEqual(session.drain_remaining(), ["step"])


_PROGRESS = pathlib.Path(__file__).resolve().parents[2] / "shared" / "progress"
_KEY_SPEC = json.loads((_PROGRESS / "recovery-key-cases.json").read_text(encoding="utf-8"))
_TRANSCRIPT = _PROGRESS / _KEY_SPEC["transcript"]


class RecoveryKeyNeverReachesTheLogTests(unittest.TestCase):
    """#429: the log used to be fisherman's transport, so the key was on disk
    until scrub_log() ran. shared/progress/README.md ("Recovery key in a
    log"): a frontend must not write the key to a log file."""

    KEY = _KEY_SPEC["key"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.log_path = os.path.join(self.tmp, "fisherman-output.log")

    def _session(self, popen=None):
        return FishermanSession(
            _RECIPE, in_flatpak=False, stage_base=self.tmp, cache_dir=self.tmp,
            host_path=os.path.join(self.tmp, "fisherman"), log_path=self.log_path,
            popen=popen)

    def _log(self):
        with open(self.log_path, encoding="utf-8") as f:
            return f.read()

    def test_the_transcript_reaches_the_page_whole_and_the_log_redacted(self):
        session = self._session(_piped_popen(_TRANSCRIPT.read_bytes()))
        session.launch()
        lines = session.drain_remaining()
        self.assertEqual(lines, _TRANSCRIPT.read_text(encoding="utf-8").splitlines())
        self.assertNotIn(self.KEY, self._log())
        self.assertIn(_KEY_SPEC["redacted_event"], self._log())

    def test_a_later_line_that_repeats_the_key_loses_it_too(self):
        out = _TRANSCRIPT.read_bytes() + f"stderr: unlocked with {self.KEY}\n".encode()
        session = self._session(_piped_popen(out))
        session.launch()
        session.drain_remaining()
        self.assertNotIn(self.KEY, self._log())

    def test_the_key_is_not_on_disk_while_the_install_still_runs(self):
        # A real wrapper that prints the transcript and keeps running: the
        # moment the old design left the key on disk, before any scrub.
        argv = ["bash", "-c", f'cat "{_TRANSCRIPT}"; exec sleep 30']
        with patch("bootc_installer.utils.fisherman_runner.build_argv", return_value=argv):
            session = self._session()
            session.launch()
        self.addCleanup(session.terminate)
        seen = []
        deadline = __import__("time").monotonic() + 10
        while not any('"recovery_key"' in line for line in seen):
            self.assertLess(__import__("time").monotonic(), deadline, seen)
            seen += session.read_new_lines()
            __import__("time").sleep(0.01)
        self.assertIsNone(session.poll_process())
        self.assertIn(self.KEY, "\n".join(seen))
        self.assertIn(_KEY_SPEC["redacted_event"], self._log())
        self.assertNotIn(self.KEY, self._log())


class FishermanSessionTerminateAndCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def test_terminate_without_launch_is_a_noop(self):
        session = FishermanSession(_RECIPE)
        session.terminate()  # must not raise

    def test_terminate_skips_already_exited_process(self):
        session = FishermanSession(
            _RECIPE,
            popen=lambda argv, **kw: _fake_popen(poll_sequence=(0,)),
        )
        session.launch()
        with patch("os.killpg") as killpg:
            session.terminate()
            killpg.assert_not_called()

    def test_launch_starts_the_wrapper_in_its_own_session(self):
        popen = MagicMock(side_effect=lambda argv, **kw: _fake_popen())
        session = FishermanSession(_RECIPE, popen=popen)
        session.launch()
        self.assertIs(popen.call_args.kwargs.get("start_new_session"), True)

    def test_terminate_signals_the_wrappers_group_not_ours(self):
        session = FishermanSession(
            _RECIPE,
            popen=lambda argv, **kw: _fake_popen(pid=4242, poll_sequence=(None,)),
        )
        session.launch()
        with patch("os.killpg") as killpg, patch("os.getpgid", return_value=os.getpgrp()):
            session.terminate()
        killpg.assert_called_once_with(4242, signal.SIGTERM)
        self.assertNotEqual(killpg.call_args.args[0], os.getpgrp())
        session.proc.wait.assert_called_once_with(timeout=FishermanSession.TERMINATE_TIMEOUT)

    def test_terminate_falls_back_to_proc_terminate_if_killpg_fails(self):
        session = FishermanSession(
            _RECIPE,
            popen=lambda argv, **kw: _fake_popen(poll_sequence=(None,)),
        )
        session.launch()
        with patch("os.killpg", side_effect=OSError()):
            session.terminate()
            session.proc.terminate.assert_called_once()
        session.proc.wait.assert_called_once()

    def test_terminate_tolerates_a_wrapper_that_outlives_the_wait(self):
        session = FishermanSession(
            _RECIPE,
            popen=lambda argv, **kw: _fake_popen(poll_sequence=(None,)),
        )
        session.launch()
        session.proc.wait.side_effect = subprocess.TimeoutExpired("bash", 5)
        with patch("os.killpg"):
            session.terminate()  # must not raise

    def test_terminate_with_a_real_child_does_not_signal_the_installer(self):
        # A real wrapper through the real subprocess.Popen. The installer
        # (this test process) traps SIGTERM: before start_new_session the
        # wrapper shared our group and killpg delivered SIGTERM here too.
        received = []
        previous = signal.signal(signal.SIGTERM, lambda *a: received.append(a[0]))
        self.addCleanup(signal.signal, signal.SIGTERM, previous)
        with patch(
            "bootc_installer.utils.fisherman_runner.build_argv",
            return_value=["sleep", "30"],
        ):
            session = FishermanSession(
                _RECIPE,
                in_flatpak=False,
                cache_dir=os.path.join(self.tmp, "cache"),
                log_path=os.path.join(self.tmp, "cache", "fisherman-output.log"),
            )
            session.launch()
        self.addCleanup(lambda: session.proc.poll() is None and session.proc.kill())
        self.assertEqual(os.getpgid(session.proc.pid), session.proc.pid)
        self.assertNotEqual(os.getpgid(session.proc.pid), os.getpgrp())

        session.terminate()

        self.assertEqual(received, [])
        self.assertEqual(session.proc.returncode, -signal.SIGTERM)

    def test_the_session_has_no_recipe_file_to_clean_up(self):
        self.assertFalse(hasattr(FishermanSession, "cleanup_recipe_file"))


class FishermanSessionStdinTests(unittest.TestCase):
    """fisherman reads the recipe from stdin (`fisherman -`, fisherman#276):
    the passphrase never touches the disk or argv."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache_dir = os.path.join(self.tmp, "cache")

    def _session(self, popen, **kw):
        return FishermanSession(
            _RECIPE, in_flatpak=False, stage_base=self.tmp, cache_dir=self.cache_dir,
            host_path=os.path.join(self.cache_dir, "fisherman"),
            log_path=os.path.join(self.cache_dir, "fisherman-output.log"),
            popen=popen, **kw)

    def test_the_recipe_is_written_to_stdin_and_closed(self):
        popen = MagicMock(side_effect=lambda argv, **kw: _fake_popen())
        session = self._session(popen)
        argv = session.launch()
        self.assertIs(popen.call_args.kwargs.get("stdin"), subprocess.PIPE)
        written = session.proc.stdin.write.call_args.args[0]
        self.assertEqual(__import__("json").loads(written), _RECIPE)
        session.proc.stdin.close.assert_called_once()
        self.assertTrue(argv[-1].endswith(" -; exit $?"), argv[-1])
        self.assertNotIn("s3cret", " ".join(argv))

    def test_no_file_holds_the_recipe(self):
        session = self._session(lambda argv, **kw: _fake_popen())
        session.launch()
        for root, _dirs, files in os.walk(self.tmp):
            for name in files:
                with open(os.path.join(root, name), errors="replace") as fh:
                    self.assertNotIn("s3cret", fh.read(), name)

    def test_a_wrapper_that_already_died_is_not_an_exception(self):
        def popen(argv, **kw):
            proc = _fake_popen()
            proc.stdin.write.side_effect = BrokenPipeError()
            return proc
        session = self._session(popen)
        self.assertIsNotNone(session.launch())
        session.proc.stdin.close.assert_called_once()

    def test_a_real_wrapper_reads_the_recipe_on_stdin(self):
        """The real bash wrapper, with the escalation replaced by `cat`:
        what fisherman would read on stdin comes back on its stdout."""
        with patch("bootc_installer.utils.fisherman_runner.build_argv",
                   return_value=["bash", "-c", "cat -; exit $?"]):
            session = self._session(None)
            session.launch()
        self.assertEqual(session.proc.wait(timeout=10), 0)
        self.assertEqual(json.loads("".join(session.drain_remaining())), _RECIPE)

    def test_live_media_uses_sudo_and_an_installed_host_pkexec(self):
        argvs = {}
        for use_sudo in (True, False):
            popen = MagicMock(side_effect=lambda argv, **kw: _fake_popen())
            self._session(popen, use_sudo=use_sudo).launch()
            argvs[use_sudo] = popen.call_args.args[0][-1]
        self.assertTrue(argvs[True].startswith("sudo -n /usr/local/bin/fisherman -"))
        self.assertTrue(argvs[False].startswith("pkexec /usr/local/bin/fisherman -"))


class RecipeIsDroppedTests(unittest.TestCase):
    """#316: the recipe holds the passphrase; the session kept it for the
    life of the process."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache_dir = os.path.join(self.tmp, "cache")

    def _session(self, popen):
        return FishermanSession(
            _RECIPE, in_flatpak=False, stage_base=self.tmp, cache_dir=self.cache_dir,
            host_path=os.path.join(self.cache_dir, "fisherman"),
            log_path=os.path.join(self.cache_dir, "fisherman-output.log"),
            popen=popen)

    def test_the_recipe_is_dropped_after_the_write_to_stdin(self):
        session = self._session(lambda argv, **kw: _fake_popen())
        session.launch()
        self.assertIsNone(session._recipe)
        self.assertNotIn("s3cret", repr(vars(session)))

    def test_the_recipe_is_dropped_when_the_write_fails(self):
        def popen(argv, **kw):
            proc = _fake_popen()
            proc.stdin.write.side_effect = BrokenPipeError()
            return proc
        session = self._session(popen)
        session.launch()
        self.assertIsNone(session._recipe)


class RecoveryKeyRedactionTests(unittest.TestCase):
    """#316: the key is on the recovery-key page and nowhere else."""

    KEY = "mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf"

    def _log(self):
        return "\n".join([
            '{"type":"step","step":8,"total_steps":9,"step_name":"Enrolling TPM2"}',
            '{"type":"recovery_key","key":"' + self.KEY + '"}',
            '{"type": "recovery_key", "key": "' + self.KEY + '", "message": "keep"}',
            "Recovery key: " + self.KEY,
            "systemd-cryptenroll: recovery key is " + self.KEY + " (stderr)",
            '{"type":"complete","message":"Installation complete!"}',
            "",
        ])

    def test_every_form_of_the_key_is_removed(self):
        from bootc_installer.utils.fisherman_session import REDACTED, redact_recovery_key
        out = redact_recovery_key(self._log(), self.KEY)
        self.assertNotIn(self.KEY, out)
        self.assertEqual(out.count(REDACTED), 4)
        # The rest of the log is what fisherman wrote.
        self.assertIn('"step_name":"Enrolling TPM2"', out)
        self.assertIn('"message": "keep"', out)
        self.assertIn('"type":"complete"', out)
        self.assertEqual(len(out.split("\n")), len(self._log().split("\n")))

    def test_events_are_redacted_without_knowing_the_key(self):
        """The log dialog reads the file with no session in hand."""
        from bootc_installer.utils.fisherman_session import redact_recovery_key
        out = redact_recovery_key(self._log())
        for line in out.split("\n")[1:4]:
            self.assertNotIn(self.KEY, line)

    def test_a_key_field_of_another_event_is_left_alone(self):
        from bootc_installer.utils.fisherman_session import redact_recovery_key
        line = '{"type":"info","key":"value","message":"x"}'
        self.assertEqual(redact_recovery_key(line), line)

    def test_empty_text_and_empty_key(self):
        from bootc_installer.utils.fisherman_session import redact_recovery_key
        self.assertEqual(redact_recovery_key(""), "")
        self.assertEqual(redact_recovery_key("plain line", ""), "plain line")

    def test_read_log_redacted(self):
        from bootc_installer.utils.fisherman_session import read_log_redacted
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log")
            with open(path, "w") as fh:
                fh.write(self._log())
            self.assertNotIn(self.KEY, read_log_redacted(path, self.KEY))
            self.assertIsNone(read_log_redacted(os.path.join(tmp, "absent")))

    def test_scrub_rewrites_the_file_and_keeps_its_mode(self):
        from bootc_installer.utils.fisherman_session import scrub_log_file
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
            os.write(fd, self._log().encode())
            os.close(fd)
            self.assertTrue(scrub_log_file(path, self.KEY))
            with open(path) as fh:
                text = fh.read()
            self.assertNotIn(self.KEY, text)
            self.assertIn('"type":"complete"', text)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_scrub_of_a_missing_log_is_not_an_error(self):
        from bootc_installer.utils.fisherman_session import scrub_log_file
        self.assertTrue(scrub_log_file("/nonexistent/dir/fisherman-output.log", self.KEY))

    def test_scrub_removes_a_log_it_cannot_rewrite(self):
        """A missing log is better than a key on disk."""
        from bootc_installer.utils import fisherman_session
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log")
            with open(path, "w") as fh:
                fh.write(self._log())
            real_open = os.open

            def refuse(p, flags, *a, **kw):
                if p == path and flags & os.O_TRUNC:
                    raise PermissionError("read-only")
                return real_open(p, flags, *a, **kw)

            with patch.object(fisherman_session.os, "open", side_effect=refuse):
                self.assertTrue(fisherman_session.scrub_log_file(path, self.KEY))
            self.assertFalse(os.path.exists(path))

    def test_scrub_does_not_follow_a_symlink(self):
        from bootc_installer.utils.fisherman_session import scrub_log_file
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "target")
            with open(target, "w") as fh:
                fh.write(self._log())
            link = os.path.join(tmp, "log")
            os.symlink(target, link)
            scrub_log_file(link, self.KEY)
            with open(target) as fh:
                self.assertIn(self.KEY, fh.read(), "the link's target was rewritten")
            self.assertFalse(os.path.lexists(link))


class RequestCancelTests(unittest.TestCase):
    """The Cancel button's signal: sent to the wrapper's group, no wait."""

    def _session(self, proc):
        session = FishermanSession(_RECIPE, in_flatpak=False)
        session.proc = proc
        return session

    def test_signals_the_group_and_does_not_wait(self):
        proc = _fake_popen(pid=4242, poll_sequence=(None,))
        session = self._session(proc)
        with patch("bootc_installer.utils.fisherman_session.os.killpg") as killpg:
            self.assertTrue(session.request_cancel())
        killpg.assert_called_once_with(4242, signal.SIGTERM)
        proc.wait.assert_not_called()

    def test_nothing_to_cancel_after_exit_or_before_launch(self):
        session = self._session(_fake_popen(poll_sequence=(0,)))
        with patch("bootc_installer.utils.fisherman_session.os.killpg") as killpg:
            self.assertFalse(session.request_cancel())
            self.assertFalse(self._session(None).request_cancel())
        killpg.assert_not_called()

    def test_falls_back_to_the_wrapper_when_the_group_is_gone(self):
        proc = _fake_popen(poll_sequence=(None,))
        session = self._session(proc)
        with patch("bootc_installer.utils.fisherman_session.os.killpg",
                   side_effect=ProcessLookupError()):
            self.assertTrue(session.request_cancel())
        proc.terminate.assert_called_once()
