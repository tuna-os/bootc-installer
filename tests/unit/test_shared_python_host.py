"""bootc_shared: how fisherman is reached, the network targets, the log
redaction and the logo sources.

GNOME and XFCE each had this logic, and the two had drifted (#338). One
copy is in shared/python/bootc_shared/; these tests hold it. Each frontend
keeps the tests of its own half (tests/unit/test_fisherman_runner.py,
frontends/xfce/tests/test_core.py, and so on).
"""

import json
import os
import pathlib
import stat

import pytest
from bootc_shared import branding, fisherman_host, network, redact

REPO = pathlib.Path(__file__).resolve().parents[2]
PROGRESS = REPO / "shared" / "progress"
SPEC = json.loads((PROGRESS / "recovery-key-cases.json").read_text(encoding="utf-8"))
KEY = SPEC["key"]


# ── fisherman_host: the command ──────────────────────────────────────────────

def test_the_unprivileged_commands_never_escalate():
    for purpose, tail in (("probe", ["probe", "--json"]),
                          ("validate", ["validate", "--json", "--partial", "-"]),
                          ("validate-full", ["validate", "--json", "-"]),
                          ("plan", ["plan", "--json", "-"])):
        assert fisherman_host.command(purpose, in_flatpak=False) == [
            "/usr/local/bin/fisherman", *tail]
        assert fisherman_host.command(purpose, in_flatpak=True, host_path="/c/f") == [
            "flatpak-spawn", "--host", "/c/f", *tail]
        for flatpak in (False, True):
            argv = fisherman_host.command(purpose, in_flatpak=flatpak, live=True, host_path="/c/f")
            assert "pkexec" not in " ".join(argv) and "sudo" not in " ".join(argv)


def test_the_install_reads_the_recipe_on_stdin_inside_a_bash():
    assert fisherman_host.command("install", in_flatpak=False) == [
        "bash", "-c", "pkexec /usr/local/bin/fisherman -; exit $?"]
    assert fisherman_host.command("install", in_flatpak=True, host_path="/c/f") == [
        "flatpak-spawn", "--host", "bash", "-c", "pkexec /c/f -; exit $?"]
    # `live` is for a native install only: a Flatpak always has polkit's
    # host agent, and its staged binary.
    assert fisherman_host.command("install", in_flatpak=True, live=True, host_path="/c/f")[-1] \
        == "pkexec /c/f -; exit $?"


def test_live_media_uses_sudo_that_does_not_ask():
    """The same line in all five frontends: `sudo -n`. With no terminal, a
    sudo that asks for a password waits for ever."""
    assert fisherman_host.command("install", in_flatpak=False, live=True)[-1] == \
        "sudo -n /usr/local/bin/fisherman -; exit $?"


def test_one_command_with_an_optional_log_path():
    """XFCE reads the pipes; GNOME sends the output to a file that it
    tails. The same command, with one more part."""
    assert fisherman_host.command("install", in_flatpak=False, log_path="/l/out.log")[-1] == \
        "pkexec /usr/local/bin/fisherman - >/l/out.log 2>&1; exit $?"
    script = fisherman_host.command("install", in_flatpak=True, host_path="/a b/f",
                                    log_path="/a b/$HOME.log")[-1]
    assert script == "pkexec '/a b/f' - >'/a b/$HOME.log' 2>&1; exit $?"


def test_a_flatpak_command_needs_the_staged_binary():
    for purpose in fisherman_host.PURPOSES:
        with pytest.raises(fisherman_host.StageError):
            fisherman_host.command(purpose, in_flatpak=True)
    with pytest.raises(ValueError):
        fisherman_host.command("reboot", in_flatpak=False)


# ── fisherman_host: the stage ────────────────────────────────────────────────

@pytest.fixture
def stage_env(tmp_path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    source = tmp_path / "fisherman"
    source.write_bytes(b"\x7fELF bundled fisherman")
    return {"HOME": str(home), "XDG_CACHE_HOME": str(home / "cache")}, str(source)


def test_the_stage_is_private_and_the_host_must_see_the_same_bytes(stage_env):
    env, source = stage_env
    asked = []

    def host_hash(path):
        asked.append(path)
        return fisherman_host.sha256(path)

    staged = fisherman_host.stage(source, environ=env, host_hash=host_hash)
    assert staged == os.path.join(env["XDG_CACHE_HOME"], "bootc-installer", "fisherman")
    assert asked == [staged]
    assert stat.S_IMODE(os.stat(staged).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(os.path.dirname(staged)).st_mode) == 0o700
    with pytest.raises(fisherman_host.StageError, match="byte-identical"):
        fisherman_host.stage(source, environ=env, host_hash=lambda path: "0" * 64)
    with pytest.raises(fisherman_host.StageError, match="byte-identical"):
        fisherman_host.stage(source, environ=env, host_hash=lambda path: "")


def test_the_cache_must_be_flatpaks_own_never_home_dot_cache(stage_env):
    env, source = stage_env
    assert fisherman_host.stage_dir(env) == os.path.join(env["XDG_CACHE_HOME"], "bootc-installer")
    for cache in ("", "relative/cache"):
        with pytest.raises(fisherman_host.StageError, match="absolute"):
            fisherman_host.stage(source, environ={**env, "XDG_CACHE_HOME": cache},
                                 host_hash=fisherman_host.sha256)


def test_a_home_that_is_not_the_users_own_stops_the_stage(stage_env, tmp_path):
    """The check GNOME had and XFCE did not: a HOME that is a symlink, or
    that a different user owns, means the cache below it is not private."""
    env, source = stage_env
    link = tmp_path / "link"
    link.symlink_to(env["HOME"], target_is_directory=True)
    called = []
    with pytest.raises(fisherman_host.StageError, match="symlink"):
        fisherman_host.stage(source, environ={**env, "HOME": str(link)},
                             host_hash=lambda path: called.append(path) or "")
    assert not called, "nothing is copied and the host is not asked"
    assert not os.path.exists(os.path.join(env["XDG_CACHE_HOME"], "bootc-installer"))
    # The mode of HOME is not judged (a 0755 home is normal).
    os.chmod(env["HOME"], 0o755)
    assert fisherman_host.stage(source, environ=env, host_hash=fisherman_host.sha256)


def test_an_unsafe_cache_stops_the_stage(stage_env):
    env, source = stage_env
    cache = fisherman_host.stage_dir(env)
    os.makedirs(cache)
    os.chmod(cache, 0o777)
    with pytest.raises(fisherman_host.StageError, match="writable"):
        fisherman_host.stage(source, environ=env, host_hash=fisherman_host.sha256)
    os.chmod(cache, 0o700)
    os.symlink("/etc/passwd", os.path.join(cache, "fisherman"))
    with pytest.raises(fisherman_host.StageError, match="symlink"):
        fisherman_host.stage(source, environ=env, host_hash=fisherman_host.sha256)
    os.remove(os.path.join(cache, "fisherman"))
    with pytest.raises(fisherman_host.StageError, match="cannot stage"):
        fisherman_host.stage(source + ".absent", environ=env, host_hash=fisherman_host.sha256)


def test_the_host_hash_goes_through_the_portal(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = "abc123  /cache/fisherman\n"

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Result()

    monkeypatch.setattr(fisherman_host.subprocess, "run", fake_run)
    assert fisherman_host.host_sha256("/cache/fisherman") == "abc123"
    assert calls == [["flatpak-spawn", "--host", "sha256sum", "--", "/cache/fisherman"]]
    Result.returncode = 1
    assert fisherman_host.host_sha256("/cache/fisherman") == ""


# ── network ──────────────────────────────────────────────────────────────────

def test_the_registry_of_the_image_is_probed_first():
    assert network.connectivity_targets("quay.io/centos-bootc/centos-bootc:c10s") == [
        ("quay.io", 443), ("ghcr.io", 443), ("8.8.8.8", 53)]
    assert network.connectivity_targets("ghcr.io/example/os:latest") == [
        ("ghcr.io", 443), ("8.8.8.8", 53)]
    assert network.connectivity_targets("") == list(network.SHARED_TARGETS)
    assert network.connectivity_targets(None) == list(network.SHARED_TARGETS)


def test_registry_target():
    target = network.registry_target
    assert target("registry.example:5000/os/atlas:1") == ("registry.example", 5000)
    assert target("localhost/os:1") == ("localhost", 443)
    assert target("docker://quay.io/a/b:1") == ("quay.io", 443)
    assert target("library/ubuntu:26.04") == (network.DEFAULT_REGISTRY, 443)
    assert target("ubuntu") == (network.DEFAULT_REGISTRY, 443)
    assert target("") is None and target("   ") is None


def test_has_connectivity_stops_at_the_first_target_that_answers():
    tried = []

    class Sock:
        def close(self):
            tried.append("closed")

    def connect(address, timeout):
        tried.append(address)
        if address[0] == "quay.io":
            raise OSError("blocked")
        return Sock()

    assert network.has_connectivity("quay.io/a/b:1", connect=connect, environ={}) is True
    assert tried == [("quay.io", 443), ("ghcr.io", 443), "closed"]

    def offline(address, timeout):
        raise OSError("offline")

    assert network.has_connectivity("quay.io/a/b:1", connect=offline, environ={}) is False


def test_a_harness_turns_the_check_off_with_a_value():
    def never(address, timeout):
        raise AssertionError("no probe when the check is off")

    for name in network.SKIP_ENV_VARS:
        assert network.has_connectivity(connect=never, environ={name: "1"}) is True
        # An empty variable, or "0", does not turn the check off.
        assert network.skip_requested({name: ""}) is False
        assert network.skip_requested({name: "0"}) is False
    assert set(network.SKIP_ENV_VARS) == {"VANILLA_SKIP_CONN_CHECK",
                                          "TUNA_INSTALLER_SKIP_CONN_CHECK"}


# ── redact ───────────────────────────────────────────────────────────────────

def test_the_placeholder_is_the_shared_one():
    assert redact.REDACTED == SPEC["placeholder"]


@pytest.mark.parametrize("case", SPEC["lines"], ids=lambda case: case["name"])
def test_each_line_case_of_the_fixture(case):
    known = KEY if case["known_key"] else ""
    assert redact.redact_recovery_key(case["line"], known) == case["redacted"]


def test_a_line_writer_learns_the_key_from_the_event():
    transcript = (PROGRESS / SPEC["transcript"]).read_text(encoding="utf-8").splitlines(True)
    redactor = redact.LogRedactor()
    out = [redactor.line(line) for line in transcript]
    assert redactor.known_key == KEY
    assert KEY not in "".join(out)
    assert out == [(SPEC["redacted_event"] + "\n") if '"recovery_key"' in line else line
                   for line in transcript]
    assert redactor.line(f"enrolled with {KEY}.\n") == f"enrolled with {SPEC['placeholder']}.\n"
    # Before the event the writer does not know the key.
    assert redact.LogRedactor().line(f"enrolled with {KEY}.\n") == f"enrolled with {KEY}.\n"
    # A redacted event does not teach the placeholder as a key.
    again = redact.LogRedactor()
    again.line(SPEC["redacted_event"] + "\n")
    assert again.known_key == ""


def test_a_file_is_scrubbed_in_place(tmp_path):
    path = tmp_path / "out.log"
    path.write_text(f'{{"type":"recovery_key","key":"{KEY}"}}\nplain\n')
    os.chmod(path, 0o600)
    assert KEY not in redact.read_log_redacted(str(path))
    assert redact.scrub_log_file(str(path), KEY) is True
    assert KEY not in path.read_text() and "plain" in path.read_text()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert redact.scrub_log_file(str(tmp_path / "absent.log")) is True
    assert redact.read_log_redacted(str(tmp_path / "absent.log")) is None


# ── logo sources ─────────────────────────────────────────────────────────────

def test_logo_sources_follow_the_fixture():
    fixture = REPO / "shared" / "branding" / "fixtures" / "logo-paths.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 6
    for case in cases:
        assert branding.logo_source(case["spec"], case["in_flatpak"]) == (
            case["kind"], case["value"]), case


def test_a_resource_is_an_absolute_path_in_the_applications_own_resources():
    assert branding.logo_source("resource:///org/example/logo.svg", True) == (
        "resource", "/org/example/logo.svg")
    # Not a path in the resources: nothing to show, and never a fetch.
    assert branding.logo_source("resource://org/example/logo.svg", False) == ("none", "")
    assert branding.logo_source("https://example.com/logo.png", False) == ("none", "")
    assert branding.logo_source("relative/logo.png", False) == ("none", "")
    assert branding.logo_source(None, False) == ("none", "")
