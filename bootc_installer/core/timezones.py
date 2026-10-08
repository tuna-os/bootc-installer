import datetime
import logging

import requests
from gi.repository import GLib, GWeather
from zoneinfo import ZoneInfo

logger = logging.getLogger("BootcInstaller::Timezones")

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


def get_location(callback=None):
    logger.info("Trying to retrieve timezone automatically")
    try:
        coords = parse_geoip(requests.get(GEOIP_URL, timeout=3).json())
        if coords is None:
            raise ValueError("GeoIP response had no usable coordinates")
        nearest = world.find_nearest_city(*coords)
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
