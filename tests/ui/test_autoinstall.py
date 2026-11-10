"""--autoinstall: where the recipe is read from, and the checks before the
start (#317). The window class is the real one; fisherman is never run."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from bootc_shared import validate as fisherman_validate
from bootc_installer.windows.main_window import BootcWindow

_VALID = {"disk": "/dev/vda", "image": "registry.example/os:1"}


class TestAutoinstallPath:
    def test_a_host_etc_path_is_read_under_run_host_in_a_flatpak(self):
        assert BootcWindow._autoinstall_paths(
            "/etc/bootc-installer/autoinstall.json", in_flatpak=True
        ) == ["/run/host/etc/bootc-installer/autoinstall.json",
              "/etc/bootc-installer/autoinstall.json"]

    def test_other_paths_and_native_runs_are_read_as_given(self):
        assert BootcWindow._autoinstall_paths("/etc/x.json", in_flatpak=False) == ["/etc/x.json"]
        assert BootcWindow._autoinstall_paths("/home/u/r.json", in_flatpak=True) == ["/home/u/r.json"]
        assert BootcWindow._autoinstall_paths("r.json", in_flatpak=True) == ["r.json"]
        # /etcetera is not /etc.
        assert BootcWindow._autoinstall_paths("/etcetera/r.json", in_flatpak=True) == ["/etcetera/r.json"]

    def test_the_host_file_wins_in_a_flatpak(self, tmp_path):
        host = tmp_path / "host.json"
        host.write_text(json.dumps(_VALID))
        with patch.object(BootcWindow, "_autoinstall_paths",
                          return_value=[str(host), "/etc/absent.json"]):
            recipe, reason = BootcWindow._read_autoinstall_recipe("/etc/absent.json", True)
        assert recipe == _VALID and reason == ""

    def test_the_given_path_is_the_fallback(self, tmp_path):
        given = tmp_path / "given.json"
        given.write_text(json.dumps(_VALID))
        with patch.object(BootcWindow, "_autoinstall_paths",
                          return_value=[str(tmp_path / "absent.json"), str(given)]):
            recipe, reason = BootcWindow._read_autoinstall_recipe(str(given), True)
        assert recipe == _VALID and reason == ""


class TestAutoinstallReasons:
    def test_a_missing_file_says_so(self, tmp_path):
        path = str(tmp_path / "absent.json")
        recipe, reason = BootcWindow._read_autoinstall_recipe(path, False)
        assert recipe is None
        assert path in reason and "cannot be read" in reason

    def test_bad_json_says_so(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        recipe, reason = BootcWindow._read_autoinstall_recipe(str(path), False)
        assert recipe is None and "not valid JSON" in reason

    def test_a_json_list_says_so(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[]")
        recipe, reason = BootcWindow._read_autoinstall_recipe(str(path), False)
        assert recipe is None and "JSON object" in reason

    def test_the_old_loader_still_returns_the_recipe_or_none(self, tmp_path):
        path = tmp_path / "ok.json"
        path.write_text(json.dumps(_VALID))
        assert BootcWindow._load_autoinstall_recipe(str(path)) == _VALID
        assert BootcWindow._load_autoinstall_recipe(str(tmp_path / "absent")) is None


class TestAutoinstallValidation:
    _window = SimpleNamespace(recipe={"branding": {"copy": {
        "validate_hostname_invalid_char": "Use letters, digits and hyphens."}}})

    def _validate(self, recipe, result=None, error=None):
        def run(command, sent, timeout=None):
            assert command[-3:] == ["validate", "--json", "-"], "a full check, not --partial"
            assert sent == recipe
            if error:
                raise error
            return result
        with patch.object(fisherman_validate, "run", side_effect=run), \
             patch("bootc_installer.utils.fisherman_runner.IN_FLATPAK", False):
            return BootcWindow._validate_autoinstall_recipe(self._window, recipe)

    def test_a_recipe_with_no_disk_is_refused_before_fisherman_is_asked(self):
        with patch.object(fisherman_validate, "run") as run:
            reason = BootcWindow._validate_autoinstall_recipe(self._window, {"image": "x"})
        assert "no installation disk" in reason
        run.assert_not_called()

    def test_a_valid_recipe_has_no_reason(self):
        assert self._validate(_VALID, {"protocol_version": 1, "valid": True, "errors": []}) == ""

    def test_the_reason_is_the_copy_for_fishermans_code(self):
        result = {"protocol_version": 1, "valid": False, "errors": [
            {"field": "hostname", "code": "hostname_invalid_char", "message": "bad hostname"}]}
        assert self._validate(_VALID, result) == "Use letters, digits and hyphens."

    def test_a_code_with_no_copy_shows_fishermans_message(self):
        result = {"protocol_version": 1, "valid": False, "errors": [
            {"field": "image", "code": "brand_new_code", "message": "image is not a reference"}]}
        assert self._validate(_VALID, result) == "image is not a reference"

    def test_when_fisherman_cannot_be_asked_the_install_decides(self):
        """The install runs the same rules before it touches a disk."""
        assert self._validate(_VALID, error=fisherman_validate.ValidateError("not found")) == ""
