"""Both root leaves and grouped leaves are valid image catalogs."""
from types import SimpleNamespace
from unittest.mock import patch

from bootc_installer.defaults import image


def test_root_and_grouped_leaves_use_their_container_api():
    ref = 'localhost/example:latest'
    tree = [
        {'name': 'Root product', 'imgref': ref, 'filesystem': 'ext4', 'composefs': True},
        {'name': 'Other products', 'children': [{'name': 'Nested', 'imgref': 'localhost/other:latest'}]},
    ]
    controller = SimpleNamespace(recipe={})
    with patch.object(image, '_IMAGE_TREE', tree), patch.object(image, '_DEFAULT_IMAGE', ref):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    leaves = page._BootcDefaultImage__leaf_rows
    assert len(leaves) == 2
    assert leaves[0][0].get_parent() is page.list_images
    assert leaves[1][0].get_parent() is not page.list_images
    finals = page.get_finals()
    assert finals['selected_image'] == ref
    assert finals['image_filesystem'] == 'ext4'
    assert finals['composefs_backend'] is True


def test_selected_catalog_identity_survives_channel_labels_and_other_os_selection():
    ref = 'localhost/base-family:latest'
    tree = [
        {'name': 'Example Remix', 'imgref': ref},
        {'name': 'Other OS', 'registry': 'localhost/other', 'children': [
            {'name': 'Stable', 'tag': 'stable'},
            {'name': 'Developer OS', 'registry': 'localhost/other-dev', 'children': [
                {'name': 'Latest', 'tag': 'latest'}]},
        ]},
        {'name': ' ', 'imgref': 'localhost/fallback:latest'},
    ]
    controller = SimpleNamespace(recipe={'distro_name': 'Example Remix'})
    with patch.object(image, '_IMAGE_TREE', tree), patch.object(image, '_DEFAULT_IMAGE', ref):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    leaves = page._BootcDefaultImage__leaf_rows
    for leaf, expected in zip(leaves, ['Example Remix', 'Other OS', 'Developer OS', 'Fallback'], strict=True):
        leaf[1].set_active(True)
        finals = page.get_finals()
        assert finals['pretty_name'] == expected
        assert finals['selected_image'] == leaf[2]
    page.row_custom.set_expanded(True)
    page.image_url_entry.set_text('localhost/custom-system:latest')
    assert page.get_finals()['pretty_name'] == image._imgref_to_pretty_name('localhost/custom-system:latest')


def test_recipe_extra_images_keep_names_and_unnamed_slug_fallback():
    controller = SimpleNamespace(recipe={'images': [
        {'name': 'Recipe Remix', 'imgref': 'localhost/family:latest'},
        {'imgref': 'localhost/unnamed:latest'},
    ]})
    with patch.object(image, '_IMAGE_TREE', []), patch.object(image, '_DEFAULT_IMAGE', ''):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    for leaf, expected in zip(page._BootcDefaultImage__leaf_rows, ['Recipe Remix', 'Unnamed'], strict=True):
        leaf[1].set_active(True)
        assert page.get_finals()['pretty_name'] == expected


def _tree():
    return [
        {'name': 'First', 'imgref': 'localhost/first:latest'},
        {'name': 'Product', 'imgref': 'localhost/product:latest'},
    ]


def test_branding_default_image_is_selected_when_the_catalog_names_none():
    """#315: the bundled recipe names no image, so a product names its
    image through branding `default_image`."""
    controller = SimpleNamespace(recipe={'branding': {'default_image': 'localhost/product:latest'}})
    with patch.object(image, '_IMAGE_TREE', _tree()), patch.object(image, '_DEFAULT_IMAGE', ''):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    assert page.get_finals()['selected_image'] == 'localhost/product:latest'
    assert page.btn_next.get_sensitive()


def test_the_branding_default_wins_over_the_catalog_default():
    """shared/catalog/README.md: the branding's `default_image` first, then
    the catalog's. GNOME had the two the other way round."""
    controller = SimpleNamespace(recipe={'branding': {'default_image': 'localhost/product:latest'}})
    with patch.object(image, '_IMAGE_TREE', _tree()), \
         patch.object(image, '_DEFAULT_IMAGE', 'localhost/first:latest'):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    assert page.get_finals()['selected_image'] == 'localhost/product:latest'


def test_the_catalog_default_is_used_when_the_branding_default_is_not_a_leaf():
    controller = SimpleNamespace(recipe={'branding': {'default_image': 'localhost/absent:latest'}})
    with patch.object(image, '_IMAGE_TREE', _tree()), \
         patch.object(image, '_DEFAULT_IMAGE', 'localhost/first:latest'):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    assert page.get_finals()['selected_image'] == 'localhost/first:latest'


def test_the_page_reads_the_contract_fixture():
    """The real page, on shared/catalog/fixtures/catalog.json: each row
    hands on what bootc_shared.catalog resolves, and the account flag follows
    the selected leaf (default: an account)."""
    import copy
    import json
    import pathlib

    from bootc_installer.utils import image_finals
    from bootc_shared import catalog

    fixtures = pathlib.Path(__file__).resolve().parents[2] / 'shared' / 'catalog' / 'fixtures'
    manifest = json.loads((fixtures / 'catalog.json').read_text())
    expected = json.loads((fixtures / 'expected.json').read_text())
    loaded = copy.deepcopy(manifest)
    image._resolve_aliases(loaded, loaded['aliases'])
    controller = SimpleNamespace(recipe={})
    with patch.object(image, '_MANIFEST', loaded), \
         patch.object(image, '_IMAGE_TREE', loaded['images']), \
         patch.object(image, '_DEFAULT_IMAGE', loaded['default_image']):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    rows = page._BootcDefaultImage__leaf_rows
    assert [row[2] for row in rows] == [entry['imgref'] for entry in expected['leaves']]
    # The catalog's default_image is selected at the start.
    assert page.get_finals()['selected_image'] == manifest['default_image']
    for row, entry in zip(rows, expected['leaves'], strict=True):
        row[1].set_active(True)
        finals = page.get_finals()
        leaf = entry['leaf']
        assert finals['selected_image'] == leaf['imgref']
        assert page.selected_needs_user_creation is leaf['needs_user_creation']
        assert finals['needs_user_creation'] is leaf['needs_user_creation']
        assert finals.get('flatpaks') == leaf['flatpaks']
        assert ('flatpaks' in finals) is (leaf['flatpaks'] is not None)
        assert finals['supported_filesystems'] == leaf['filesystems']
        assert finals['default_filesystem'] == leaf['filesystem']
        assert finals['composefs_backend'] is leaf['composefs']
        assert finals['bootloader'] == leaf['bootloader']
        assert finals['flatpak_var_path'] == leaf['flatpak_var_path']
        assert finals['default_hostname'] == leaf['default_hostname']
        assert finals['nvidia_imgref'] == leaf['nvidia_imgref']
        assert finals['pretty_name'] == leaf['product']
        expected_finals = image_finals.leaf_finals(catalog.find(manifest, leaf['imgref']))
        assert {k: v for k, v in finals.items() if k not in ('icon', 'carousel')} == \
            {k: v for k, v in expected_finals.items() if k not in ('icon', 'carousel')}
    page.row_custom.set_expanded(True)
    page.image_url_entry.set_text('localhost/custom-system:latest')
    assert page.selected_needs_user_creation is True
    assert 'flatpaks' not in page.get_finals()


def test_a_branding_default_that_the_catalog_lacks_selects_nothing():
    """The user must pick: Next stays off."""
    controller = SimpleNamespace(recipe={'branding': {'default_image': 'localhost/absent:latest'}})
    with patch.object(image, '_IMAGE_TREE', _tree()), patch.object(image, '_DEFAULT_IMAGE', ''):
        page = image.BootcDefaultImage(controller, {}, 'image', {})
    assert page.get_finals()['selected_image'] is None
    assert not page.btn_next.get_sensitive()
