"""shared/walkthrough/capture-catalog.json is the one image catalog of the
capture harnesses (shared/README.md, "walkthrough/").

It names no product of ours: the committed walkthrough of each frontend
is photographed from it, and CLAUDE.md forbids a product in a frontend.
"""

import importlib.util
import json
import os
import re

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CATALOG = os.path.join(REPO, "shared", "walkthrough", "capture-catalog.json")
# The harness of each frontend that shows an image list, and how it names
# the file. KDE's capture has no image list.
HARNESSES = {
    "gnome": ("tests/gui/capture-screens.py",
              '"shared", "walkthrough", "capture-catalog.json"'),
    "xfce": ("frontends/xfce/tests/gui/capture-screens.py",
             '"capture-catalog.json"'),
    "niri": ("frontends/niri/tests/gui/capture-screens.py",
             '"capture-catalog.json"'),
    "cosmic": ("frontends/cosmic/src/capture.rs",
               '"/../../shared/walkthrough/capture-catalog.json"'),
}
PRODUCTS = re.compile(r"tuna|bluefin|ublue|bonito|aurora|bazzite|fedora|centos", re.IGNORECASE)


def _resolver():
    spec = importlib.util.spec_from_file_location(
        "shared_catalog_resolve", os.path.join(REPO, "shared", "catalog", "resolve.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as stream:
        return stream.read()


def test_every_harness_with_an_image_list_reads_the_shared_catalog():
    for frontend, (path, reference) in HARNESSES.items():
        text = _read(path)
        assert reference in text, frontend
        # No second catalog in the harness.
        assert '"images": [' not in text and "'images': [" not in text, frontend


def test_the_catalog_names_no_product():
    assert not PRODUCTS.search(_read("shared/walkthrough/capture-catalog.json"))


def test_the_catalog_has_what_the_pages_photograph():
    resolve = _resolver()
    catalog = resolve.load(CATALOG)
    leaves = {leaf["imgref"]: leaf for leaf in resolve.leaves(catalog)}
    default = leaves[catalog["default_image"]]
    # The account page renders: the selection needs an account. A leaf with
    # no account shows the step go away.
    assert default["needs_user_creation"] is True
    assert any(not leaf["needs_user_creation"] for leaf in leaves.values())
    # Rows show the product and the channel: one product has channels.
    assert len({leaf["product"] for leaf in leaves.values()}) >= 2
    assert sum(leaf["product"] == default["product"] for leaf in leaves.values()) >= 2
    # The probe fixture's offline images: one leaf is on the medium, one needs
    # a download (the offline frames of Niri and COSMIC).
    with open(os.path.join(REPO, "shared", "probe", "fixtures", "laptop.json"),
              encoding="utf-8") as stream:
        offline = set(json.load(stream)["offline"]["images"])
    assert catalog["default_image"] in offline
    assert any(imgref not in offline for imgref in leaves)
    # A tour slide for the tour frames.
    raw = json.dumps(catalog)
    assert '"carousel"' in raw
