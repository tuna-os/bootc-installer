"""Headless contract tests for FishermanSession — no GTK, no real subprocess."""
import os
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


class FishermanSessionLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.log_path = os.path.join(self.cache_dir, "fisherman-output.log")

    def _session(self, popen=None, in_flatpak=False):
        return FishermanSession(
            os.path.join(self.tmp, "recipe.json"),
            in_flatpak=in_flatpak,
            live_iso=False,
            stage_base=self.tmp,
            cache_dir=self.cache_dir,
            host_path=os.path.join(self.cache_dir, "fisherman"),
            log_path=self.log_path,
            popen=popen or (lambda argv: _fake_popen()),
        )

    def test_launch_creates_cache_dir_and_starts_process(self):
        popen = MagicMock(side_effect=lambda argv: _fake_popen())
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
        # bash's redirect (not this test) recreates the file; here we only
        # assert the stale one was removed rather than left to be read stale.
        self.assertFalse(os.path.exists(self.log_path))

    def test_launch_returns_none_when_staging_fails(self):
        # in_flatpak=True + a stage_base that fails the private-path check
        # (world-writable) makes stage_on_host() refuse.
        os.chmod(self.tmp, 0o777)
        session = self._session(in_flatpak=True)
        self.addCleanup(os.chmod, self.tmp, 0o700)
        argv = session.launch()
        self.assertIsNone(argv)
        self.assertIsNone(session.proc)


class FishermanSessionPollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def _launched_session(self, poll_sequence=(None, None, 0)):
        popen = lambda argv: _fake_popen(poll_sequence=poll_sequence)
        session = FishermanSession(
            os.path.join(self.tmp, "recipe.json"),
            in_flatpak=False,
            live_iso=False,
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
        session = FishermanSession(os.path.join(self.tmp, "recipe.json"))
        self.assertIsNone(session.poll_process())


class FishermanSessionLogTailingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.log_path = os.path.join(self.tmp, "fisherman-output.log")
        self.session = FishermanSession(
            os.path.join(self.tmp, "recipe.json"),
            log_path=self.log_path,
            popen=lambda argv: _fake_popen(),
        )

    def test_open_log_for_tailing_false_until_file_exists(self):
        self.assertFalse(self.session.open_log_for_tailing())
        with open(self.log_path, "w"):
            pass
        self.assertTrue(self.session.open_log_for_tailing())

    def test_open_log_for_tailing_is_idempotent(self):
        with open(self.log_path, "w"):
            pass
        self.assertTrue(self.session.open_log_for_tailing())
        self.assertTrue(self.session.open_log_for_tailing())

    def test_read_new_lines_returns_only_complete_lines(self):
        with open(self.log_path, "w") as f:
            f.write("line one\nline two\nunfinished")
        self.session.open_log_for_tailing()
        lines = self.session.read_new_lines()
        self.assertEqual(lines, ["line one", "line two"])

    def test_read_new_lines_buffers_incomplete_line_across_calls(self):
        with open(self.log_path, "w") as f:
            f.write("partial")
        self.session.open_log_for_tailing()
        self.assertEqual(self.session.read_new_lines(), [])
        with open(self.log_path, "a") as f:
            f.write(" line\nnext\n")
        self.assertEqual(self.session.read_new_lines(), ["partial line", "next"])

    def test_read_new_lines_without_open_log_is_empty(self):
        self.assertEqual(self.session.read_new_lines(), [])

    def test_drain_remaining_flushes_final_unterminated_line_and_closes(self):
        with open(self.log_path, "w") as f:
            f.write("first\n")
        self.session.open_log_for_tailing()
        self.session.read_new_lines()
        with open(self.log_path, "a") as f:
            f.write("final no newline")
        lines = self.session.drain_remaining()
        self.assertEqual(lines, ["final no newline"])
        # Closed: a second drain returns nothing rather than erroring.
        self.assertEqual(self.session.drain_remaining(), [])

    def test_drain_remaining_without_open_log_is_empty(self):
        self.assertEqual(self.session.drain_remaining(), [])


class FishermanSessionTerminateAndCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def test_terminate_without_launch_is_a_noop(self):
        session = FishermanSession(os.path.join(self.tmp, "recipe.json"))
        session.terminate()  # must not raise

    def test_terminate_skips_already_exited_process(self):
        session = FishermanSession(
            os.path.join(self.tmp, "recipe.json"),
            popen=lambda argv: _fake_popen(poll_sequence=(0,)),
        )
        session.launch()
        with patch("os.killpg") as killpg:
            session.terminate()
            killpg.assert_not_called()

    def test_terminate_sends_sigterm_to_process_group(self):
        session = FishermanSession(
            os.path.join(self.tmp, "recipe.json"),
            popen=lambda argv: _fake_popen(poll_sequence=(None,)),
        )
        session.launch()
        with patch("os.killpg") as killpg, patch("os.getpgid", return_value=999):
            session.terminate()
            killpg.assert_called_once()

    def test_terminate_falls_back_to_proc_terminate_if_killpg_fails(self):
        session = FishermanSession(
            os.path.join(self.tmp, "recipe.json"),
            popen=lambda argv: _fake_popen(poll_sequence=(None,)),
        )
        session.launch()
        with patch("os.killpg", side_effect=OSError()):
            session.terminate()
            session.proc.terminate.assert_called_once()

    def test_cleanup_recipe_file_removes_the_file(self):
        recipe_path = os.path.join(self.tmp, "recipe.json")
        with open(recipe_path, "w") as f:
            f.write('{"hostname": "x"}')
        session = FishermanSession(recipe_path)
        session.cleanup_recipe_file()
        self.assertFalse(os.path.exists(recipe_path))

    def test_cleanup_recipe_file_missing_file_does_not_raise(self):
        session = FishermanSession(os.path.join(self.tmp, "does-not-exist.json"))
        session.cleanup_recipe_file()  # must not raise

    def test_cleanup_recipe_file_empty_path_is_a_noop(self):
        session = FishermanSession("")
        session.cleanup_recipe_file()  # must not raise


if __name__ == "__main__":
    unittest.main()
