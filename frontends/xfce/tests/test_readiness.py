# test_readiness.py - Unit tests for tuna_installer_xfce.readiness (stamp)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# readiness.py records, in a file the smoke test reads over SSH, that a
# window really mapped (see the module docstring — the COSMIC leg once ran
# with no window while `flatpak ps` stayed green). It is pure stdlib, so
# these tests run headlessly.

import os

import pytest

from tuna_installer_xfce import readiness


class TestStampPath:
    def test_uses_runtime_dir(self, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        assert readiness.stamp_path() == "/run/user/1000/tuna-installer-ready"

    def test_none_without_runtime_dir(self, monkeypatch):
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        assert readiness.stamp_path() is None


class TestWriteStamp:
    def test_writes_expected_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        readiness.write_stamp("org.tunaos.InstallerXfce", "InstallerWindow", page="welcome")
        body = (tmp_path / readiness.STAMP_NAME).read_text()
        assert "app_id=org.tunaos.InstallerXfce" in body
        assert "window=InstallerWindow" in body
        assert "signal=gtk-map" in body
        assert "page=welcome" in body
        assert "mapped_at=" in body

    def test_writes_without_page(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        readiness.write_stamp("org.tunaos.InstallerXfce", "InstallerWindow")
        body = (tmp_path / readiness.STAMP_NAME).read_text()
        assert "page=" not in body

    def test_atomic_replace_leaves_no_tmp_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        readiness.write_stamp("a", "InstallerWindow")
        leftovers = [p for p in os.listdir(tmp_path) if ".tmp" in p]
        assert leftovers == []

    def test_no_runtime_dir_is_best_effort(self, tmp_path, monkeypatch):
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        # Must not raise: a frontend that cannot write its stamp must still install.
        readiness.write_stamp("a", "InstallerWindow")


class TestArm:
    def test_connects_map_handler_and_stamps(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        handlers = {}

        class FakeWidget:
            pass

        class FakeWindow:
            def connect(self, signal, handler):
                handlers[signal] = handler

        window = FakeWindow()
        readiness.arm(window, app_id="org.tunaos.InstallerXfce",
                      page_getter=lambda: "summary")
        assert "map" in handlers

        # Simulate the widget mapping.
        handlers["map"](FakeWidget())
        body = (tmp_path / readiness.STAMP_NAME).read_text()
        assert "window=FakeWidget" in body
        assert "page=summary" in body

    def test_page_getter_failure_still_stamps(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        handlers = {}

        class FakeWidget:
            pass

        class FakeWindow:
            def connect(self, signal, handler):
                handlers[signal] = handler

        def boom():
            raise RuntimeError("page not ready")

        readiness.arm(FakeWindow(), app_id="x", page_getter=boom)
        handlers["map"](FakeWidget())
        body = (tmp_path / readiness.STAMP_NAME).read_text()
        assert "window=FakeWidget" in body
        assert "page=" not in body


class TestWriteStampFailure:
    def test_write_failure_is_logged_and_swallowed(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        def boom_open(*args, **kwargs):
            raise OSError("read-only file system")

        monkeypatch.setattr("builtins.open", boom_open)
        with caplog.at_level("ERROR"):
            readiness.write_stamp("org.tunaos.InstallerXfce", "InstallerWindow")
        assert "could not write readiness stamp" in caplog.text
        assert not (tmp_path / readiness.STAMP_NAME).exists()
