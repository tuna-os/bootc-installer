"""The GNOME frontend starts no thread that can outlive the window (#410).

`Gtk.Application.quit()` only makes `app.run()` return. Python then joins
every non-daemon thread before the process ends, and until it does the
window stays on screen, unresponsive: Exit in "Exit Installer?" seemed to
do nothing while the GeoIP lookup of the timezone page waited on the
network. Every thread in the code the GNOME frontend runs is a daemon.

The scan reads the source, so it needs no display:

- each `Thread(...)` or `Timer(...)` call passes `daemon=True`;
- each subclass of `Thread` passes `daemon=True` to `Thread.__init__`;
- nothing uses a `ThreadPoolExecutor`, whose workers are joined at exit.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCES = (ROOT / "bootc_installer", ROOT / "shared" / "python")


def _files():
    for base in SOURCES:
        yield from sorted(base.rglob("*.py"))


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _daemon_true(call):
    return any(kw.arg == "daemon" and isinstance(kw.value, ast.Constant)
               and kw.value.value is True for kw in call.keywords)


def _is_super_init(call):
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "__init__"):
        return False
    owner = func.value
    return ((isinstance(owner, ast.Call) and _name(owner.func) == "super")
            or _name(owner) == "Thread")


def _violations(path, root=ROOT):
    def _where(path, node):
        return f"{path.relative_to(root)}:{node.lineno}"

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _name(node.func)
            if name in ("Thread", "Timer") and not _daemon_true(node):
                found.append(f"{_where(path, node)}: {name}() without daemon=True")
            elif name == "ThreadPoolExecutor":
                found.append(f"{_where(path, node)}: ThreadPoolExecutor joins its workers at exit")
        elif isinstance(node, ast.ClassDef) and any(_name(b) == "Thread" for b in node.bases):
            inits = [c for c in ast.walk(node) if isinstance(c, ast.Call) and _is_super_init(c)]
            if not any(_daemon_true(c) for c in inits):
                found.append(f"{_where(path, node)}: Thread subclass {node.name} "
                             "does not pass daemon=True to Thread.__init__")
    return found


def test_the_scan_covers_the_gnome_sources():
    names = {p.name for p in _files()}
    assert {"timezone.py", "run_async.py", "validate.py"} <= names


def test_every_thread_is_a_daemon():
    found = [v for path in _files() for v in _violations(path)]
    assert not found, "\n".join(found)


def test_the_scan_catches_a_non_daemon_thread(tmp_path):
    src = tmp_path / "bad.py"
    src.write_text(
        "import threading\n"
        "threading.Thread(target=print).start()\n"
        "threading.Thread(target=print, daemon=False).start()\n"
        "threading.Timer(1, print)\n"
        "class Job(threading.Thread):\n"
        "    def __init__(self):\n"
        "        super().__init__(target=print)\n"
        "threading.Thread(target=print, daemon=True).start()\n",
        encoding="utf-8")
    found = _violations(src, root=tmp_path)
    assert sorted(int(f.split(":")[1]) for f in found) == [2, 3, 4, 5]
