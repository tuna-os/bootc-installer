"""One host execution policy (#82): only the host layer starts processes.

Every module under bootc_installer/ runs host commands through
`bootc_installer.utils.host.HostExecutor`. Only the files below may import
subprocess, call Popen or another process API, or spell `flatpak-spawn` in
code. A new call elsewhere fails this test; move it onto the executor
instead of adding to the list.
"""

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "bootc_installer"

ALLOWED = {
    # The host layer.
    "bootc_installer/utils/host.py",
    # The fisherman launch path: it pipes the recipe to `fisherman -` on
    # stdin and has its own contract (shared/recipe/README.md).
    "bootc_installer/utils/fisherman_runner.py",
    "bootc_installer/utils/fisherman_session.py",
}

# Attribute names that start a process, on any object.
PROCESS_ATTRS = {
    "Popen", "check_output", "check_call", "getoutput", "getstatusoutput",
    "system", "popen", "posix_spawn", "posix_spawnp",
    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "spawn_async", "spawn_async_with_pipes", "spawn_async_with_fds",
    "spawn_command_line_async", "spawn_command_line_sync", "spawn_sync",
    "Subprocess", "SubprocessLauncher",
    "create_subprocess_exec", "create_subprocess_shell",
}
PROCESS_MODULES = {"subprocess", "pty"}


def _docstrings(tree):
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                nodes.add(id(body[0].value))
    return nodes


def violations(source: str):
    """(line, what) for each process call, process import or
    `flatpak-spawn` string in `source`. Comments and docstrings may name
    them; code may not."""
    tree = ast.parse(source)
    docs = _docstrings(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in PROCESS_MODULES:
                    found.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in PROCESS_MODULES:
                found.append((node.lineno, f"from {node.module} import"))
            for alias in node.names:
                if alias.name in PROCESS_ATTRS:
                    found.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.Attribute) and node.attr in PROCESS_ATTRS:
            found.append((node.lineno, f".{node.attr}"))
        elif isinstance(node, ast.Name) and node.id in PROCESS_ATTRS:
            found.append((node.lineno, node.id))
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and "flatpak-spawn" in node.value and id(node) not in docs):
            found.append((node.lineno, "flatpak-spawn"))
    return found


def _sources():
    files = sorted(PACKAGE.rglob("*.py")) + sorted(PACKAGE.glob("*.in"))
    for path in files:
        yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8")


class TestHostPolicy(unittest.TestCase):
    def test_only_the_host_layer_starts_processes(self):
        offenders = []
        for rel, source in _sources():
            if rel in ALLOWED:
                continue
            for line, what in violations(source):
                offenders.append(f"{rel}:{line}: {what}")
        self.assertEqual(offenders, [], "run host commands through utils/host.py "
                         "(HostExecutor), not directly")

    def test_the_allowlist_names_files_that_exist_and_need_it(self):
        sources = dict(_sources())
        for rel in ALLOWED:
            with self.subTest(rel=rel):
                self.assertIn(rel, sources)
                self.assertTrue(violations(sources[rel]), f"{rel} no longer needs the allowlist")

    def test_the_launcher_script_is_scanned(self):
        self.assertIn("bootc_installer/bootc-installer.in", dict(_sources()))

    def test_detector(self):
        bad = {
            "import subprocess": "import subprocess",
            "from subprocess import run": "from subprocess import",
            "import os\nos.system('x')": ".system",
            "from gi.repository import Gio\nGio.Subprocess.new(['x'], 0)": ".Subprocess",
            "from gi.repository import GLib\nGLib.spawn_async(['x'])": ".spawn_async",
            "argv = ['flatpak-spawn', '--host', 'x']": "flatpak-spawn",
            "from os import posix_spawn": "import posix_spawn",
        }
        for source, what in bad.items():
            with self.subTest(source=source):
                self.assertIn(what, [w for _, w in violations(source)])
        clean = (
            '"""Runs on the host via flatpak-spawn."""\n'
            "# flatpak-spawn --host, through HostExecutor\n"
            "def f():\n    '''subprocess and flatpak-spawn in a docstring'''\n"
        )
        self.assertEqual(violations(clean), [])


if __name__ == "__main__":
    unittest.main()
