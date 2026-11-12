"""A HostExecutor for tests: it records each command and answers from a
script, and never starts a process (#82)."""

from bootc_installer.utils.host import HostExecutor, HostResult, Scope

OK = {"returncode": 0}
FAIL = {"returncode": 1, "stderr": "boom"}
TIMEOUT = {"returncode": None, "timed_out": True}
MISSING = {"returncode": None, "missing_command": True}
STARTED = {"returncode": None, "started": True}


class FakeExecutor(HostExecutor):
    """`calls` holds (kind, cmd, scope, timeout, argv) per command; kind is
    "run" or "spawn". `answers` are HostResult fields, used in order; when
    they run out, `default` answers."""

    def __init__(self, answers=(), *, in_flatpak=True, default=None):
        super().__init__(in_flatpak=in_flatpak, popen=None)
        self.answers = list(answers)
        self.default = default
        self.calls = []

    def _answer(self, kind, cmd, scope, timeout):
        argv = self.argv(cmd, scope)
        self.calls.append((kind, list(cmd), scope, timeout, argv))
        if self.answers:
            fields = self.answers.pop(0)
        elif self.default is not None:
            fields = self.default
        else:
            raise AssertionError(f"unexpected host command: {argv}")
        return HostResult(tuple(argv), **fields)

    def run(self, cmd, *, scope=Scope.HOST, timeout=10, cancel=None, input_text=None):
        return self._answer("run", cmd, scope, timeout)

    def spawn(self, cmd, *, scope=Scope.HOST):
        return self._answer("spawn", cmd, scope, None)
