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
- GPS uses a bounding box around Singapore. Its northern edge overlaps a
  sliver of Johor Bahru - acceptable for now, swap for a polygon if needed.
"""
import ipaddress
import logging
from functools import lru_cache
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


def coords_in_singapore(lat: float, lon: float) -> bool:
    return SG_LAT_MIN <= lat <= SG_LAT_MAX and SG_LON_MIN <= lon <= SG_LON_MAX
