"""Gaps against the installer standard (wt-installer DESKTOP-STANDARD.md):
the encryption page with a TPM, how Confirm reads on the daemon path, the
disk state after a failure in the partition step, and the QR code of the
recovery key in the Flatpak."""

import json
import os
import sys
import types

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from tuna_installer_xfce import core, daemon, pages  # noqa: E402


class _Win:
    def refresh_nav(self):
        pass

    def selected_leaf(self):
        return None

    def layout_source(self):
        return None


# ─── A1: screens.yaml encryption.skip_when: a TPM 2.0 is present ─────────────

@pytest.mark.parametrize("backend, tpm, shown", [
    ("daemon", True, False),
    ("daemon", False, True),
    ("recipe", True, True),
    ("recipe", False, True),
])
def test_the_encryption_page_is_skipped_with_a_tpm_on_the_daemon_path(
        monkeypatch, backend, tpm, shown):
    monkeypatch.setattr(core, "backend", lambda: backend)
    monkeypatch.setattr(core, "has_tpm", lambda: tpm)
    page = pages.SetupPage(_Win())
    assert page.should_show() is shown
    if backend == "daemon":
        # Skipped or not, what goes to the daemon is encrypted.
        assert page.enc_type() == ("tpm2-luks" if tpm else "luks-passphrase")


# ─── A2/A4: Confirm says how the disk unlocks, and names no registry ref ─────

class _Confirm:
    def __init__(self, live):
        self.pages = {
            "destination": types.SimpleNamespace(selected_disk=lambda: {
                "path": "/dev/vda", "title": "VirtIO disk", "size_label": "64 GiB"}),
            "source": types.SimpleNamespace(live_image="ghcr.io/tuna-os/x:live",
                                            live=live)}

    def build_recipe(self):
        return {"disk": "/dev/vda", "filesystem": "btrfs", "hostname": "box",
                "image": "ghcr.io/tuna-os/x:live",
                "encryption": {"type": "tpm2-luks"}, "user": {"username": "u"}}

    def refresh_nav(self):
        pass


def _summary(monkeypatch, backend, live):
    monkeypatch.setattr(core, "backend", lambda: backend)
    monkeypatch.setattr(core, "PRODUCT_NAME", "Bonito")
    page = pages.ConfirmPage(_Confirm(live))
    page.refused_request = lambda recipe: []
    page.refused_start = lambda fn: fn()
    monkeypatch.setattr(pages.GLib, "idle_add", lambda fn, *args: fn(*args))
    page.on_enter()
    return page.summary_text()


def test_confirm_says_how_a_tpm_disk_unlocks(monkeypatch):
    text = _summary(monkeypatch, "daemon", live=True)
    label = core.BRANDING.text("encryption_tpm2_luks_label")
    description = core.BRANDING.text("encryption_tpm2_luks_description")
    assert f"Encryption: {label}: {description}" in text


def test_confirm_names_the_product_not_the_registry_on_the_medium(monkeypatch):
    text = _summary(monkeypatch, "daemon", live=True)
    assert "Image: Bonito" in text
    assert "ghcr.io" not in text


def test_the_recipe_path_keeps_its_rows(monkeypatch):
    text = _summary(monkeypatch, "recipe", live=False)
    assert "Image: ghcr.io/tuna-os/x:live" in text
    assert "Filesystem" in text


# ─── A5: the failure page says what happened to the disk ─────────────────────

def _failed_after(monkeypatch, steps):
    monkeypatch.setattr(core, "backend", lambda: "daemon")
    known = False
    for step in steps:
        known = daemon.disk_changed_after(step, known)
    line = daemon.daemon_event_to_line(
        {"event": "failed", "stepId": steps[-1], "reason": "repart_failed",
         "message": "systemd-repart exited with status 1"}, known)
    done = pages.DonePage(types.SimpleNamespace())
    done.set_result(False, daemon.line_text(line) + "\n",
                    error={"message": line["message"],
                           "disk_changed": line["disk_changed"]})
    return done.body.get_text()


MAY = "The installer may have changed the disk."


def test_a_failure_in_the_partition_step_says_the_disk_may_have_changed(monkeypatch):
    assert MAY in _failed_after(monkeypatch, ["validate_device", "partition"])


@pytest.mark.parametrize("steps, key", [
    (["validate_device"], "done_failed_disk_unchanged"),
    (["validate_device", "partition", "luks"], "done_failed_disk_changed"),
])
def test_a_known_disk_state_is_said_once(monkeypatch, steps, key):
    body = _failed_after(monkeypatch, steps)
    assert MAY not in body
    assert core.BRANDING.text(key) in body


# ─── A4: the Flatpak ships the QR code module ────────────────────────────────

def _manifest():
    path = os.path.join(HERE, "flatpak", "org.tunaos.InstallerXfce.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_the_flatpak_ships_qrcode_before_the_app():
    """qr_available() hides the QR button when `import qrcode` fails. The
    manifest had no qrcode, so the real medium never offered the QR code."""
    modules = _manifest()["modules"]
    names = [m["name"] if isinstance(m, dict) else m for m in modules]
    assert "python3-qrcode" in names
    assert names.index("python3-qrcode") < names.index("tuna-installer-xfce")
    qr = modules[names.index("python3-qrcode")]
    (source,) = qr["sources"]
    assert source["url"].endswith(".whl") and len(source["sha256"]) == 64
    assert any("--no-index" in c for c in qr["build-commands"])


def test_the_app_build_fails_without_qrcode():
    app_module = next(m for m in _manifest()["modules"]
                      if isinstance(m, dict) and m["name"] == "tuna-installer-xfce")
    assert any("import qrcode" in c for c in app_module["build-commands"])


# ─── A4: a passphrase install can save its recovery key ──────────────────────

def test_the_key_of_a_passphrase_install_is_enrolled_with_the_passphrase(monkeypatch):
    """With no TPM the disk is locked by the person's passphrase. Enrol with
    the empty password got PasswordIncorrect (mock no-tpm), and the recovery
    page never let the person go on."""
    calls = []
    monkeypatch.setattr(core, "backend", lambda: "daemon")
    monkeypatch.setattr(core, "has_tpm", lambda: False)
    monkeypatch.setattr(core, "get_daemon", lambda: types.SimpleNamespace(
        make_recovery_key=lambda: "k" * 8,
        enroll_recovery_key=lambda *a: calls.append(a) or {"slot": 1}))
    win = _Win()
    setup = pages.SetupPage(win)
    setup.pass1.set_text("correct horse")
    setup.pass2.set_text("correct horse")
    win.pages = {"setup": setup, "destination": types.SimpleNamespace(
        selected_disk=lambda: {"path": "/dev/vda"})}
    page = pages.RecoveryPage(win)
    page.on_enter()
    page.ack.set_active(True)
    assert page.on_leave() is True
    assert calls == [("/dev/vda", "k" * 8, "correct horse")]


def test_the_key_of_a_tpm_install_is_enrolled_with_the_empty_password(monkeypatch):
    calls = []
    monkeypatch.setattr(core, "backend", lambda: "daemon")
    monkeypatch.setattr(core, "has_tpm", lambda: True)
    monkeypatch.setattr(core, "get_daemon", lambda: types.SimpleNamespace(
        make_recovery_key=lambda: "k" * 8,
        enroll_recovery_key=lambda *a: calls.append(a) or {"slot": 1}))
    win = _Win()
    win.pages = {"setup": pages.SetupPage(win), "destination": types.SimpleNamespace(
        selected_disk=lambda: {"path": "/dev/vda"})}
    page = pages.RecoveryPage(win)
    page.on_enter()
    assert page.on_leave() is True
    assert calls == [("/dev/vda", "k" * 8, "")]


# ─── eula: the agreement, not the XML file ───────────────────────────────────

AGREEMENT = """<?xml version="1.0" encoding="UTF-8"?>
<component type="operating-system">
  <id>org.example.os</id>
  <name>Example</name>
  <summary>An example</summary>
  <metadata_license>CC0-1.0</metadata_license>
  <agreement type="eula" version_id="1">
    <agreement_section type="generic">
      <name>Use of this system</name>
      <description>
        <p>Keep backups.</p>
        <ol><li>First</li><li>Second</li></ol>
        <ul><li>One item</li></ul>
      </description>
    </agreement_section>
  </agreement>
</component>
"""


def test_the_terms_page_shows_the_agreement_not_the_xml(tmp_path, monkeypatch):
    path = tmp_path / "eula.xml"
    path.write_text(AGREEMENT, encoding="utf-8")
    monkeypatch.setattr(core, "find_eula", lambda: str(path))
    page = pages.EulaPage(_Win())
    text = page.plain_text()
    assert page.loaded
    assert "<" not in text and "org.example.os" not in text and "CC0" not in text
    assert text.splitlines() == ["Use of this system", "Keep backups.",
                                 "1. First", "2. Second", "• One item"]


def test_the_kde_fixture_without_description_reads_too():
    path = os.path.join(HERE, "..", "kde", "tests", "testdata", "eula-agreement.xml")
    with open(path, encoding="utf-8") as handle:
        blocks = core.eula_blocks(handle.read())
    assert ("heading", "Updates") in blocks
    assert ("item", "File bugs when it breaks.") in blocks


@pytest.mark.parametrize("text", [
    "not xml",
    "<component><name>No agreement</name></component>",
    '<!DOCTYPE x [<!ENTITY a "b">]><component><agreement/></component>',
])
def test_a_file_that_is_no_agreement_is_unreadable(tmp_path, monkeypatch, text):
    path = tmp_path / "eula.xml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(core, "find_eula", lambda: str(path))
    page = pages.EulaPage(_Win())
    assert not page.loaded
    assert "<" not in page.plain_text()
    assert not page.accept.get_visible()


def test_show_all_keeps_the_one_way_out(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "find_eula", lambda: str(tmp_path / "gone.xml"))
    (tmp_path / "gone.xml").write_text("not xml", encoding="utf-8")
    page = pages.EulaPage(_Win())
    page.show_all()
    assert not page.accept.get_visible() and page.off_btn.get_visible()


def test_no_bare_warning_icon_before_a_disk_is_picked(monkeypatch):
    monkeypatch.setattr(core, "backend", lambda: "daemon")
    monkeypatch.setattr(core, "daemon_disk_view", lambda: ([], None))
    page = pages.DestinationPage(_Win())
    window = Gtk.Window()
    window.add(page)
    window.show_all()
    assert not page.warn.get_visible()
    page.on_enter()
    assert not page.warn.get_visible()
    labels = [c.get_label() for box in page.listbox.get_children()
              for c in box.get_children() if isinstance(c, (Gtk.Label, Gtk.Button))]
    assert "Rescan" in labels and "Power off" in labels
    window.destroy()


def test_a_varlink_error_reply_gives_the_empty_state(monkeypatch):
    """Mock no-disks: ListCandidateDevices answers the error reply
    NoCandidateDevices, which is no DaemonError. It escaped on_enter: no
    text, no Rescan, the step line of the page before, Next on."""
    class Reply(Exception):
        def __init__(self, error):
            super().__init__(error)
            self.error = error

    def candidates():
        raise Reply("io.systemd.SysInstall.NoCandidateDevices")
        yield  # pragma: no cover

    monkeypatch.setattr(core, "backend", lambda: "daemon")
    monkeypatch.setattr(core, "get_daemon", lambda: types.SimpleNamespace(
        probe=lambda: {"disks": []}, list_candidates=candidates))
    assert core.daemon_disk_view() == ([], None)

    def broken():
        raise Reply("io.systemd.System")
    monkeypatch.setattr(core, "get_daemon", lambda: types.SimpleNamespace(
        probe=broken, list_candidates=candidates))
    rows, error = core.daemon_disk_view()
    assert rows == [] and "io.systemd.System" in error


def test_a_page_that_raises_still_shows_a_way_out(monkeypatch):
    monkeypatch.setattr(core, "backend", lambda: "daemon")

    def boom():
        raise RuntimeError("probe went away")
    monkeypatch.setattr(core, "daemon_disk_view", boom)
    page = pages.DestinationPage(_Win())
    page.on_enter()
    texts = [c.get_label() for box in page.listbox.get_children()
             for c in box.get_children() if isinstance(c, (Gtk.Label, Gtk.Button))]
    assert any("probe went away" in t for t in texts)
    assert "Rescan" in texts and not page.can_continue()
