"""bootc_shared.readiness — the readiness stamp, one implementation for both GTK frontends.

GNOME and XFCE used to carry near-copies that differed only in how the page
name reached the stamp, and then byte-identical copies of one file. Both now
import shared/python/bootc_shared/readiness.py.
"""

import importlib.util
import os
import tempfile
import unittest
from unittest import mock

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CANONICAL = os.path.join(REPO, "shared", "python", "bootc_shared", "readiness.py")


def _load():
    spec = importlib.util.spec_from_file_location("bootc_shared.readiness_under_test", CANONICAL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Widget:
    pass


class _Window:
    def __init__(self):
        self.handlers = {}

    def connect(self, signal, handler):
        self.handlers[signal] = handler


class PageInjectionTest(unittest.TestCase):
    """Both ways a frontend names the page reach the stamp."""

    def setUp(self):
        self.mod = _load()
        self.tmp = tempfile.mkdtemp()
        patcher = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _stamp(self, **kwargs):
        window = _Window()
        self.mod.arm(window, "app.id", **kwargs)
        window.handlers["map"](_Widget())
        with open(os.path.join(self.tmp, self.mod.STAMP_NAME)) as fh:
            return fh.read()

    def test_fixed_page(self):
        self.assertIn("page=ram-check", self._stamp(page="ram-check"))

    def test_getter_is_called_at_map_time(self):
        state = {"page": "before"}
        window = _Window()
        self.mod.arm(window, "app.id", page_getter=lambda: state["page"])
        state["page"] = "welcome"
        window.handlers["map"](_Widget())
        with open(os.path.join(self.tmp, self.mod.STAMP_NAME)) as fh:
            self.assertIn("page=welcome", fh.read())

    def test_failing_getter_stamps_without_page(self):
        def boom():
            raise RuntimeError("not ready")
        with self.assertLogs(self.mod.logger, level="ERROR"):
            body = self._stamp(page="ignored", page_getter=boom)
        self.assertIn("window=_Widget", body)
        self.assertNotIn("page=", body)

    def test_no_page(self):
        self.assertNotIn("page=", self._stamp())


if __name__ == "__main__":
    unittest.main()
