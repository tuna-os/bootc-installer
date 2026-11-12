"""bootc_shared.plan: the reader for `fisherman plan --json -`
(fisherman/docs/PLAN.md, tuna-os/fisherman#371).

The cases are the golden files of the pinned fisherman
(fisherman/fisherman/cmd/fisherman/testdata/plan/), so a field that
fisherman renames fails here. No test runs fisherman: `run` gets a fake
subprocess.
"""

import json
import pathlib
import subprocess

import pytest
from bootc_shared import fisherman_host
from bootc_shared import plan as install_plan
from bootc_shared.branding import COPY_DEFAULTS

REPO = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = REPO / "fisherman" / "fisherman" / "cmd" / "fisherman" / "testdata" / "plan"
SECRET = "correct-horse-battery-staple"

if not GOLDEN.is_dir():
    pytest.skip("no fisherman submodule", allow_module_level=True)


DIGEST = "sha256:" + "ab" * 32


def golden(name):
    """A golden plan, with the fixture directory as /dev and a fixed
    digest for the one a fisherman with `plan.binding` writes."""
    return ((GOLDEN / f"{name}.golden").read_text(encoding="utf-8")
            .replace("@DIR@", "/dev").replace("@PLAN_DIGEST@", DIGEST))


def with_binding(plan, **binding):
    """`plan` as a fisherman with `plan.binding` (tuna-os/fisherman#472)
    prints it."""
    out = dict(plan)
    out["binding"] = binding or {"digest": DIGEST, "read_image": False}
    return out


def result(name):
    return install_plan.parse(golden(name))


def text(key, **values):
    line = COPY_DEFAULTS.get(key, "")
    for k, v in values.items():
        line = line.replace("{" + k + "}", str(v))
    return line


def recipe(**changes):
    out = {"disk": "/dev/sda", "image": "ghcr.io/example/os:stable",
           "encryption": {"type": "luks-passphrase", "passphrase": SECRET}}
    out.update(changes)
    return out


# ── the command ──────────────────────────────────────────────────────────────

def test_the_command_is_unprivileged_and_reads_stdin():
    assert install_plan.argv(["/usr/local/bin/fisherman"]) == [
        "/usr/local/bin/fisherman", "plan", "--json", "-"]
    assert install_plan.argv(["flatpak-spawn", "--host", "/c/f"]) == \
        fisherman_host.command("plan", in_flatpak=True, host_path="/c/f")
    for flatpak in (False, True):
        argv = fisherman_host.command("plan", in_flatpak=flatpak, live=True, host_path="/c/f")
        assert "pkexec" not in argv and "sudo" not in " ".join(argv)


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_the_recipe_goes_on_stdin_never_on_argv(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Proc(0, golden("grub2-plain"))

    monkeypatch.setattr(install_plan.subprocess, "run", fake_run)
    out = install_plan.run(["fisherman", "plan", "--json", "-"], recipe())
    assert out["valid"] is True
    argv, kwargs = calls[0]
    assert SECRET not in " ".join(argv)
    assert json.loads(kwargs["input"])["encryption"]["passphrase"] == SECRET
    assert kwargs["timeout"] == install_plan.TIMEOUT_SECONDS
    assert kwargs["check"] is False


def test_exit_one_is_an_invalid_recipe_not_an_error(monkeypatch):
    monkeypatch.setattr(install_plan.subprocess, "run",
                        lambda argv, **kw: _Proc(1, golden("identity-serial-changed")))
    out = install_plan.run(["fisherman"], recipe())
    assert out["valid"] is False and out["plan"] is None
    assert out["errors"][0]["code"] == "disk_identity_mismatch"


@pytest.mark.parametrize("proc", [
    # An older fisherman: no plan command, a usage line, exit 2.
    _Proc(2, "", "unknown command plan"),
    # An older fisherman that took "plan" for a recipe path and printed
    # one progress error event.
    _Proc(1, json.dumps({"type": "error", "message": "open plan: no such file"})),
    _Proc(1, "", ""),
    _Proc(0, json.dumps({"protocol_version": 2, "valid": True, "errors": [], "plan": {}})),
    _Proc(0, json.dumps({"protocol_version": 1, "valid": True, "errors": [], "plan": None})),
])
def test_an_unreadable_answer_is_a_plan_error(monkeypatch, proc):
    monkeypatch.setattr(install_plan.subprocess, "run", lambda argv, **kw: proc)
    with pytest.raises(install_plan.PlanError):
        install_plan.run(["fisherman"], recipe())


@pytest.mark.parametrize("exc", [
    FileNotFoundError("flatpak-spawn"),
    subprocess.TimeoutExpired(["fisherman"], 20),
    OSError("denied"),
])
def test_a_command_that_cannot_run_is_a_plan_error_without_the_recipe(monkeypatch, exc):
    def fake_run(argv, **kwargs):
        raise exc

    monkeypatch.setattr(install_plan.subprocess, "run", fake_run)
    with pytest.raises(install_plan.PlanError) as caught:
        install_plan.run(["fisherman"], recipe())
    assert SECRET not in str(caught.value)


# ── the goldens ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.golden")), ids=lambda p: p.stem)
def test_every_golden_parses_and_holds_no_secret(path):
    out = install_plan.parse(path.read_text(encoding="utf-8"))
    assert (out["plan"] is None) == (not out["valid"])
    lines = install_plan.rows(out["plan"], text)
    for title, detail in lines:
        assert title and "{" not in title and "{" not in detail


def test_the_binding_copies_what_the_disk_reports():
    plan = result("grub2-plain")["plan"]
    assert install_plan.disk_identity(plan) == {
        "serial": "FIXTURE-SDA-SERIAL", "wwn": "0x5000c500a1b2c3d4", "sizeBytes": 500107862016}
    bound = install_plan.bind(recipe(), plan)
    assert bound["diskIdentity"] == install_plan.disk_identity(plan)
    assert "diskIdentity" not in recipe()


def test_an_unknown_value_is_left_out_of_the_binding():
    plan = result("loop-image")["plan"]
    assert install_plan.disk_identity(plan) == {"sizeBytes": 8589934592}
    assert install_plan.bind(recipe(disk="/dev/loop0"), plan)["diskIdentity"] == {
        "sizeBytes": 8589934592}


def test_no_binding_without_a_plan_for_this_disk():
    plan = result("grub2-plain")["plan"]
    for case in (recipe(disk="/dev/sdb"), recipe(disk="")):
        assert install_plan.bind(case, plan) is case
    assert install_plan.bind(recipe(), None) == recipe()
    manual = result("manual")["plan"]
    assert install_plan.disk_identity(manual) == {}
    assert "diskIdentity" not in install_plan.bind(recipe(), manual)


def test_the_plan_binding_is_copied_as_plan_binding():
    plan = with_binding(result("grub2-plain")["plan"], digest=DIGEST, read_image=True)
    assert install_plan.plan_binding(plan) == {"digest": DIGEST, "readImage": True}
    bound = install_plan.bind(recipe(), plan)
    assert bound["planBinding"] == {"digest": DIGEST, "readImage": True}
    assert bound["diskIdentity"] == install_plan.disk_identity(plan)
    assert "planBinding" not in recipe()


def test_the_goldens_binding_is_copied():
    """The pinned fisherman's own `plan.binding`, with and without
    `--read-image`."""
    for name, read_image in (("grub2-plain", False), ("read-image-registry", True)):
        plan = result(name)["plan"]
        if "binding" not in plan:
            pytest.skip("the pinned fisherman has no plan.binding")
        assert install_plan.bind(recipe(), plan)["planBinding"] == {
            "digest": DIGEST, "readImage": read_image}


def test_a_plan_without_a_binding_binds_the_disk_only():
    """An older fisherman prints no `plan.binding`: no `planBinding`."""
    plan = result("grub2-plain")["plan"]
    plan.pop("binding", None)
    assert install_plan.plan_binding(plan) == {}
    bound = install_plan.bind(recipe(), plan)
    assert "planBinding" not in bound
    assert "diskIdentity" in bound


@pytest.mark.parametrize("binding", [
    None, "sha256:" + "ab" * 32, {}, {"digest": ""}, {"digest": "sha256:ABC"},
    {"digest": "sha256:" + "AB" * 32}, {"digest": "md5:" + "ab" * 16},
    {"digest": "sha256:" + "ab" * 32 + "\n"}, {"digest": 7}, {"read_image": True},
])
def test_a_malformed_binding_is_not_copied(binding):
    plan = dict(result("grub2-plain")["plan"])
    plan["binding"] = binding
    assert install_plan.plan_binding(plan) == {}
    assert "planBinding" not in install_plan.bind(recipe(), plan)


def test_read_image_is_copied_only_as_a_boolean():
    plan = with_binding({}, digest=DIGEST, read_image="yes")
    assert install_plan.plan_binding(plan) == {"digest": DIGEST}


def test_no_plan_binding_for_another_disk():
    plan = with_binding(result("grub2-plain")["plan"])
    for case in (recipe(disk="/dev/sdb"), recipe(disk="")):
        assert install_plan.bind(case, plan) is case


def test_a_manual_layout_is_bound_to_its_plan_not_a_disk():
    manual = with_binding(result("manual")["plan"])
    bound = install_plan.bind(recipe(), manual)
    assert bound["planBinding"] == {"digest": DIGEST, "readImage": False}
    assert "diskIdentity" not in bound


def test_every_plan_error_code_has_a_copy_key():
    for code in ("plan_stale", "plan_binding_invalid",
                 "disk_identity_mismatch", "disk_identity_invalid"):
        line = COPY_DEFAULTS["validate_" + code]
        assert line and "{" not in line


def test_the_target_rows_mark_unknown_values():
    rows = install_plan.target_rows(result("grub2-plain")["plan"], text)
    assert rows[0] == ("Installs to Fixture Disk",
                       "/dev/sda, 465.8 GiB, serial number FIXTURE-SDA-SERIAL")
    assert rows[1][0] == COPY_DEFAULTS["confirm_plan_bound"]
    loop = install_plan.target_rows(result("loop-image")["plan"], text)
    assert loop[0] == ("Installs to unknown", "/dev/loop0, 8 GiB, serial number unknown")
    assert loop[1][0] == COPY_DEFAULTS["confirm_plan_unbound"]
    assert install_plan.target_rows(result("manual")["plan"], text) == []


def test_each_destroyed_device_has_a_line():
    assert install_plan.destroy_rows(result("grub2-plain")["plan"], text) == [
        ("Everything on /dev/sda is erased.", "")]
    assert install_plan.destroy_rows(result("manual")["plan"], text) == [
        ("/dev/sda3 is formatted. Its data is erased.", ""),
        ("/dev/sda4 becomes swap space. Its data is erased.", ""),
        ("/dev/sda2 is formatted. Its data is erased.", "")]
    # An effect this build has no line for still says the data is lost.
    plan = {"destroys": [{"device": "/dev/sdz", "effect": "trim"}]}
    assert install_plan.destroy_rows(plan, text) == [("/dev/sdz is formatted. Its data is erased.", "")]


def test_every_effect_has_a_copy_key():
    for effect in install_plan.EFFECTS:
        assert COPY_DEFAULTS[install_plan.COPY_PREFIX + effect]
    effects = set()
    for path in GOLDEN.glob("*.golden"):
        plan = install_plan.parse(path.read_text(encoding="utf-8"))["plan"]
        effects |= {effect for _device, effect in install_plan.destroys(plan)}
    assert effects <= set(install_plan.EFFECTS)
