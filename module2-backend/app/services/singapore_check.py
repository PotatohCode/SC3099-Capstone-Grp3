"""
Singapore-only check-ins (graded - course clarification email):

    "Check-ins must be rejected (HTTP 403, or created with status
    "rejected") when the client IP is a public IP outside Singapore, or the
    GPS coordinates are outside Singapore. ... private/local addresses
    (e.g., 192.168.x.x, 10.x.x.x, 127.x.x.x) may be treated as on-campus
    and allowed."

IP -> country uses an offline, bundled DB-IP "IP to Country Lite" database
(app/data/dbip-country-lite.mmdb, read with `maxminddb`) so the check never
depends on an external HTTP API during grading.

    IP geolocation by DB-IP (https://db-ip.com), licensed under CC BY 4.0.

Team decisions (UPDATE-TRACKER.md, item B):
- A public IP the database can't place is ALLOWED - the rule rejects IPs
  shown to be *outside* Singapore, and an unknown one hasn't been. GPS is
  still checked independently.
- GPS: inside a bounding box around Singapore AND not on Malaysian or
  Indonesian land. The box alone also covered Johor Bahru (its Wikipedia
  coordinates, JB Sentral, the JB checkpoint), Pasir Gudang, Pengerang and
  Batam's north coast - measured 2026-10-23. The land inside the box comes
  from app/data/sg-neighbour-land.json (OpenStreetMap via geoBoundaries,
  ODbL; rebuilt by scripts/build_sg_neighbour_land.py). Same philosophy as
  the IP rule: reject what's shown to be foreign. Water in the straits
  counts as Singapore's side, so a GPS fix that drifts a little offshore
  from a coastal venue still passes.
"""
import ipaddress
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import maxminddb

from app.core.config import get_settings

logger = logging.getLogger("saiv.singapore_check")

SINGAPORE_ISO_CODE = "SG"
SG_LAT_MIN, SG_LAT_MAX = 1.15, 1.48
SG_LON_MIN, SG_LON_MAX = 103.59, 104.10


@lru_cache
def _reader() -> Optional[maxminddb.Reader]:
    path = get_settings().GEOIP_DB_PATH
    try:
        return maxminddb.open_database(path)
    except (OSError, ValueError, maxminddb.InvalidDatabaseError) as exc:
        # Loud, not fatal: without the DB every public IP is "unknown" and
        # therefore allowed - the GPS check still applies.
        logger.error("GeoIP database unavailable at %s (%s) - IP country check disabled", path, exc)
        return None


def _parse(ip: str) -> Optional[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    # ::ffff:a.b.c.d (IPv4 seen through a dual-stack socket) -> a.b.c.d
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def is_private_or_local(ip: str) -> bool:
    addr = _parse(ip)
    if addr is None:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified


def ip_country(ip: str) -> Optional[str]:
    """ISO country code for a public IP, or None if unknown/unavailable."""
    addr = _parse(ip)
    reader = _reader()
    if addr is None or reader is None:
        return None
    record = reader.get(str(addr))
    if not record:
        return None
    return (record.get("country") or {}).get("iso_code")


def ip_allowed(ip: Optional[str]) -> bool:
    if not ip or _parse(ip) is None:
        return True  # nothing usable to judge - leave it to the GPS check
    if is_private_or_local(ip):
        return True  # on-campus / local network, per the email
    country = ip_country(ip)
    return country is None or country == SINGAPORE_ISO_CODE


_NEIGHBOUR_LAND_PATH = Path(__file__).resolve().parents[1] / "data" / "sg-neighbour-land.json"


def _in_ring(lat: float, lon: float, ring: list) -> bool:
    """Ray casting; ring points are [lon, lat]."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_polygons(lat: float, lon: float, polygons: list) -> bool:
    """True if the point is inside any polygon ([outer ring, hole, ...])."""
    for poly in polygons:
        if _in_ring(lat, lon, poly[0]) and not any(_in_ring(lat, lon, hole) for hole in poly[1:]):
            return True
    return False


@lru_cache
def _neighbour_land() -> list:
    """[(lat_min, lat_max, lon_min, lon_max), polygon] for each polygon, so
    most polygons are skipped by their bounding box."""
    try:
        polygons = json.loads(_NEIGHBOUR_LAND_PATH.read_text(encoding="utf-8"))["polygons"]
    except (OSError, ValueError, KeyError) as exc:
        # Loud, not fatal: without the data the check falls back to the box.
        logger.error("Neighbour-land data unavailable at %s (%s) - GPS check is box-only", _NEIGHBOUR_LAND_PATH, exc)
        return []
    out = []
    for poly in polygons:
        lons = [p[0] for p in poly[0]]
        lats = [p[1] for p in poly[0]]
        out.append(((min(lats), max(lats), min(lons), max(lons)), poly))
    return out


def coords_in_singapore(lat: float, lon: float) -> bool:
    if not (SG_LAT_MIN <= lat <= SG_LAT_MAX and SG_LON_MIN <= lon <= SG_LON_MAX):
        return False
    for (la0, la1, lo0, lo1), poly in _neighbour_land():
        if la0 <= lat <= la1 and lo0 <= lon <= lo1 and point_in_polygons(lat, lon, [poly]):
            return False  # Malaysian or Indonesian land
    return True
