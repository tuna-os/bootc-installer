"""The zones the time zone step offers, and a guess from GeoIP.

GWeather's world tree gives the most cities. It is optional: the GNOME
runtime or a test runner may have no GWeather typelib, and the step must
still work there. Without it the list comes from tzdata itself
(zone1970.tab and iso3166.tab), which every system with zoneinfo has.
Either way each row's value is an IANA zone name, the recipe's `timezone`.
"""

import datetime
import json
import logging
import math
import os
import urllib.request

from gi.repository import GLib
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:  # the step falls back to urllib
    requests = None

try:
    import gi

    gi.require_version("GWeather", "4.0")
    from gi.repository import GWeather
except (ImportError, ValueError, AttributeError):
    GWeather = None

logger = logging.getLogger("BootcInstaller::Timezones")

ZONEINFO = "/usr/share/zoneinfo"


def _gweather_regions():
    """region -> country -> city -> zone, from GWeather's world tree."""
    regions: dict[str, dict[str, dict[str, str]]] = {}
    world = GWeather.Location.get_world()
    parents = []
    base = world
    child = None
    while True:
        child = base.next_child(child)
        if child is not None:
            if child.get_level() == GWeather.LocationLevel.REGION:
                regions[child.get_name()] = {}
                current_region = child.get_name()
            elif child.get_level() == GWeather.LocationLevel.COUNTRY:
                regions[current_region][child.get_name()] = {}
                current_country = child.get_name()
            elif child.get_level() == GWeather.LocationLevel.CITY:
                regions[current_region][current_country][child.get_city_name()] = (
                    child.get_timezone_str()
                )

            if child.next_child(None) is not None:
                parents.append(child)
                base = child
                child = None
        else:
            base = base.get_parent()
            if base is None:
                break
            child = parents.pop()

    return regions


def _coordinate(text, degree_digits):
    """A zone1970.tab coordinate (+DDMM, +DDMMSS, +DDDMM...) in degrees."""
    sign = -1.0 if text[0] == "-" else 1.0
    digits = text[1:]
    degrees = int(digits[:degree_digits])
    minutes = int(digits[degree_digits:degree_digits + 2] or 0)
    seconds = int(digits[degree_digits + 2:degree_digits + 4] or 0)
    return sign * (degrees + minutes / 60 + seconds / 3600)


def parse_coordinates(text):
    """(latitude, longitude) of a zone1970.tab coordinates field."""
    split = max(text.rfind("+"), text.rfind("-"))
    return _coordinate(text[:split], 2), _coordinate(text[split:], 3)


def tzdata_zones(zoneinfo=ZONEINFO):
    """[(zone, country, latitude, longitude)] from tzdata's zone1970.tab
    (a zone shared by several countries is listed for the first), with
    the country names of iso3166.tab. [] when the files are absent."""
    try:
        with open(os.path.join(zoneinfo, "iso3166.tab"), encoding="utf-8") as stream:
            countries = dict(line.rstrip("\n").split("\t", 1) for line in stream
                             if line.strip() and not line.startswith("#"))
        with open(os.path.join(zoneinfo, "zone1970.tab"), encoding="utf-8") as stream:
            rows = [line.rstrip("\n").split("\t") for line in stream
                    if line.strip() and not line.startswith("#")]
    except (OSError, ValueError):
        return []
    zones = []
    for row in rows:
        if len(row) < 3:
            continue
        codes, coordinates, zone = row[0], row[1], row[2]
        code = codes.split(",")[0]
        try:
            lat, lon = parse_coordinates(coordinates)
        except (ValueError, IndexError):
            continue
        zones.append((zone, countries.get(code, code), lat, lon))
    return zones


def city_name(zone):
    """The city of an IANA name: its last part, with spaces."""
    return zone.rsplit("/", 1)[-1].replace("_", " ")


def tzdata_regions(zones):
    """region -> country -> city -> zone, from tzdata_zones()."""
    regions = {}
    for zone, country, _lat, _lon in zones:
        region = zone.split("/", 1)[0]
        regions.setdefault(region, {}).setdefault(country, {})[city_name(zone)] = zone
    return regions


class Guess:
    """The zone nearest to a GeoIP answer, in the shape of a GWeather
    city: the time zone step reads these three methods."""

    def __init__(self, zone, country):
        self._zone, self._country = zone, country

    def get_city_name(self):
        return city_name(self._zone)

    def get_country_name(self):
        return self._country

    def get_timezone_str(self):
        return self._zone


def nearest_zone(zones, lat, lon):
    """The Guess for the zone whose tzdata point is nearest to (lat, lon),
    or None when there is no zone."""
    def distance(row):
        _zone, _country, zlat, zlon = row
        p1, p2 = math.radians(lat), math.radians(zlat)
        dlon = math.radians(zlon - lon)
        # The central angle: enough to order the points.
        return math.acos(max(-1.0, min(1.0, math.sin(p1) * math.sin(p2)
                                       + math.cos(p1) * math.cos(p2) * math.cos(dlon))))
    if not zones:
        return None
    zone, country, _lat, _lon = min(zones, key=distance)
    return Guess(zone, country)


TZDATA_ZONES = tzdata_zones()
regions = _gweather_regions() if GWeather is not None else {}
if not regions:
    regions = tzdata_regions(TZDATA_ZONES)

all_timezones = dict(sorted(regions.items()))


# HTTPS, and free without a key. This was http://ip-api.com, which sends
# the user's location in clear text (#184). ip-api.com's free tier does not
# serve HTTPS at all ("SSL unavailable for this endpoint, order a key"), so
# the obvious one-letter fix would have turned auto-detection off. Fedora's
# GeoIP service is what Anaconda uses for the same purpose.
GEOIP_URL = "https://geoip.fedoraproject.org/city"


def parse_geoip(payload) -> tuple[float, float] | None:
    """(latitude, longitude) from a GeoIP response, or None if unusable.

    The response comes from the network, so only two finite numbers in
    range are taken from it. Anything else means no auto-detection, never
    an exception and never a wrong guess.
    """
    if not isinstance(payload, dict):
        return None
    try:
        lat = float(payload["latitude"])
        lon = float(payload["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None  # also rejects NaN, which fails every comparison
    return lat, lon


def _fetch_geoip():
    """The GeoIP answer (JSON) over HTTPS, in 3 seconds at most."""
    if requests is not None:
        return requests.get(GEOIP_URL, timeout=3).json()
    with urllib.request.urlopen(GEOIP_URL, timeout=3) as response:  # noqa: S310 - fixed https URL
        return json.loads(response.read(65536).decode("utf-8"))


def get_location(callback=None):
    logger.info("Trying to retrieve timezone automatically")
    try:
        coords = parse_geoip(_fetch_geoip())
        if coords is None:
            raise ValueError("GeoIP response had no usable coordinates")
        if GWeather is not None:
            nearest = GWeather.Location.get_world().find_nearest_city(*coords)
        else:
            nearest = nearest_zone(TZDATA_ZONES, *coords)
    except Exception as e:
        logger.error(f"Failed to retrieve timezone: {e}")
        nearest = None

    logger.info("Done retrieving timezone")

    if callback:
        logger.info("Running callback")
        GLib.idle_add(callback, nearest)


tz_preview_cache: dict[str, tuple[str, str]] = {}


def get_timezone_preview(tzname):
    if tzname in tz_preview_cache:
        return tz_preview_cache[tzname]
    else:
        timezone = ZoneInfo(tzname)
        now = datetime.datetime.now(timezone)
        now_str = (
            "%02d:%02d" % (now.hour, now.minute),
            now.strftime("%A, %d %B %Y"),
        )
        tz_preview_cache[tzname] = now_str
        return now_str
