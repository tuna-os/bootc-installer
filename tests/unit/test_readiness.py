"""Unit tests for bootc_installer/readiness.py.

Covers stamp_path()'s no-XDG_RUNTIME_DIR fallback, write_stamp()'s happy
path/OSError-swallow branches, and arm()'s map-signal wiring — none of which
had any unit coverage even though the module is pure logic with no GTK
dependency at import time.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bootc_installer import readiness


def test_stamp_path_returns_none_without_runtime_dir(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert readiness.stamp_path() is None


def test_stamp_path_joins_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert readiness.stamp_path() == os.path.join(str(tmp_path), readiness.STAMP_NAME)


def test_write_stamp_without_runtime_dir_logs_warning_and_skips(monkeypatch, caplog):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with caplog.at_level("WARNING"):
        readiness.write_stamp("org.tunaos.Installer", "BootcWindow")
    assert "no XDG_RUNTIME_DIR" in caplog.text


def test_write_stamp_writes_atomic_file_with_expected_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    readiness.write_stamp("org.tunaos.Installer", "BootcWindow", page="welcome")

    stamp = tmp_path / readiness.STAMP_NAME
    assert stamp.exists()
    body = stamp.read_text()
    assert "app_id=org.tunaos.Installer" in body
    assert "window=BootcWindow" in body
    assert f"signal={readiness.SIGNAL}" in body
    assert "mapped_at=" in body
    assert "page=welcome" in body

    # no leftover temp file from the rename
    assert not list(tmp_path.glob(f"{readiness.STAMP_NAME}.tmp*"))


def test_write_stamp_omits_page_when_not_given(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    readiness.write_stamp("org.tunaos.Installer", "BootcWindow")

    body = (tmp_path / readiness.STAMP_NAME).read_text()
    assert "page=" not in body


def test_write_stamp_swallows_oserror(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    def _raise(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _raise)
    with caplog.at_level("ERROR"):
        readiness.write_stamp("org.tunaos.Installer", "BootcWindow")
    assert "could not write readiness stamp" in caplog.text


def test_arm_writes_stamp_on_map_signal(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    calls = []
    monkeypatch.setattr(
        readiness, "write_stamp", lambda *a, **kw: calls.append((a, kw))
    )

    class _FakeWindow:
        def __init__(self):
            self._handlers = {}

        def connect(self, signal, callback):
            self._handlers[signal] = callback

    win = _FakeWindow()
    readiness.arm(win, "org.tunaos.Installer", page="disk")

    assert "map" in win._handlers
    win._handlers["map"](win)

    assert calls == [(("org.tunaos.Installer", "_FakeWindow"), {"page": "disk"})]
