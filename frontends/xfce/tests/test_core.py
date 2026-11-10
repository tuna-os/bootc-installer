# test_core.py - Unit tests for tuna_installer_xfce.core (backend plumbing)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# core.py is the shared backend (catalog, disks, live and offline facts,
# recipe emission, fisherman invocation) and is pure stdlib — no GTK import — so
# these tests run headlessly in plain pytest.

import json
import os
import subprocess

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
# The resolver itself is tested against the shared fixtures in
# tests/test_branding.py; here only core's use of it.

class TestBranding:
    def test_product_name_is_the_branding_name(self):
        assert core.PRODUCT_NAME == core.BRANDING.name

    def test_resolve_branding_reads_env_file(self, tmp_path, monkeypatch):
        f = tmp_path / "branding.json"
        f.write_text('{"name": "Alpha", "id": "alpha"}')
        monkeypatch.setenv("BOOTC_INSTALLER_BRANDING", str(f))
        b = core.resolve_branding()
        assert (b.name, b.id) == ("Alpha", "alpha")

    def test_nothing_readable_is_neutral(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOOTC_INSTALLER_BRANDING", str(tmp_path / "missing"))
        monkeypatch.setattr(core.branding, "OS_RELEASE_PATHS", [str(tmp_path / "missing")])
        b = core.resolve_branding()
        assert b.name == "Linux"
        assert "tuna" not in b.name.lower() and "bluefin" not in b.name.lower()


# ─── live media and offline images: fisherman's facts ────────────────────────

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "probe", "fixtures")


def _probe_from(monkeypatch, name):
    monkeypatch.setenv("BOOTC_INSTALLER_FAKE_PROBE", os.path.join(FIXTURES, name + ".json"))
    core.probe(refresh=True)


class TestLiveAndOffline:
    """probe's `live` and `offline` sections, read through the shared reader
    (shared/probe/README.md). No bootc status, /proc/cmdline, store list or
    podman here: inside a Flatpak they saw the runtime, not the host."""

    def teardown_method(self):
        core._probe_cache.clear()

    def test_live_laptop(self, monkeypatch):
        _probe_from(monkeypatch, "laptop")
        expected = json.load(open(os.path.join(FIXTURES, "laptop.expected.json")))
        assert core.is_live()
        assert core.live_image() == expected["live_image"]
        assert core.offline_images() == set(expected["offline_images"])

    def test_pure_live_oci_installs_the_running_image(self, monkeypatch):
        _probe_from(monkeypatch, "pure-live-oci")
        expected = json.load(open(os.path.join(FIXTURES, "pure-live-oci.expected.json")))
        assert core.is_live()
        assert core.live_image() == expected["live_image"]
        assert expected["live_image"] != ""
        assert core.offline_images() == set(expected["offline_images"])


    def test_installed_container_is_not_live(self, monkeypatch):
        _probe_from(monkeypatch, "container")
        assert not core.is_live()
        assert core.live_image() == ""
        assert core.offline_images() == set()

    def test_a_failed_probe_is_not_live(self, monkeypatch):
        monkeypatch.setenv("BOOTC_INSTALLER_FAKE_PROBE", "/nonexistent/probe.json")
        core.probe(refresh=True)
        assert not core.is_live()
        assert core.offline_images() == set()

    def test_no_detection_of_its_own(self):
        src = open(core.__file__).read()
        for gone in ("live_iso_image", "offline_stores", '"podman"', "rd.live.image",
                     "/run/ostree-live", "TUNA_OFFLINE_STORES"):
            assert gone not in src, gone


class TestCatalogLeaves:
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
        leaves = core.catalog_leaves({"images": [raw_parent]})
        assert len(leaves) == 1
        child = leaves[0]

        assert child.name == "XFCE"
        assert child.imgref == "ghcr.io/tuna-os:xfce"
        assert child.bootloader == "systemd-boot"
        assert child.filesystem == "btrfs"
        # The row says the product, not only the channel (#289).
        assert child.label == "Desktop XFCE"
        assert child.breadcrumb == "Desktop \u203a XFCE"

    def test_needs_user_creation_defaults_to_an_account(self):
        leaves = core.catalog_leaves({"images": [
            {"name": "A", "imgref": "r.example/a:1"},
            {"name": "B", "registry": "r.example/b", "needs_user_creation": False,
             "children": [{"name": "One", "tag": "1"},
                          {"name": "Two", "tag": "2", "needs_user_creation": True}]},
        ]})
        assert [leaf.needs_user_creation for leaf in leaves] == [True, False, True]


class TestLoadCatalog:
    def test_loads_images_json_file(self, tmp_path):
        cfg = tmp_path / "images.json"
        cfg.write_text(json.dumps({
            "default_image": "ghcr.io/tuna-os/xfce:latest",
            "fallback_flatpaks": ["org.gnome.Loupe"],
            "images": [{"name": "XFCE", "imgref": "ghcr.io/tuna-os/xfce:latest"}]
        }))
        catalog = core.load_catalog([str(cfg)])
        assert catalog.default_image == "ghcr.io/tuna-os/xfce:latest"
        assert len(catalog.leaves) == 1
        assert catalog.leaves[0].name == "XFCE"
        assert catalog.roots[0].name == "XFCE"
        # fallback_flatpaks is not part of the contract: never read, never
        # sent (shared/catalog/README.md).
        assert not hasattr(catalog, "fallback_flatpaks")
        assert catalog.leaves[0].flatpaks is None

    def test_a_file_that_does_not_load_does_not_stop_the_search(self, tmp_path):
        broken = tmp_path / "broken.json"
        broken.write_text("{nope")
        not_a_catalog = tmp_path / "list.json"
        not_a_catalog.write_text('{"images": "none"}')
        good = tmp_path / "images.json"
        good.write_text(json.dumps({"images": [{"name": "A", "imgref": "r.example/a:1"}]}))
        catalog = core.load_catalog([str(tmp_path / "missing.json"), str(broken),
                                     str(not_a_catalog), str(good)])
        assert catalog.path == str(good)
        assert [leaf.imgref for leaf in catalog.leaves] == ["r.example/a:1"]

    def test_the_harness_override_is_read_first(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FISHERMAN_IMAGES_PATH", str(tmp_path / "x.json"))
        paths = core.images_json_paths()
        assert paths[0] == str(tmp_path / "x.json")
        assert paths[1:] == core.catalog_search_paths()


# Disks, sizes and the TPM come from `fisherman probe --json` now: see
# tests/test_probe.py.


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
        r = core.build_recipe(**MINIMAL, hostname="reef")
        assert r["disk"] == "/dev/vda"
        assert r["filesystem"] == "xfs"
        assert r["hostname"] == "reef"
        assert r["distroID"] == core.BRANDING.id
        assert r["selinuxDisabled"] is False
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
        """`tpm2-luks` unlocks from the TPM alone — see ENCRYPTION_TYPES."""
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

    def test_a_flatpak_list_is_written_as_given(self):
        r = core.build_recipe(**MINIMAL, flatpaks=["org.gnome.Loupe", "org.gnome.Calculator"])
        assert r["flatpaks"] == ["org.gnome.Loupe", "org.gnome.Calculator"]

    def test_an_empty_flatpak_list_is_a_value(self):
        """`[]` tells fisherman to copy no Flatpak; no key tells it to apply
        its own default. The two are not the same."""
        assert core.build_recipe(**MINIMAL, flatpaks=[])["flatpaks"] == []
        assert "flatpaks" not in core.build_recipe(**MINIMAL, flatpaks=None)

    def test_catalog_reference_is_not_a_package_list(self):
        """A leading @ names a catalog alias. Passing it verbatim would ask
        fisherman to install a flatpak called '@desktop'; an alias that names
        a list is that list, and a URL or an unknown alias is no key."""
        aliases = {"desktop": ["org.example.A"], "remote": "https://example.org/Brewfile"}
        assert core.resolve_flatpaks("@desktop", aliases) == ["org.example.A"]
        assert core.resolve_flatpaks("@remote", aliases) is None
        assert core.resolve_flatpaks("@missing", aliases) is None
        assert core.resolve_flatpaks("https://example.org/Brewfile", aliases) is None
        assert core.resolve_flatpaks(None, aliases) is None
        assert core.resolve_flatpaks([], aliases) == []

    def test_target_imgref_and_leaf_keys_only_when_set(self):
        r = core.build_recipe(**MINIMAL, image="r.example/a:1", target_imgref="r.example/a:1",
                              flatpak_var_path="state/var", image_type="ostree")
        assert r["targetImgref"] == "r.example/a:1"
        assert r["flatpakVarPath"] == "state/var"
        assert r["imageType"] == "ostree"
        bare = core.build_recipe(**MINIMAL)
        for key in ("targetImgref", "flatpakVarPath", "imageType"):
            assert key not in bare

    # --- offline stores ---

    def test_stores_are_left_to_fisherman(self):
        """Absent, fisherman exposes the host's offline stores itself."""
        r = core.build_recipe(**MINIMAL)
        assert "additionalImageStores" not in r

    # --- user block ---

    def test_user_block_built_when_the_image_needs_one(self):
        r = core.build_recipe(**MINIMAL, needs_user=True, username="jo",
                              fullname="Jo Fish", password="pw")
        assert r["user"] == {"username": "jo", "fullname": "Jo Fish",
                             "password": "pw", "groups": list(core.DEFAULT_GROUPS)}
        assert {"wheel", "sudo"} <= set(r["user"]["groups"])

    def test_operator_groups_replace_the_default(self):
        r = core.build_recipe(**MINIMAL, needs_user=True, username="jo", groups=[])
        assert r["user"]["groups"] == []

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

    def test_recipe_survives_the_stdin_encoding(self):
        built = core.build_recipe(**MINIMAL, encryption_type="luks-passphrase",
                                  passphrase="pw", needs_user=True, username="jo")
        assert json.loads(core.recipe_stdin(built)) == built


# ─── "install this system": the live image's layout ────────────────────────

class TestLiveSystem:
    # What tunaOS customize-live.sh wrote to grouper:xfce's live media
    # (ghcr.io/tuna-os/live-overlay:grouper-xfce, 2026-11-10), less branding.
    GROUPER = {"imgref": "ghcr.io/tuna-os/grouper:xfce", "bootloader": "systemd",
               "composeFsBackend": True, "filesystem": "ext4"}

    def test_reads_the_operator_recipe_backend(self, tmp_path):
        path = tmp_path / "recipe.json"
        path.write_text(json.dumps(self.GROUPER))
        live = core.live_system(str(path))
        assert (live.bootloader, live.composefs, live.filesystem) == ("systemd", True, "ext4")
        assert live.filesystems == ["ext4"]
        assert live.imgref == ""

    def test_reaches_the_recipe(self):
        """grouper's install failed "bootupd is required for ostree-based
        installs" because this recipe had no composeFsBackend (#343)."""
        live = core.LiveSystem(self.GROUPER)
        r = core.build_recipe(disk="/dev/vda", filesystem=live.filesystem,
                              bootloader=live.bootloader, composefs=live.composefs)
        assert r["image"] == ""
        assert r["bootloader"] == "systemd"
        assert r["composeFsBackend"] is True
        assert r["filesystem"] == "ext4"

    def test_no_file_leaves_it_to_fisherman(self, tmp_path):
        live = core.live_system(str(tmp_path / "absent.json"))
        assert (live.bootloader, live.composefs) == ("", False)
        assert (live.filesystem, live.filesystems) == ("", [])
        r = core.build_recipe(disk="/dev/vda", filesystem="xfs",
                              bootloader=live.bootloader, composefs=live.composefs)
        assert "bootloader" not in r and "composeFsBackend" not in r

    def test_wrong_types_are_ignored(self):
        live = core.LiveSystem({"bootloader": 1, "composeFsBackend": "true",
                                "filesystem": ["ext4"]})
        assert (live.bootloader, live.composefs, live.filesystem) == ("", False, "")


# ─── fisherman invocation: the recipe on stdin ──────────────────────────────

class TestFisherman:
    def test_nothing_writes_a_recipe_file(self):
        assert not hasattr(core, "write_recipe")
        assert not hasattr(core, "recipe_dir")
        assert "tempfile" not in open(core.__file__).read()

    # One resolver, fisherman_command(), for the probe, the validate checks
    # and the install; these are its three worlds (#290).

    def test_native_install_uses_pkexec_and_reads_stdin(self):
        # Not sudo: a GUI has no terminal for its prompt.
        assert core.fisherman_command("install", in_flatpak=False, live=False) == [
            "bash", "-c", "pkexec /usr/local/bin/fisherman -; exit $?"]
        assert core.fisherman_argv(in_flatpak=False, live=False) == [
            "bash", "-c", "pkexec /usr/local/bin/fisherman -; exit $?"]

    def test_live_media_install_uses_sudo_without_a_prompt(self):
        assert core.fisherman_command("install", in_flatpak=False, live=True) == [
            "bash", "-c", "sudo -n /usr/local/bin/fisherman -; exit $?"]

    def test_native_install_asks_the_probe_whether_this_is_live_media(self, monkeypatch):
        monkeypatch.setattr(core, "is_live", lambda: True)
        assert "sudo -n" in core.fisherman_command("install", in_flatpak=False)[-1]
        monkeypatch.setattr(core, "is_live", lambda: False)
        assert core.fisherman_command("install", in_flatpak=False)[-1].startswith("pkexec ")

    def test_native_probe_and_validate_are_unprivileged(self):
        assert core.fisherman_command("probe", in_flatpak=False) == [
            "/usr/local/bin/fisherman", "probe", "--json"]
        assert core.fisherman_command("validate", in_flatpak=False) == [
            "/usr/local/bin/fisherman", "validate", "--json", "--partial", "-"]
        assert core.fisherman_command("validate-full", in_flatpak=False) == [
            "/usr/local/bin/fisherman", "validate", "--json", "-"]

    def test_flatpak_runs_the_staged_binary_for_all_three(self):
        staged = "/home/u/.var/app/org.example/cache/bootc-installer/fisherman"
        assert core.fisherman_command("probe", in_flatpak=True, host_path=staged) == [
            "flatpak-spawn", "--host", staged, "probe", "--json"]
        assert core.fisherman_command("validate", in_flatpak=True, host_path=staged) == [
            "flatpak-spawn", "--host", staged, "validate", "--json", "--partial", "-"]
        # Not `flatpak-spawn --host pkexec ...`: then fisherman's parent is
        # the host's flatpak-session-helper and it cannot be cancelled.
        assert core.fisherman_command("install", in_flatpak=True, host_path=staged) == [
            "flatpak-spawn", "--host", "bash", "-c", f"pkexec {staged} -; exit $?"]

    def test_flatpak_never_uses_the_hosts_fisherman(self):
        for purpose in core.FISHERMAN_PURPOSES:
            argv = core.fisherman_command(purpose, in_flatpak=True, host_path="/cache/f")
            assert "/usr/local/bin/fisherman" not in " ".join(argv), purpose

    def test_flatpak_stages_before_it_answers(self, monkeypatch):
        monkeypatch.setattr(core, "staged_fisherman", lambda: "/staged/fisherman")
        for purpose in core.FISHERMAN_PURPOSES:
            assert "/staged/fisherman" in " ".join(
                core.fisherman_command(purpose, in_flatpak=True)), purpose

        def refuse():
            raise core.StageError("no")

        monkeypatch.setattr(core, "staged_fisherman", refuse)
        import pytest
        with pytest.raises(core.StageError):
            core.fisherman_command("install", in_flatpak=True)

    def test_a_staged_path_with_a_space_is_one_word_for_the_host_bash(self):
        argv = core.fisherman_command("install", in_flatpak=True, host_path="/a b/fisherman")
        assert argv[-1] == "pkexec '/a b/fisherman' -; exit $?"

    def test_an_unknown_purpose_is_refused(self):
        import pytest
        with pytest.raises(ValueError):
            core.fisherman_command("uninstall", in_flatpak=False)

    def test_shell_line(self):
        assert core.shell_line(core.fisherman_argv(in_flatpak=False, live=True)) == (
            "bash -c 'sudo -n /usr/local/bin/fisherman -; exit $?'")

    def test_only_the_resolver_names_how_fisherman_runs(self):
        """No page or dialog builds its own command: outside core.py no
        string of the code (docstrings apart) names the binary or pkexec."""
        import ast

        package = os.path.dirname(core.__file__)
        scanned = 0
        for name in sorted(os.listdir(package)):
            if not name.endswith(".py") or name == "core.py":
                continue
            with open(os.path.join(package, name), encoding="utf-8") as stream:
                tree = ast.parse(stream.read())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                    body = node.body
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)):
                        docstrings.add(id(body[0].value))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docstrings):
                    scanned += 1
                    for needle in ("/usr/local/bin/fisherman", "/app/bin/fisherman",
                                   "pkexec", "sudo"):
                        assert needle not in node.value, f"{name} names {needle}"
        assert scanned > 100, "the scan read the package's strings"

    def _run_wrapper(self, tmp_path, tool, argv):
        """Run the wrapper's bash for real, with `tool` stubbed: the recipe
        written to the wrapper's stdin is what fisherman reads."""
        stub = tmp_path / "bin"
        stub.mkdir()
        (stub / tool).write_text(
            '#!/bin/sh\n'
            'printf \'{"type":"step","argv":"%s"}\\n\' "$*"\n'
            'cat > "$RECIPE_OUT"\n'
            'echo "to stderr" >&2\n'
            'exit 7\n')
        (stub / tool).chmod(0o755)
        out = tmp_path / "recipe-read"
        env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}", RECIPE_OUT=str(out))
        recipe = core.build_recipe(**MINIMAL, encryption_type="luks-passphrase",
                                   passphrase="pw")
        done = subprocess.run(argv, env=env, cwd=tmp_path, input=core.recipe_stdin(recipe),
                              capture_output=True)
        assert done.returncode == 7
        assert done.stderr == b"to stderr\n"
        assert json.loads(out.read_text()) == recipe
        assert list(tmp_path.glob("*.json")) == []
        return json.loads(done.stdout)["argv"]

    def test_flatpak_wrapper_passes_stdin_stdout_stderr_and_status_through(self, tmp_path):
        argv = core.fisherman_argv(in_flatpak=True, host_path="/cache/fisherman")
        assert argv[:2] == ["flatpak-spawn", "--host"]
        assert self._run_wrapper(tmp_path, "pkexec", argv[2:]) == "/cache/fisherman -"

    def test_native_wrapper_passes_stdin_stdout_stderr_and_status_through(self, tmp_path):
        argv = core.fisherman_argv(in_flatpak=False, live=False)
        assert self._run_wrapper(tmp_path, "pkexec", argv) == "/usr/local/bin/fisherman -"

    def test_live_wrapper_passes_stdin_stdout_stderr_and_status_through(self, tmp_path):
        argv = core.fisherman_argv(in_flatpak=False, live=True)
        assert self._run_wrapper(tmp_path, "sudo", argv) == "-n /usr/local/bin/fisherman -"


# ─── staging the bundled fisherman in a Flatpak (#290) ──────────────────────

class TestStaging:
    def _source(self, tmp_path):
        source = tmp_path / "app-bin-fisherman"
        source.write_bytes(b"#!/bin/sh\necho fisherman\n")
        return source

    def _env(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir(mode=0o700)
        return {"XDG_CACHE_HOME": str(cache), "HOME": str(tmp_path / "home")}

    def test_the_stage_path_is_the_app_cache_never_home(self, tmp_path):
        env = {"HOME": "/var/home/test",
               "XDG_CACHE_HOME": "/var/home/test/.var/app/app.id/cache"}
        assert core.staged_fisherman_path(env) == (
            "/var/home/test/.var/app/app.id/cache/bootc-installer/fisherman")

    def test_a_missing_or_relative_cache_is_refused(self):
        import pytest
        for cache in ("", "relative"):
            with pytest.raises(core.StageError, match="absolute path"):
                core.fisherman_stage_dir({"HOME": "/home/test", "XDG_CACHE_HOME": cache})
        # Never a path made from HOME.
        with pytest.raises(core.StageError):
            core.fisherman_stage_dir({"HOME": "/home/test"})

    def test_staging_copies_and_verifies_on_the_host(self, tmp_path):
        source, env = self._source(tmp_path), self._env(tmp_path)
        asked = []

        def host_sha256(path):
            asked.append(path)
            return core._sha256(path)

        staged = core.stage_fisherman(str(source), env, host_sha256)
        assert staged == core.staged_fisherman_path(env)
        assert asked == [staged], "the host is asked about the staged copy"
        with open(staged, "rb") as stream:
            assert stream.read() == source.read_bytes()
        assert stat_mode(staged) == 0o700
        assert stat_mode(os.path.dirname(staged)) == 0o700

    def test_staging_fails_when_the_host_sees_other_bytes(self, tmp_path):
        import pytest
        source, env = self._source(tmp_path), self._env(tmp_path)
        for answer in ("0" * 64, ""):
            with pytest.raises(core.StageError, match="byte-identical"):
                core.stage_fisherman(str(source), env, lambda path, a=answer: a)

    def test_staging_refuses_a_symlinked_target(self, tmp_path):
        import pytest
        source, env = self._source(tmp_path), self._env(tmp_path)
        stage_dir = core.fisherman_stage_dir(env)
        os.makedirs(stage_dir, mode=0o700)
        os.symlink("/etc/passwd", os.path.join(stage_dir, "fisherman"))
        with pytest.raises(core.StageError, match="symlink"):
            core.stage_fisherman(str(source), env, core._sha256)

    def test_staging_refuses_a_world_writable_cache(self, tmp_path):
        import pytest
        source, env = self._source(tmp_path), self._env(tmp_path)
        stage_dir = core.fisherman_stage_dir(env)
        os.makedirs(stage_dir)
        os.chmod(stage_dir, 0o777)
        with pytest.raises(core.StageError, match="writable"):
            core.stage_fisherman(str(source), env, core._sha256)

    def test_a_missing_bundled_binary_is_a_stage_error(self, tmp_path):
        import pytest
        with pytest.raises(core.StageError, match="cannot stage"):
            core.stage_fisherman(str(tmp_path / "absent"), self._env(tmp_path), core._sha256)

    def test_the_host_hash_goes_through_the_portal(self, monkeypatch):
        calls = []

        class Result:
            returncode = 0
            stdout = "abc123  /cache/fisherman\n"

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return Result()

        monkeypatch.setattr(core.subprocess, "run", fake_run)
        assert core._host_sha256("/cache/fisherman") == "abc123"
        assert calls == [["flatpak-spawn", "--host", "sha256sum", "--", "/cache/fisherman"]]

    def test_staging_happens_once(self, monkeypatch):
        count = []
        monkeypatch.setattr(core, "stage_fisherman", lambda: count.append(1) or "/s/f")
        monkeypatch.setattr(core, "_stage_cache", {})
        assert core.staged_fisherman() == "/s/f"
        assert core.staged_fisherman() == "/s/f"
        assert len(count) == 1


def stat_mode(path):
    return os.stat(path).st_mode & 0o777


# ─── validation and encryption choices: fisherman's ────────────────────────

class TestValidateAndChoices:
    def test_validate_argv_is_partial_on_stdin_and_unprivileged(self):
        argv = core.validate_argv()
        assert argv[-4:] == ["validate", "--json", "--partial", "-"]
        assert "sudo" not in argv and "pkexec" not in argv

    def test_validate_argv_survives_a_fisherman_that_cannot_be_staged(self, monkeypatch):
        def refuse(*_args, **_kwargs):
            raise core.StageError("no")

        monkeypatch.setattr(core, "fisherman_command", refuse)
        # The command cannot run; LiveCheck reports that and blocks nothing.
        assert core.validate_argv()[-4:] == ["validate", "--json", "--partial", "-"]

    def test_choices_come_from_the_file(self):
        assert [c["type"] for c in core.ENCRYPTION_CHOICES] == [
            "none", "luks-passphrase", "tpm2-luks", "tpm2-luks-passphrase"]
        assert core.needs_passphrase("tpm2-luks-passphrase")
        assert not core.needs_passphrase("tpm2-luks")
        assert core.needs_tpm2("tpm2-luks") and not core.needs_tpm2("luks-passphrase")


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


class TestLoadCatalogFallback:
    def test_missing_file_returns_defaults(self):
        catalog = core.load_catalog(["/path/that/does/not/exist.json"])
        assert catalog.default_image == ""
        assert catalog.leaves == []
        assert catalog.roots == []
        assert catalog.default_leaf("anything") is None
        # An image no catalog has needs an account.
        assert catalog.needs_user_creation("r.example/unknown:1") is True
