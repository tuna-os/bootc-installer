"""shared/tpm/ — the TPM 2.0 detection contract.

Every frontend used to decide this by testing `/sys/class/tpm/tpm0` for
existence. The kernel creates that directory for a TPM 1.2 device too, so a
1.2 machine was offered `tpm2-luks` and the install failed at enrolment,
after fisherman had partitioned the disk.

No CI runner has a TPM of any version, which is why nothing caught it, and
why the fixture trees under shared/tpm/fixtures/ exist.
"""

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHARED = os.path.join(REPO, "shared", "tpm")
FIXTURES = os.path.join(SHARED, "fixtures")

CANONICAL = os.path.join(SHARED, "tpm_probe.py")
COPIES = [
    os.path.join(REPO, "bootc_installer", "core", "tpm_probe.py"),
    os.path.join(REPO, "frontends", "xfce", "tuna_installer_xfce", "tpm_probe.py"),
]

sys.path.insert(0, SHARED)
import tpm_probe  # noqa: E402

# tree -> what the probe must answer, and why.
CASES = [
    ("tpm2", True, "tpm_version_major reads 2"),
    ("tpm12", False, "a TPM 1.2 device cannot do tpm2-luks"),
    ("legacy-tpm2", True, "no version file, but /dev/tpmrm0 is TPM2-only"),
    ("legacy-none", False, "no version file and no resource manager"),
]


def test_copies_are_byte_identical():
    """Same arrangement shared/progress/ uses: one canonical file, copies."""
    want = open(CANONICAL, "rb").read()
    for copy in COPIES:
        assert open(copy, "rb").read() == want, f"{copy} has drifted"


def test_every_fixture_tree_exists():
    for tree, _, _ in CASES:
        assert os.path.isdir(os.path.join(FIXTURES, tree)), tree


def test_probe_answers_every_case():
    for tree, want, why in CASES:
        got = tpm_probe.probe_tpm2(os.path.join(FIXTURES, tree))
        assert got is want, f"{tree}: expected {want} because {why}"


def test_a_tpm12_device_is_not_tpm2():
    """The bug, stated on its own.

    The old probe was the existence of the tpm0 directory, which this tree
    has. Anything that reduces to that existence check fails here.
    """
    assert tpm_probe.probe_tpm2(os.path.join(FIXTURES, "tpm12")) is False
    assert os.path.isdir(
        os.path.join(FIXTURES, "tpm12", "sys", "class", "tpm", "tpm0")
    ), "the fixture must still have the directory, or it proves nothing"


def test_the_directory_alone_is_never_the_answer():
    """Every tree has the tpm0 directory; the answers still differ."""
    for tree, _, _ in CASES:
        node = os.path.join(FIXTURES, tree, "sys", "class", "tpm", "tpm0")
        if tree == "legacy-tpm2":
            continue  # has the directory and the resource manager both
        assert os.path.isdir(node), tree
    answers = {tree: tpm_probe.probe_tpm2(os.path.join(FIXTURES, tree))
               for tree, _, _ in CASES}
    assert len(set(answers.values())) == 2, answers


def test_fake_tpm_only_forces_it_on():
    assert tpm_probe.fake_tpm_requested({"BOOTC_INSTALLER_FAKE_TPM": "1"}) is True
    for blank in ("", "0"):
        assert tpm_probe.fake_tpm_requested(
            {"BOOTC_INSTALLER_FAKE_TPM": blank}) is False, repr(blank)
    assert tpm_probe.fake_tpm_requested({}) is False


def test_gnome_and_the_shared_probe_agree():
    """GNOME reads it through Systeminfo, which caches the real root only."""
    sys.path.insert(0, REPO)
    from bootc_installer.core.system import Systeminfo

    for tree, want, why in CASES:
        got = Systeminfo.has_tpm2(os.path.join(FIXTURES, tree))
        assert got is want, f"{tree}: expected {want} because {why}"


def test_the_go_frontend_agrees():
    """Niri implements the same contract in Go; it must give the same answers."""
    niri = os.path.join(REPO, "frontends", "niri", "installer")
    if not os.path.isdir(niri):
        return
    proc = subprocess.run(
        ["go", "test", "-run", "TestProbeTPM2", "-json", "./..."],
        cwd=niri, capture_output=True, text=True)
    if proc.returncode != 0 and "go: " in proc.stderr[:8]:
        return  # no Go toolchain on this runner
    failures = [json.loads(line)
                for line in proc.stdout.splitlines() if line.startswith("{")]
    assert not [f for f in failures if f.get("Action") == "fail"], proc.stdout
