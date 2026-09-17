# test_core.py - Unit tests for tuna_installer_xfce.core (backend plumbing)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# core.py is the shared backend (catalog, disks, offline stores, recipe
# emission, fisherman invocation) and is pure stdlib — no GTK import — so
# these tests run headlessly in plain pytest.

import json
import os
import subprocess

import pytest

from tuna_installer_xfce import core


# ─── dry_run interlock ───────────────────────────────────────────────────────

class TestDryRun:
    def test_unset_is_false(self, monkeypatch):
        monkeypatch.delenv("TUNA_INSTALLER_DRY_RUN", raising=False)
        assert core.dry_run() is False

    def test_empty_is_false(self, monkeypatch):
        monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "")
        assert core.dry_run() is False

    def test_zero_is_false(self, monkeypatch):
        monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "0")
        assert core.dry_run() is False

    def test_nonzero_is_true(self, monkeypatch):
        monkeypatch.setenv("TUNA_INSTALLER_DRY_RUN", "1")
        assert core.dry_run() is True


# ─── product name resolution ─────────────────────────────────────────────────

class TestReadPrettyName:
    def test_quoted_value(self, tmp_path):
        f = tmp_path / "os-release"
        f.write_text('ID=fedora\nPRETTY_NAME="TunaOS Skipjack"\n')
        assert core._read_pretty_name(str(f)) == "TunaOS Skipjack"

    def test_unquoted_value(self, tmp_path):
        f = tmp_path / "os-release"
        f.write_text("PRETTY_NAME=Bonito\n")
        assert core._read_pretty_name(str(f)) == "Bonito"

    def test_missing_file_returns_empty(self, tmp_path):
        assert core._read_pretty_name(str(tmp_path / "nope")) == ""

    def test_ignores_other_keys(self, tmp_path):
        f = tmp_path / "os-release"
        f.write_text("NAME=Something\nPRETTY_NAME=\nID=tunaos\n")
        assert core._read_pretty_name(str(f)) == ""

    def test_no_pretty_name_line_at_all(self, tmp_path):
        f = tmp_path / "os-release"
        f.write_text("NAME=Something\nID=tunaos\n")
        assert core._read_pretty_name(str(f)) == ""


class TestResolveProductName:
    def test_first_path_wins(self, tmp_path, monkeypatch):
        first = tmp_path / "a"
        second = tmp_path / "b"
        first.write_text('PRETTY_NAME="Alpha"\n')
        second.write_text('PRETTY_NAME="Beta"\n')
        monkeypatch.setattr(core, "OS_RELEASE_PATHS", [str(first), str(second)])
        assert core.resolve_product_name() == "Alpha"

    def test_falls_back_when_none_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(core, "OS_RELEASE_PATHS", [str(tmp_path / "missing")])
        assert core.resolve_product_name() == core.PRODUCT_NAME_FALLBACK


# ─── offline stores ──────────────────────────────────────────────────────────

class TestOfflineStores:
    def test_env_and_default_dedup_and_dir_filter(self, tmp_path, monkeypatch):
        a = tmp_path / "store-a"
        b = tmp_path / "store-b"
        a.mkdir()
        b.mkdir()
        not_a_dir = tmp_path / "plain-file"
        not_a_dir.write_text("x")
        monkeypatch.setenv("TUNA_OFFLINE_STORES", f"{a}:{b}:{not_a_dir}:{a}")
        monkeypatch.setattr(core, "OFFLINE_STORES_FILE", str(tmp_path / "absent"))
        monkeypatch.setattr(core, "OFFLINE_STORE_DEFAULT", str(tmp_path / "default-missing"))
        stores = core.offline_stores()
        assert stores == [str(a), str(b)]

    def test_config_file_entries(self, tmp_path, monkeypatch):
        a = tmp_path / "from-file"
        a.mkdir()
        cfg = tmp_path / "offline-stores"
        cfg.write_text(f"# comment\n\n{a}\n\n")
        monkeypatch.delenv("TUNA_OFFLINE_STORES", raising=False)
        monkeypatch.setattr(core, "OFFLINE_STORES_FILE", str(cfg))
        monkeypatch.setattr(core, "OFFLINE_STORE_DEFAULT", str(tmp_path / "default-missing"))
        assert core.offline_stores() == [str(a)]


# ─── host commands / catalog ─────────────────────────────────────────────────

class TestOfflineImages:
    def test_parses_names_and_skips_failures(self, monkeypatch):
        fake = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps([{"Names": ["localhost/one:latest", "localhost/two:1.0"]},
                               {"Names": None}]),
            stderr="")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        assert core.offline_images(["store-a", "store-b"]) == {"localhost/one:latest", "localhost/two:1.0"}

    def test_nonzero_returncode_yields_empty(self, monkeypatch):
        fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="boom", stderr="")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        assert core.offline_images(["store"]) == set()

    def test_invalid_json_yields_empty(self, monkeypatch):
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr="")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        assert core.offline_images(["store"]) == set()


class TestImageNode:
    def test_parent_child_field_inheritance(self):
        raw_parent = {
            "name": "Desktop",
            "registry": "ghcr.io/tuna-os",
            "bootloader": "systemd-boot",
            "filesystem": "btrfs",
            "children": [
                {
                    "name": "XFCE",
                    "tag": "xfce",
                }
            ],
        }
        parent = core.ImageNode(raw_parent)
        assert len(parent.children) == 1
        child = parent.children[0]

        assert child.name == "XFCE"
        assert child.registry == "ghcr.io/tuna-os"
        assert child.imgref == "ghcr.io/tuna-os:xfce"
        assert child.bootloader == "systemd-boot"
        assert child.filesystem == "btrfs"
        assert child.is_leaf() is True

        leaves = list(parent.leaves())
        assert len(leaves) == 1
        assert leaves[0].name == "XFCE"


class TestLoadCatalog:
    def test_loads_images_json_file(self, tmp_path, monkeypatch):
        cfg = tmp_path / "images.json"
        cfg.write_text(json.dumps({
            "default_image": "ghcr.io/tuna-os/xfce:latest",
            "fallback_flatpaks": ["org.gnome.Loupe"],
            "images": [{"name": "XFCE", "imgref": "ghcr.io/tuna-os/xfce:latest"}]
        }))
        monkeypatch.setattr(core, "IMAGES_JSON_PATHS", [str(cfg)])
        default_img, fallbacks, nodes = core.load_catalog()
        assert default_img == "ghcr.io/tuna-os/xfce:latest"
        assert fallbacks == ["org.gnome.Loupe"]
        assert len(nodes) == 1
        assert nodes[0].name == "XFCE"


class TestCandidateDisks:
    def test_filters_non_disks_and_live_media(self, monkeypatch):
        payload = {
            "blockdevices": [
                {"type": "disk", "path": "/dev/vda", "name": "vda", "size": 10**12, "model": "", "rm": "0", "mountpoints": ["/run/initramfs/live"], "tran": "virtio"},
                {"type": "disk", "path": "/dev/vdb", "name": "vdb", "size": 10**12, "model": "Virtio", "rm": "0", "mountpoints": [], "tran": "virtio"},
                {"type": "part", "path": "/dev/vda1", "name": "vda1", "size": 10**11, "model": "", "rm": "0", "mountpoints": [], "tran": "virtio"},
            ]
        }
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        disks = core.candidate_disks()
        assert [d["path"] for d in disks] == ["/dev/vdb"]
        assert disks[0]["model"] == "Virtio"
        assert disks[0]["transport"] == "virtio"

    def test_filters_run_media_iso_live_media(self, monkeypatch):
        payload = {
            "blockdevices": [
                {"type": "disk", "path": "/dev/sda", "size": 10**11, "mountpoints": ["/run/media/iso"]},
                {"type": "disk", "path": "/dev/sdb", "size": 5*10**11, "mountpoints": []},
            ]
        }
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr="")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        disks = core.candidate_disks()
        assert [d["path"] for d in disks] == ["/dev/sdb"]

    def test_failure_yields_empty(self, monkeypatch):
        fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="lsblk missing")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        assert core.candidate_disks() == []


# ─── human_size formatting ───────────────────────────────────────────────────

class TestHumanSize:
    @pytest.mark.parametrize(
        "nbytes,expected",
        [
            (0, "0 B"),
            (999, "999 B"),
            (1000, "1 KB"),
            (1500, "1.5 KB"),
            (1_000_000, "1 MB"),
            (2_500_000_000, "2.5 GB"),
            (10**12, "1 TB"),
        ],
    )
    def test_formatting(self, nbytes, expected):
        assert core.human_size(nbytes) == expected


# ─── recipe building ─────────────────────────────────────────────────────────
#
# These cover the conditionals that used to sit inside
# InstallerWindow.build_recipe, where reaching them meant constructing a GTK
# window. The recipe is the contract with fisherman, so the interesting cases
# are the ones where a key must be ABSENT — an empty value and a missing key
# do not mean the same thing to the backend.

MINIMAL = dict(disk="/dev/vda", filesystem="xfs")


class TestBuildRecipe:
    def test_minimal_recipe_has_the_fixed_fields(self):
        r = core.build_recipe(**MINIMAL, hostname="tunaos")
        assert r["disk"] == "/dev/vda"
        assert r["filesystem"] == "xfs"
        assert r["hostname"] == "tunaos"
        assert r["distroID"] == "tunaos"
        assert r["selinuxDisabled"] is True
        assert r["encryption"] == {"type": "none"}

    def test_optional_keys_are_absent_not_empty(self):
        r = core.build_recipe(**MINIMAL)
        for key in ("bootloader", "composeFsBackend", "flatpaks",
                    "additionalImageStores", "user"):
            assert key not in r, f"{key} must be omitted, not emitted empty"

    # --- btrfs subvolumes ---

    def test_subvolumes_honoured_on_btrfs(self):
        r = core.build_recipe(disk="/dev/vda", filesystem="btrfs",
                              btrfs_subvolumes=True)
        assert r["btrfsSubvolumes"] is True

    def test_subvolumes_ignored_off_btrfs(self):
        """The Advanced checkbox keeps its state when the filesystem changes."""
        r = core.build_recipe(disk="/dev/vda", filesystem="xfs",
                              btrfs_subvolumes=True)
        assert r["btrfsSubvolumes"] is False

    # --- encryption ---

    def test_passphrase_emitted_for_a_passphrase_type(self):
        r = core.build_recipe(**MINIMAL, encryption_type="luks-passphrase",
                              passphrase="hunter2")
        assert r["encryption"] == {"type": "luks-passphrase",
                                   "passphrase": "hunter2"}

    def test_passphrase_never_leaks_into_an_unencrypted_recipe(self):
        """A stale entry in the box must not reach the backend."""
        r = core.build_recipe(**MINIMAL, encryption_type="none",
                              passphrase="left-over")
        assert "passphrase" not in r["encryption"]

    def test_tpm_only_takes_no_passphrase(self):
        """`tpm2-luks` unlocks from the TPM alone — see ENCRYPTION_CHOICES."""
        r = core.build_recipe(**MINIMAL, encryption_type="tpm2-luks",
                              passphrase="left-over")
        assert r["encryption"] == {"type": "tpm2-luks"}

    def test_tpm_plus_passphrase_carries_the_fallback(self):
        """`tpm2-luks-passphrase` is TPM unlock with a passphrase fallback, so
        the passphrase must survive. This is why the check is a substring test
        and not equality against 'luks-passphrase'."""
        r = core.build_recipe(**MINIMAL, encryption_type="tpm2-luks-passphrase",
                              passphrase="fallback")
        assert r["encryption"] == {"type": "tpm2-luks-passphrase",
                                   "passphrase": "fallback"}

    # --- catalog leaf properties ---

    def test_bootloader_and_composefs_passed_through(self):
        r = core.build_recipe(**MINIMAL, bootloader="systemd-boot",
                              composefs=True)
        assert r["bootloader"] == "systemd-boot"
        assert r["composeFsBackend"] is True

    def test_flatpaks_split_into_a_list(self):
        r = core.build_recipe(**MINIMAL, flatpaks="org.gnome.Loupe org.gnome.Calculator")
        assert r["flatpaks"] == ["org.gnome.Loupe", "org.gnome.Calculator"]

    def test_catalog_reference_is_not_a_package_list(self):
        """A leading @ names another catalog entry — passing it verbatim would
        ask fisherman to install a flatpak called '@desktop'."""
        r = core.build_recipe(**MINIMAL, flatpaks="@desktop")
        assert "flatpaks" not in r

    # --- offline stores ---

    def test_stores_passed_when_detected(self):
        r = core.build_recipe(**MINIMAL, stores=["/run/media/iso/containers"])
        assert r["additionalImageStores"] == ["/run/media/iso/containers"]

    # --- user block ---

    def test_user_block_built_when_the_image_needs_one(self):
        r = core.build_recipe(**MINIMAL, needs_user=True, username="jo",
                              fullname="Jo Fish", password="pw")
        assert r["user"] == {"username": "jo", "fullname": "Jo Fish",
                             "password": "pw", "groups": ["wheel"]}

    def test_no_user_block_when_the_image_creates_its_own(self):
        """The image runs its own first-boot setup; a second user would be
        created behind the user's back."""
        r = core.build_recipe(**MINIMAL, needs_user=False, username="jo",
                              password="pw")
        assert "user" not in r

    def test_no_user_block_without_a_username(self):
        r = core.build_recipe(**MINIMAL, needs_user=True, username="",
                              password="pw")
        assert "user" not in r

    # --- round trip ---

    def test_recipe_survives_write_recipe(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        built = core.build_recipe(**MINIMAL, encryption_type="luks-passphrase",
                                  passphrase="pw", stores=["/a"],
                                  needs_user=True, username="jo")
        assert json.load(open(core.write_recipe(built))) == built


# ─── recipe writing ──────────────────────────────────────────────────────────

class TestWriteRecipe:
    def test_writes_0600_json_under_runtime_dir(self, tmp_path, monkeypatch):
        import stat
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        path = core.write_recipe({"image": "localhost/foo:1"})
        assert path.startswith(str(tmp_path / "tuna-installer-"))
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600, f"recipe must be 0600, got {oct(mode)}"
        assert json.load(open(path)) == {"image": "localhost/foo:1"}

    def test_falls_back_to_tmp_without_runtime_dir(self, monkeypatch):
        import stat
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        path = core.write_recipe({"x": 1})
        assert json.load(open(path)) == {"x": 1}
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    def test_directory_is_private(self, tmp_path, monkeypatch):
        """0700, so nobody else can enumerate or replace the recipe.

        The file mode was never the weak part — mkstemp already gave an
        unpredictable 0600 file. The directory was: a fixed
        <base>/tuna-installer created with exist_ok=True inherited whatever
        mode a pre-existing directory had, and the path is what gets handed
        to root's fisherman."""
        import stat
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        rundir = core.recipe_dir(core.write_recipe({"x": 1}))
        assert stat.S_IMODE(os.stat(rundir).st_mode) == 0o700

    def test_directory_is_not_reused(self, tmp_path, monkeypatch):
        """A fresh directory per call — never a fixed name a local user can
        pre-create and then own."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        first = core.recipe_dir(core.write_recipe({"x": 1}))
        second = core.recipe_dir(core.write_recipe({"x": 2}))
        assert first != second
        assert not os.path.exists(tmp_path / "tuna-installer")

    def test_precreated_world_writable_dir_is_not_adopted(self, tmp_path, monkeypatch):
        """The old code accepted a pre-existing 0777 <base>/tuna-installer."""
        import stat
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        hostile = tmp_path / "tuna-installer"
        hostile.mkdir(mode=0o777)
        os.chmod(hostile, 0o777)  # defeat the umask
        rundir = core.recipe_dir(core.write_recipe({"x": 1}))
        assert rundir != str(hostile)
        assert stat.S_IMODE(os.stat(rundir).st_mode) == 0o700


# ─── fisherman invocation ────────────────────────────────────────────────────

class TestFisherman:
    def test_argv_uses_sudo_outside_flatpak(self):
        assert core.fisherman_argv("/run/user/1000/recipe.json") == [
            "sudo", "/usr/local/bin/fisherman", "/run/user/1000/recipe.json"]

    def test_shell_quotes_arguments(self):
        cmd = core.fisherman_shell("/run/user/1000/recipe.json")
        assert cmd == "sudo /usr/local/bin/fisherman /run/user/1000/recipe.json"

    def test_shell_quotes_spaces(self):
        cmd = core.fisherman_shell("/path with spaces/recipe.json")
        assert "'/path with spaces/recipe.json'" in cmd


# ─── install log ─────────────────────────────────────────────────────────────

class TestInstallLog:
    def test_path_under_xdg_state_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        assert core.install_log_path() == str(tmp_path / "tuna-installer" / "install.log")

    def test_falls_back_to_local_state_without_xdg_state_home(self, monkeypatch):
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        path = core.install_log_path()
        assert path == os.path.join(
            os.path.expanduser("~"), ".local", "state", "tuna-installer", "install.log")

    def test_creates_private_directory(self, tmp_path, monkeypatch):
        import stat
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        core.install_log_path()
        mode = stat.S_IMODE(os.stat(tmp_path / "tuna-installer").st_mode)
        assert mode == 0o700

    def test_open_install_log_creates_0600_file(self, tmp_path, monkeypatch):
        import stat
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        f = core.open_install_log()
        try:
            f.write("hello\n")
            f.flush()
            path = core.install_log_path()
            mode = stat.S_IMODE(os.stat(path).st_mode)
            assert mode == 0o600, f"install log must be 0600, got {oct(mode)}"
        finally:
            f.close()

    def test_open_install_log_appends_across_calls(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        f1 = core.open_install_log()
        f1.write("first\n")
        f1.close()
        f2 = core.open_install_log()
        f2.write("second\n")
        f2.close()
        assert open(core.install_log_path()).read() == "first\nsecond\n"


class TestHostRun:
    def test_host_run_flatpak(self, monkeypatch):
        monkeypatch.setattr(core, "IN_FLATPAK", True)
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        core.host_run(["echo", "hi"])
        assert calls == [["flatpak-spawn", "--host", "echo", "hi"]]


class TestReadPrettyNameValueError:
    def test_shlex_split_value_error(self, tmp_path):
        f = tmp_path / "os-release"
        f.write_text('PRETTY_NAME="Unmatched quote\n')
        assert core._read_pretty_name(str(f)) == "Unmatched quote"


class TestLoadCatalogFallback:
    def test_missing_file_returns_defaults(self, monkeypatch):
        monkeypatch.setattr(core, "IMAGES_JSON_PATHS", ["/path/that/does/not/exist.json"])
        default_img, fallbacks, nodes = core.load_catalog()
        assert default_img == ""
        assert fallbacks == []
        assert nodes == []


class TestLiveIsoImage:
    def test_live_iso_image_success(self, monkeypatch, tmp_path):
        status_json = json.dumps({
            "status": {
                "booted": {
                    "image": {
                        "image": {
                            "image": "ghcr.io/tuna-os/xfce:latest"
                        }
                    }
                }
            }
        })
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=status_json, stderr="")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        cmdline = tmp_path / "cmdline"
        cmdline.write_text("BOOT_IMAGE=/vmlinuz rd.live.image quiet")

        real_open = open

        def mocked_open(path, *args, **kwargs):
            if path == "/proc/cmdline":
                return real_open(cmdline, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", mocked_open)
        assert core.live_iso_image() == "ghcr.io/tuna-os/xfce:latest"

    def test_live_iso_image_bootc_error(self, monkeypatch):
        fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        assert core.live_iso_image() is None

    def test_live_iso_image_invalid_json(self, monkeypatch):
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json", stderr="")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        assert core.live_iso_image() is None

    def test_live_iso_image_empty_ref(self, monkeypatch):
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}", stderr="")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        assert core.live_iso_image() is None

    def test_live_iso_image_not_live(self, monkeypatch, tmp_path):
        status_json = json.dumps({
            "status": {
                "booted": {
                    "image": {
                        "image": {
                            "image": "ghcr.io/tuna-os/xfce:latest"
                        }
                    }
                }
            }
        })
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=status_json, stderr="")
        monkeypatch.setattr(core, "host_run", lambda argv, **kw: fake)
        cmdline = tmp_path / "cmdline"
        cmdline.write_text("BOOT_IMAGE=/vmlinuz quiet")

        real_open = open

        def mocked_open(path, *args, **kwargs):
            if path == "/proc/cmdline":
                return real_open(cmdline, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", mocked_open)
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        assert core.live_iso_image() is None

