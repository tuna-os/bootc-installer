"""The confirm page's install plan (tuna-os/fisherman#371), through the
shared reader (bootc_shared.plan).

The plans are the golden files of the pinned fisherman
(fisherman/fisherman/cmd/fisherman/testdata/plan/). No test runs
fisherman: the page gets a fake request, and core.request_plan a fake
subprocess.
"""

import json
import os
import pathlib
import sys
import time
import types

import gi
import pytest

gi.require_version("Gtk", "3.0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bootc_shared import plan as install_plan  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

from tuna_installer_xfce import app, core, pages  # noqa: E402

# conftest replaces core.request_plan in every test; this is the real one.
REAL_REQUEST_PLAN = core.request_plan

REPO = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = REPO / "fisherman" / "fisherman" / "cmd" / "fisherman" / "testdata" / "plan"
SECRET = "correct-horse-battery-staple"

if not GOLDEN.is_dir():
    pytest.skip("no fisherman submodule", allow_module_level=True)


def golden(name):
    text = (GOLDEN / f"{name}.golden").read_text(encoding="utf-8").replace("@DIR@", "/dev")
    return install_plan.parse(text)


def recipe(disk="/dev/sda"):
    return {"disk": disk, "filesystem": "xfs", "hostname": "box",
            "image": "registry.example/os:1",
            "encryption": {"type": "luks-passphrase", "passphrase": SECRET}}


class _Win:
    def __init__(self, r):
        self.recipe = r
        self.pages = {
            "destination": types.SimpleNamespace(
                selected_disk=lambda: {"path": r["disk"], "title": "Disk"}),
            "source": types.SimpleNamespace(live_image=""),
        }

    def build_recipe(self):
        return dict(self.recipe)

    def refresh_nav(self):
        pass


@pytest.fixture
def page_for(monkeypatch):
    """A confirm page whose plan request answers `answer` at once, on this
    thread; the requests it made are in `page.requests`."""
    monkeypatch.delenv("TUNA_INSTALLER_DRY_RUN", raising=False)
    monkeypatch.setattr(core, "probe", lambda refresh=False: (None, "no probe in tests"))
    monkeypatch.setattr(pages.ConfirmPage, "_check_source", lambda self, r: None)
    monkeypatch.setattr(pages.ConfirmPage, "_check_network", lambda self: None)
    monkeypatch.setattr(pages.GLib, "idle_add", lambda fn, *a: fn(*a))

    def make(answer, r=None):
        page = pages.ConfirmPage(_Win(r or recipe()))
        page.requests = []

        def request(asked):
            page.requests.append(asked)
            return answer

        page.plan_request = request
        page.plan_start = lambda fn: fn()
        return page

    return make


def text(key, **values):
    return core.BRANDING.text(key, **values)


def test_a_plan_shows_the_disk_and_what_is_erased(page_for):
    page = page_for((golden("grub2-plain"), None))
    page.on_enter()
    shown = page.plan_label.get_text()
    lines = shown.splitlines()
    assert page.plan_label.get_visible()
    assert lines[0] == text("confirm_plan_title")
    assert lines[1] == "Installs to Fixture Disk"
    assert "serial number FIXTURE-SDA-SERIAL" in lines[2]
    assert text("confirm_plan_bound") in lines
    assert text("confirm_plan_wipe_disk", disk="/dev/sda") in lines
    # The recipe that was asked about is the install's, passphrase and all.
    assert page.requests == [recipe()]


def test_next_binds_the_recipe_to_the_planned_disk(page_for):
    page = page_for((golden("grub2-plain"), None))
    page.on_enter()
    assert page.bind_disk(recipe())["diskIdentity"] == {
        "serial": "FIXTURE-SDA-SERIAL", "wwn": "0x5000c500a1b2c3d4",
        "sizeBytes": 500107862016}
    # A plan for another disk than the recipe's binds nothing.
    assert "diskIdentity" not in page.bind_disk(recipe("/dev/sdb"))


def test_a_disk_without_serial_binds_its_size_and_says_so(page_for):
    page = page_for((golden("loop-image"), None), recipe("/dev/loop0"))
    page.on_enter()
    lines = page.plan_label.get_text().splitlines()
    assert lines[1] == "Installs to " + text("confirm_plan_unknown")
    assert "serial number " + text("confirm_plan_unknown") in lines[2]
    assert text("confirm_plan_unbound") in lines
    assert page.bind_disk(recipe("/dev/loop0"))["diskIdentity"] == {"sizeBytes": 8589934592}


def test_a_manual_layout_binds_nothing(page_for):
    page = page_for((golden("manual"), None))
    page.on_enter()
    assert "diskIdentity" not in page.bind_disk(recipe())


@pytest.mark.parametrize("answer", [
    (None, "fisherman plan failed (exit 2): unknown command"),
    (None, "fisherman plan gave no answer in 20 s"),
    "invalid",
])
def test_no_plan_leaves_the_page_and_the_recipe_as_before(page_for, answer):
    if answer == "invalid":
        answer = (golden("invalid"), None)
    page = page_for(answer)
    page.on_enter()
    assert not page.plan_label.get_visible()
    assert page.plan_label.get_text() == ""
    assert page.plan is None
    assert page.bind_disk(recipe()) == recipe()
    assert page.can_continue()


def test_a_late_reply_is_dropped(page_for):
    page = page_for((None, "no plan"))
    page.on_enter()
    page._on_plan(page.plan_generation - 1, (golden("grub2-plain"), None))
    assert page.plan is None
    assert not page.plan_label.get_visible()


def test_a_new_visit_forgets_the_old_plan(page_for):
    page = page_for((golden("grub2-plain"), None))
    page.on_enter()
    assert page.plan is not None
    # The next visit gets no answer before Next: the install is unbound.
    page.plan_start = lambda fn: None
    page.on_enter()
    assert page.plan is None
    assert page.bind_disk(recipe()) == recipe()


def test_a_dry_run_asks_no_fisherman(page_for, monkeypatch):
    page = page_for((golden("grub2-plain"), None))
    monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "1")
    page.on_enter()
    assert page.requests == []
    assert page.plan is None


def test_the_plan_is_asked_unprivileged_with_the_recipe_on_stdin(monkeypatch):
    calls = []

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = json.dumps({"protocol_version": 1, "valid": True, "errors": [],
                             "plan": {"target": {"layout": "manual"}, "destroys": []}})

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Proc()

    monkeypatch.setattr(core, "IN_FLATPAK", False)
    monkeypatch.setattr(install_plan.subprocess, "run", fake_run)
    result, error = REAL_REQUEST_PLAN(recipe())
    assert error is None and result["valid"]
    argv, kwargs = calls[0]
    assert argv == [core.FISHERMAN_PATH, "plan", "--json", "-"]
    assert "pkexec" not in argv and "sudo" not in " ".join(argv)
    assert SECRET not in " ".join(argv)
    assert json.loads(kwargs["input"])["encryption"]["passphrase"] == SECRET


def test_an_older_fisherman_or_a_failed_stage_is_no_plan(monkeypatch):
    class _Old:
        returncode = 2
        stderr = "unknown command \"plan\" for \"fisherman\"\n"
        stdout = ""

    monkeypatch.setattr(core, "IN_FLATPAK", False)
    monkeypatch.setattr(install_plan.subprocess, "run", lambda argv, **kw: _Old())
    result, error = REAL_REQUEST_PLAN(recipe())
    assert result is None and "exit 2" in error and SECRET not in error

    def no_stage():
        raise core.StageError("cannot stage fisherman")

    monkeypatch.setattr(core, "IN_FLATPAK", True)
    monkeypatch.setattr(core, "staged_fisherman", no_stage)
    result, error = REAL_REQUEST_PLAN(recipe())
    assert result is None and "stage" in error


def test_install_recipe_is_bound_only_through_the_confirm_page():
    planned = types.SimpleNamespace(bind_disk=lambda r: dict(r, diskIdentity={"sizeBytes": 1}))
    win = types.SimpleNamespace(build_recipe=recipe, pages={"confirm": planned})
    assert app.InstallerWindow.install_recipe(win)["diskIdentity"] == {"sizeBytes": 1}
    # A window without the confirm page (a test double) installs unbound.
    bare = types.SimpleNamespace(build_recipe=recipe, pages={})
    assert app.InstallerWindow.install_recipe(bare) == recipe()


def test_the_bound_recipe_goes_to_fisherman_on_stdin(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("TUNA_INSTALLER_DRY_RUN", raising=False)
    win = app.InstallerWindow(None)
    bound = dict(recipe(), diskIdentity={"serial": "S1", "sizeBytes": 1})
    monkeypatch.setattr(win, "install_recipe", lambda: bound)
    monkeypatch.setattr(core, "fisherman_argv", lambda: ["true"])
    spawned = []
    real_spawn = app.spawn_fisherman

    def spawn(argv, stdin_data=b""):
        spawned.append((list(argv), stdin_data))
        return real_spawn(["true"])

    monkeypatch.setattr(app, "spawn_fisherman", spawn)
    try:
        win.start_install(win.pages["progress"])
        (argv, stdin_data), = spawned
        assert SECRET not in " ".join(argv)
        sent = json.loads(stdin_data)
        assert sent["diskIdentity"] == {"serial": "S1", "sizeBytes": 1}
        deadline = time.time() + 10
        while win._install_pid is not None and time.time() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.01)
    finally:
        GLib.idle_add(lambda: False)
        win.destroy()
