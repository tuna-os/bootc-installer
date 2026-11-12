"""The disk page offers a /var disk exactly where fisherman accepts one.

`var_disk_offered` (defaults/disk_plan.py) mirrors fisherman's
`var_disk_unsupported_composefs` rule (tuna-os/fisherman#252). This test
asks the real `fisherman validate --json --partial -` for each case, so the
two cannot drift. It needs a fisherman binary in FISHERMAN_BIN; the Recipe
compliance workflow sets one and RECIPE_COMPLIANCE_REQUIRE_FISHERMAN.
"""
import json
import os
import subprocess

import pytest

from bootc_installer.defaults.disk_plan import var_disk_offered

CASES = [(composefs, fs) for composefs in (False, True) for fs in ("xfs", "ext4", "btrfs", "zfs")]


def _fisherman():
    # Only FISHERMAN_BIN: a "fisherman" on PATH can be a test shim.
    return os.environ.get("FISHERMAN_BIN", "")


@pytest.mark.parametrize(("composefs", "filesystem"), CASES)
def test_offer_matches_fisherman(composefs, filesystem):
    binary = _fisherman()
    if not binary:
        if os.environ.get("RECIPE_COMPLIANCE_REQUIRE_FISHERMAN"):
            pytest.fail("no fisherman binary, and the workflow requires one")
        pytest.skip("no fisherman binary (set FISHERMAN_BIN)")
    recipe = {"varDisk": {"disk": "/dev/vdb"}, "composeFsBackend": composefs,
              "filesystem": filesystem}
    run = subprocess.run([binary, "validate", "--json", "--partial", "-"],
                         input=json.dumps(recipe), capture_output=True, text=True,
                         timeout=60, check=False)
    codes = {e.get("code") for e in json.loads(run.stdout)["errors"]}
    refused = "var_disk_unsupported_composefs" in codes
    assert var_disk_offered({"composefs_backend": composefs}, filesystem) is not refused, codes
