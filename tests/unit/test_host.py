"""Contract of bootc_installer.utils.host, the one host execution layer (#82).

The argv tests pin what runs natively and in a Flatpak for each scope. The
run tests start real processes (`sh`, `sleep`) natively, so the timeout,
cancel, missing-command and exit-code results are the ones a user gets.
"""

import sys
import threading
import time
import unittest

from bootc_installer.utils import host
from bootc_installer.utils.host import HostExecutor, HostResult, Scope, build_argv


class TestArgv(unittest.TestCase):
    def test_native_argv_per_scope(self):
        cmd = ["lsblk", "-no", "FSTYPE", "/dev/vda"]
        self.assertEqual(build_argv(cmd, Scope.LOCAL, in_flatpak=False), cmd)
        self.assertEqual(build_argv(cmd, Scope.HOST, in_flatpak=False), cmd)
        self.assertEqual(build_argv(cmd, Scope.ELEVATED, in_flatpak=False), ["pkexec"] + cmd)

    def test_flatpak_argv_per_scope(self):
        cmd = ["losetup", "-fP", "/img"]
        self.assertEqual(build_argv(cmd, Scope.LOCAL, in_flatpak=True), cmd)
        self.assertEqual(build_argv(cmd, Scope.HOST, in_flatpak=True),
                         ["flatpak-spawn", "--host"] + cmd)
        self.assertEqual(build_argv(cmd, Scope.ELEVATED, in_flatpak=True),
                         ["flatpak-spawn", "--host", "pkexec"] + cmd)

    def test_shell_strings_are_refused(self):
        with self.assertRaises(TypeError):
            build_argv("lsblk /dev/vda", Scope.HOST, in_flatpak=False)
        with self.assertRaises(ValueError):
            build_argv([], Scope.HOST, in_flatpak=False)
        with self.assertRaises(TypeError):
            build_argv(["true"], "host", in_flatpak=False)

    def test_executor_gives_its_mode_to_popen(self):
        seen = []

        class _Proc:
            returncode = 0

            def communicate(self, input=None, timeout=None):
                return "out", ""

        def popen(argv, **kwargs):
            seen.append((argv, kwargs))
            return _Proc()

        result = HostExecutor(in_flatpak=True, popen=popen).run(
            ["lsblk"], scope=Scope.HOST)
        self.assertEqual(seen[0][0], ["flatpak-spawn", "--host", "lsblk"])
        self.assertNotIn("shell", seen[0][1])
        self.assertEqual(result, HostResult(("flatpak-spawn", "--host", "lsblk"), 0, "out", ""))

    def test_command_exists_never_puts_the_name_in_the_script(self):
        seen = []

        class _Proc:
            returncode = 1

            def communicate(self, input=None, timeout=None):
                return "", ""

        def popen(argv, **kwargs):
            seen.append(argv)
            return _Proc()

        name = "x; rm -rf /"
        HostExecutor(in_flatpak=True, popen=popen).command_exists(name)
        argv = seen[0]
        self.assertEqual(argv[:4], ["flatpak-spawn", "--host", "sh", "-c"])
        self.assertNotIn(name, argv[4])
        self.assertEqual(argv[-1], name)


class TestRun(unittest.TestCase):
    def setUp(self):
        self.ex = HostExecutor(in_flatpak=False)

    def test_success_captures_stdout_and_stderr(self):
        r = self.ex.run(["sh", "-c", "echo out; echo err >&2"])
        self.assertTrue(r.ok)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "out\n", "err\n"))
        self.assertFalse(r.timed_out or r.missing_command or r.cancelled)

    def test_non_zero_exit(self):
        r = self.ex.run(["sh", "-c", "echo nope >&2; exit 3"])
        self.assertFalse(r.ok)
        self.assertEqual(r.returncode, 3)
        self.assertIn("exit 3 nope", r.describe())

    def test_missing_command(self):
        r = self.ex.run(["bootc-installer-no-such-command"])
        self.assertTrue(r.missing_command)
        self.assertIsNone(r.returncode)
        self.assertFalse(r.ok)
        self.assertIn("command not found", r.describe())

    def test_missing_flatpak_spawn_is_a_missing_command(self):
        def popen(argv, **kwargs):
            raise FileNotFoundError(argv[0])

        r = HostExecutor(in_flatpak=True, popen=popen).run(["lsblk"])
        self.assertTrue(r.missing_command)
        self.assertEqual(r.argv[0], "flatpak-spawn")

    def test_timeout_kills_the_command(self):
        start = time.monotonic()
        r = self.ex.run(["sleep", "30"], timeout=0.3)
        self.assertLess(time.monotonic() - start, 10)
        self.assertTrue(r.timed_out)
        self.assertIsNone(r.returncode)
        self.assertFalse(r.ok)

    def test_cancel_stops_a_running_command(self):
        cancel = threading.Event()
        threading.Timer(0.2, cancel.set).start()
        start = time.monotonic()
        r = self.ex.run(["sleep", "30"], timeout=None, cancel=cancel)
        self.assertLess(time.monotonic() - start, 10)
        self.assertTrue(r.cancelled)
        self.assertFalse(r.timed_out)
        self.assertFalse(r.ok)

    def test_cancel_before_start_runs_nothing(self):
        cancel = threading.Event()
        cancel.set()

        def popen(argv, **kwargs):
            raise AssertionError("must not start")

        r = HostExecutor(in_flatpak=False, popen=popen).run(["true"], cancel=cancel)
        self.assertTrue(r.cancelled)

    def test_input_reaches_stdin_once(self):
        r = self.ex.run([sys.executable, "-c", "import sys; print(sys.stdin.read())"],
                        input_text="abc", cancel=threading.Event())
        self.assertEqual(r.stdout, "abc\n")

    def test_no_stdin_by_default(self):
        r = self.ex.run(["cat"], timeout=5)
        self.assertTrue(r.ok)
        self.assertEqual(r.stdout, "")

    def test_command_exists(self):
        self.assertTrue(self.ex.command_exists("sh").ok)
        self.assertFalse(self.ex.command_exists("bootc-installer-no-such-command").ok)

    def test_default_executor_reads_the_sandbox_once(self):
        self.assertIs(host.default_executor(), host.default_executor())
        self.assertEqual(host.default_executor().in_flatpak, host.IN_FLATPAK)

    def test_module_does_not_import_gtk(self):
        source = host.__file__
        with open(source, encoding="utf-8") as f:
            self.assertNotIn("gi.repository", f.read())


class TestSpawn(unittest.TestCase):
    def test_spawn_does_not_wait_and_detaches(self):
        seen = []

        def popen(argv, **kwargs):
            seen.append((argv, kwargs))
            return object()

        r = HostExecutor(in_flatpak=True, popen=popen).spawn(["blueman-manager"])
        argv, kwargs = seen[0]
        self.assertEqual(argv, ["flatpak-spawn", "--host", "blueman-manager"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertNotIn("shell", kwargs)
        self.assertTrue(r.started)
        self.assertIsNone(r.returncode)
        self.assertFalse(r.ok)

    def test_spawn_local_and_missing(self):
        ex = HostExecutor(in_flatpak=True)
        r = ex.spawn(["bootc-installer-no-such-command"], scope=Scope.LOCAL)
        self.assertTrue(r.missing_command)
        self.assertFalse(r.started)
        self.assertEqual(r.argv, ("bootc-installer-no-such-command",))

    def test_spawn_real_process(self):
        start = time.monotonic()
        r = HostExecutor(in_flatpak=False).spawn(["sleep", "5"])
        self.assertTrue(r.started)
        self.assertLess(time.monotonic() - start, 2)

    def test_spawn_refuses_shell_strings(self):
        with self.assertRaises(TypeError):
            HostExecutor(in_flatpak=False).spawn("gnome-control-center wifi")


if __name__ == "__main__":
    unittest.main()
