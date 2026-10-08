"""#184: timezone auto-detection must not send the user's location in clear
text, and must survive whatever the network sends back."""

import importlib
import json
import math
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _import_timezones():
    """bootc_installer.core.timezones with GWeather and GLib stubbed.

    The module walks GWeather's location tree at import; an empty world makes
    that walk end at once.
    """
    world = MagicMock()
    world.next_child.return_value = None
    world.get_parent.return_value = None
    gweather = types.SimpleNamespace(
        Location=types.SimpleNamespace(get_world=lambda: world),
        LocationLevel=types.SimpleNamespace(REGION=1, COUNTRY=2, CITY=3),
    )
    glib = types.SimpleNamespace(idle_add=lambda fn, *a: fn(*a))
    repo = types.SimpleNamespace(GWeather=gweather, GLib=glib)
    gi = types.SimpleNamespace(repository=repo, require_version=lambda *a, **k: None)
    mods = {"gi": gi, "gi.repository": repo, "requests": MagicMock()}
    with patch.dict(sys.modules, mods):
        sys.modules.pop("bootc_installer.core.timezones", None)
        mod = importlib.import_module("bootc_installer.core.timezones")
    return mod, world


class TestGeoipEndpoint(unittest.TestCase):
    def test_endpoint_is_https(self):
        mod, _ = _import_timezones()
        self.assertTrue(mod.GEOIP_URL.startswith("https://"), mod.GEOIP_URL)
        self.assertNotIn("ip-api.com", mod.GEOIP_URL)

    def test_get_location_requests_the_https_endpoint(self):
        mod, world = _import_timezones()
        response = MagicMock()
        response.json.return_value = {"latitude": 37.751, "longitude": -97.822,
                                      "time_zone": "America/Chicago"}
        mod.requests = MagicMock()
        mod.requests.get.return_value = response
        world.find_nearest_city.return_value = "Wichita"
        got = []
        mod.get_location(got.append)
        url = mod.requests.get.call_args[0][0]
        self.assertTrue(url.startswith("https://"), url)
        world.find_nearest_city.assert_called_once_with(37.751, -97.822)
        self.assertEqual(got, ["Wichita"])

    def test_unusable_response_means_no_guess(self):
        mod, world = _import_timezones()
        mod.requests = MagicMock()
        mod.requests.get.return_value.json.return_value = {"status": "fail"}
        got = []
        mod.get_location(got.append)
        world.find_nearest_city.assert_not_called()
        self.assertEqual(got, [None])


class TestParseGeoip(unittest.TestCase):
    def setUp(self):
        self.parse = _import_timezones()[0].parse_geoip

    def test_real_response_shape(self):
        # Captured from geoip.fedoraproject.org/city.
        payload = json.loads('{"country_code": "US", "time_zone": "America/Chicago", '
                             '"latitude": 37.751, "longitude": -97.822, "city": null}')
        self.assertEqual(self.parse(payload), (37.751, -97.822))

    def test_rejects_garbage(self):
        for payload in (None, [], "x", {}, {"latitude": 1}, {"latitude": "a", "longitude": 1},
                        {"latitude": 91, "longitude": 0}, {"latitude": 0, "longitude": 181},
                        {"latitude": math.nan, "longitude": 0},
                        {"latitude": None, "longitude": None}):
            with self.subTest(payload=payload):
                self.assertIsNone(self.parse(payload))


if __name__ == "__main__":
    unittest.main()
