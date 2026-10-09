"""shared/tpm/ — the TPM 2.0 detection contract, now answered by fisherman.

Every frontend used to decide this by testing `/sys/class/tpm/tpm0` for
existence. The kernel creates that directory for a TPM 1.2 device too, so a
1.2 machine was offered `tpm2-luks` and the install failed at enrolment,
after fisherman had partitioned the disk. The five frontends then each
implemented shared/tpm/README.md themselves.

`fisherman probe --json` now owns the probe (its `tpm.usable` is this
contract's answer, tested against copies of these fixture trees) and the
frontends only read it (shared/probe/README.md). These tests keep it that
way: fisherman's copies of the fixtures must match these, and no frontend may
grow its own probe back.
"""

import filecmp
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(REPO, "shared", "tpm", "fixtures")
FISHERMAN_FIXTURES = os.path.join(
    REPO, "fisherman", "fisherman", "internal", "probe", "testdata", "tpm")

TREES = ("tpm2", "tpm12", "legacy-tpm2", "legacy-none")

# Where each frontend's own code lives. Test trees are excluded: they may
# name the files to explain what moved.
FRONTEND_SOURCES = [
    ("bootc_installer", (".py",)),
    ("frontends/xfce/tuna_installer_xfce", (".py",)),
    ("frontends/kde/src", (".cpp", ".h")),
    ("frontends/cosmic/src", (".rs",)),
    ("frontends/niri/installer", (".go",)),
]
# A path in a string literal: the probe itself, not a comment about it.
PROBE_MARKERS = re.compile(r"[\"'][^\"'\n]*(tpm_version_major|tpmrm0|/sys/class/tpm)")


def _files(tree):
    out = set()
    for root, _dirs, files in os.walk(tree):
        for name in files:
            out.add(os.path.relpath(os.path.join(root, name), tree))
    return out


def test_every_fixture_tree_exists():
    for tree in TREES:
        assert os.path.isdir(os.path.join(FIXTURES, tree)), tree


def test_fishermans_copies_match_these_fixtures():
    if not os.path.isdir(FISHERMAN_FIXTURES):
        return  # submodule not checked out
    for tree in TREES:
        ours = os.path.join(FIXTURES, tree)
        theirs = os.path.join(FISHERMAN_FIXTURES, tree)
        assert _files(ours) == _files(theirs), tree
        for rel in _files(ours):
            assert filecmp.cmp(os.path.join(ours, rel), os.path.join(theirs, rel),
                               shallow=False), f"{tree}/{rel} differs from fisherman's copy"


def test_no_frontend_probes_the_tpm_itself():
    offenders = []
    for rel, exts in FRONTEND_SOURCES:
        base = os.path.join(REPO, rel)
        for root, _dirs, files in os.walk(base):
            if "/tests" in root or "/target" in root:
                continue
            for name in files:
                if not name.endswith(exts) or name.endswith("_test.go"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                # Rust unit tests live beside the code; skip that module.
                text = text.split("#[cfg(test)]", 1)[0]
                if PROBE_MARKERS.search(text):
                    offenders.append(os.path.relpath(path, REPO))
    assert not offenders, (
        "these frontend files probe the TPM themselves; read tpm.usable from "
        f"`fisherman probe --json` instead (shared/probe/README.md): {offenders}")
