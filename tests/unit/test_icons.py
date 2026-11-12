"""Logo inputs work identically in native and Flatpak catalog/header views."""
from unittest.mock import Mock, patch

import pytest

from bootc_installer.utils.icons import resolve_icon, set_image_icon


@pytest.mark.parametrize('spec,kind,value', [
    ('resource:///org/example/logo.svg', 'resource', '/org/example/logo.svg'),
    ('example-logo-symbolic', 'theme', 'example-logo-symbolic'),
    ('/usr/share/example/logo.svg', 'file', '/run/host/usr/share/example/logo.svg'),
    ('/etc/example/logo.png', 'file', '/run/host/etc/example/logo.png'),
    ('/run/host/usr/share/logo.svg', 'file', '/run/host/usr/share/logo.svg'),
    ('/app/share/logo.svg', 'file', '/app/share/logo.svg'),
    ('/home/live/logo.png', 'file', '/home/live/logo.png'),
])
def test_flatpak_resolution(spec, kind, value):
    assert resolve_icon(spec, in_flatpak=True) == (kind, value)


@pytest.mark.parametrize('spec', ['', None, 12])
def test_empty_or_invalid_spec(spec):
    assert resolve_icon(spec) is None


def test_native_file_is_unchanged():
    assert resolve_icon('/usr/share/logo.svg', in_flatpak=False) == ('file', '/usr/share/logo.svg')


@pytest.mark.parametrize('spec,method,value', [
    ('resource:///org/example/logo.svg', 'set_from_resource', '/org/example/logo.svg'),
    ('example-logo', 'set_from_icon_name', 'example-logo'),
    ('/usr/share/logo.svg', 'set_from_file', '/run/host/usr/share/logo.svg'),
])
def test_gtk_image_dispatch(spec, method, value):
    image = Mock()
    with patch('bootc_installer.utils.icons.os.path.exists', return_value=True):
        set_image_icon(image, spec)
    getattr(image, method).assert_called_once_with(value)


@pytest.mark.parametrize('spec,kind,value', [
    ('resource:///org/example/logo.svg', 'resource', '/org/example/logo.svg'),
    ('/usr/share/example/logo.png', 'file', '/run/host/usr/share/example/logo.png'),
])
def test_a_logo_is_loaded_once_for_all_images_of_a_size(spec, kind, value):
    """Each Gtk.Image decoded its own copy of a logo at the file's size:
    the catalog's 190 logos held about 180 MB for each catalog page (#321,
    the UI suite ran out of memory)."""
    from bootc_installer.utils import icons

    paintable = object()
    loads = []
    images = [Mock(), Mock()]
    for image in images:
        image.get_pixel_size.return_value = 32
    with patch.dict(icons._paintables, clear=True), \
            patch.object(icons, '_load_paintable',
                         side_effect=lambda k, v, s: loads.append((k, v, s)) or paintable), \
            patch('bootc_installer.utils.icons.os.path.exists', return_value=True):
        for image in images:
            set_image_icon(image, spec)
    assert loads == [(kind, value, 32)]
    for image in images:
        image.set_from_paintable.assert_called_once_with(paintable)
        image.set_from_file.assert_not_called()
        image.set_from_resource.assert_not_called()


def test_an_image_without_a_pixel_size_keeps_the_file_size():
    image = Mock()
    image.get_pixel_size.return_value = -1
    set_image_icon(image, 'resource:///org/example/logo.svg')
    image.set_from_resource.assert_called_once_with('/org/example/logo.svg')
    image.set_from_paintable.assert_not_called()


def test_shared_portable_logo_contract():
    import json
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[2] / 'shared/branding/fixtures/logo-paths.json'
    for case in json.loads(fixture.read_text())['cases']:
        resolved = resolve_icon(case['spec'], in_flatpak=case['in_flatpak'])
        assert (resolved or ('none', '')) == (case['kind'], case['value'])
