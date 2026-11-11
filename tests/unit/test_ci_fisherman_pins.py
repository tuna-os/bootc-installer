"""shared/ci/fisherman_pins.py: the fisherman pin is the submodule gitlink.

Every Flatpak builds fisherman from the submodule (shared/flatpak/
fisherman.json for the four frontends, ../fisherman for GNOME), so the
gitlink is the only pin. The script moves it and refuses to run while a
manifest pins a tuna-os/fisherman git source, because it would leave that
second pin behind. These tests run it in throwaway git repositories, with no
network.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "shared", "ci"))
import fisherman_pins as fp  # noqa: E402

OLD = "a" * 40
NEW = "b" * 40
URL = "https://github.com/tuna-os/fisherman.git"
SHARED_MODULE = "../../../shared/flatpak/fisherman.json"


def manifest(app_id, modules):
    return {"app-id": app_id, "runtime": "r", "modules": [
        {"name": "dep", "sources": [{"type": "archive", "url": "https://example.invalid/x.tgz"}]},
        *modules,
        {"name": "app", "sources": [{"type": "dir", "path": ".."}]},
    ]}


def git_source(commit=OLD, url=URL):
    return {"type": "git", "url": url, "commit": commit}


def write(repo, rel, data):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout


def gitlink(repo):
    return git(repo, "ls-files", "-s", "fisherman").split()[1]


@pytest.fixture
def repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    r = str(tmp_path)
    git(r, "init", "-q")
    git(r, "update-index", "--add", "--cacheinfo", f"160000,{OLD},fisherman")
    write(r, "shared/flatpak/fisherman.json",
          {"name": "fisherman", "sources": [{"type": "dir", "path": "../../fisherman"}]})
    for name in ("alpha", "beta"):
        write(r, f"frontends/{name}/flatpak/org.example.{name.title()}.json",
              manifest(f"org.example.{name.title()}", [SHARED_MODULE]))
    write(r, "flatpak/org.example.Root.json", manifest("org.example.Root", [
        {"name": "fisherman", "sources": [{"type": "dir", "path": "../fisherman"}]}]))
    # Not an app manifest (cargo-sources.json is a list): never read.
    write(r, "frontends/alpha/flatpak/cargo-sources.json",
          [{"type": "git", "url": URL, "commit": OLD}])
    return r


def test_the_gitlink_moves_and_is_staged(repo):
    fp.set_pin(repo, NEW)
    # gitlink() reads the index: the new commit is staged for `git commit`.
    assert gitlink(repo) == NEW


def test_already_current_is_a_no_op(repo):
    fp.set_pin(repo, NEW)
    fp.set_pin(repo, NEW)
    assert gitlink(repo) == NEW


@pytest.mark.parametrize("where", ["frontend", "nested", "include", "root"])
def test_a_second_pin_fails_and_writes_nothing(repo, where):
    pinned = {"name": "backend", "sources": [git_source()]}
    if where == "frontend":
        write(repo, "frontends/gamma/flatpak/org.example.Gamma.json",
              manifest("org.example.Gamma", [pinned]))
        name = "Gamma"
    elif where == "nested":
        write(repo, "frontends/gamma/flatpak/org.example.Gamma.json",
              manifest("org.example.Gamma", [{"name": "outer", "modules": [pinned]}]))
        name = "Gamma"
    elif where == "include":
        # The shared module itself goes back to a git pin: both includers fail.
        write(repo, "shared/flatpak/fisherman.json", pinned)
        name = "Alpha"
    else:
        write(repo, "flatpak/org.example.Root.json", manifest("org.example.Root", [pinned]))
        name = "Root"

    with pytest.raises(fp.PinError, match=rf"{name}\.json.*pins a tuna-os/fisherman git source"):
        fp.set_pin(repo, NEW)
    assert gitlink(repo) == OLD


def test_another_git_source_is_not_a_pin(repo):
    write(repo, "frontends/gamma/flatpak/org.example.Gamma.json", manifest("org.example.Gamma", [
        {"name": "lib", "sources": [git_source(url="https://github.com/other/repo.git")]}]))
    fp.set_pin(repo, NEW)
    assert gitlink(repo) == NEW


def test_a_missing_include_fails(repo):
    write(repo, "frontends/gamma/flatpak/org.example.Gamma.json",
          manifest("org.example.Gamma", ["../../../shared/flatpak/nope.json"]))
    with pytest.raises(fp.PinError, match="nope.json does not exist"):
        fp.set_pin(repo, NEW)
    assert gitlink(repo) == OLD


def test_rejects_a_short_or_bad_sha(repo):
    with pytest.raises(fp.PinError, match="not a full commit sha"):
        fp.set_pin(repo, "b" * 7)
    assert gitlink(repo) == OLD


@pytest.mark.parametrize("url,ok", [
    ("https://github.com/tuna-os/fisherman.git", True),
    ("https://github.com/tuna-os/fisherman", True),
    ("https://github.com/tuna-os/fisherman/", True),
    ("git@github.com:tuna-os/fisherman.git", True),
    ("https://github.com/tuna-os/fisherman-fork.git", False),
    ("https://github.com/someone/fisherman.git", False),
    ("https://gitlab.com/tuna-os/fisherman.git", False),
    (None, False),
])
def test_fisherman_url_matching(url, ok):
    assert fp.is_fisherman_url(url) is ok


def test_cli_reports_errors_without_a_traceback(repo, capsys):
    write(repo, "frontends/gamma/flatpak/org.example.Gamma.json",
          manifest("org.example.Gamma", [{"name": "b", "sources": [git_source()]}]))
    assert fp.main(["--repo", repo, "--commit", NEW]) == 1
    assert "::error::" in capsys.readouterr().err
    assert gitlink(repo) == OLD


def test_the_real_manifests_have_no_second_pin():
    """The checked-in manifests satisfy what the script relies on."""
    manifests = fp.app_manifests(REPO)
    assert len(manifests) >= 6, manifests  # GNOME x2 + four frontends
    assert fp.second_pins(REPO) == {}
