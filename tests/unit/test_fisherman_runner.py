"""Headless contract tests for the fisherman host execution boundary."""

import os
from unittest.mock import patch

from bootc_installer.utils import fisherman_runner


def test_native_argv_uses_pkexec_and_preserves_recipe_argument():
    argv = fisherman_runner.build_argv(
        "/tmp/recipe.json",
        in_flatpak=False,
        live_iso=False,
        log_path="/tmp/fisherman.log",
    )

    assert argv[-1] == "/tmp/recipe.json"
    assert "pkexec /usr/local/bin/fisherman" in argv[argv.index("-c") + 1]


def test_flatpak_argv_runs_redirect_on_host():
    with patch.dict(os.environ, {}, clear=True):
        argv = fisherman_runner.build_argv(
            "/tmp/recipe.json",
            in_flatpak=True,
            host_path="/private/fisherman",
            log_path="/private/fisherman.log",
        )

    assert argv[:3] == ["flatpak-spawn", "--host", "bash"]
    command = argv[argv.index("-c") + 1]
    assert 'pkexec "/private/fisherman"' in command
    assert '>"/private/fisherman.log"' in command


def test_native_staging_is_a_noop():
    assert fisherman_runner.stage_on_host(in_flatpak=False)
