"""
Geofence distance + effective-venue resolution (Task 2.5).

"Effective" venue/radius = session override, falling back to the course
default - the same fallback pattern already used in DATABASE-SCHEMA.md for
venue_latitude/venue_longitude/geofence_radius_meters on both tables.
"""
from typing import Optional, Tuple

from geopy.distance import geodesic

from app.db.models.course import Course
from app.db.models.session import ClassSession


def effective_venue(session: ClassSession, course: Course) -> Tuple[Optional[float], Optional[float], float]:
    """Returns (latitude, longitude, radius_meters). Radius always has a
    value (course.geofence_radius_meters defaults to 100.0 at the DB
    level); lat/lon can both be None if neither session nor course ever
    set a venue - callers must handle that (no geofence to check)."""
    lat = session.venue_latitude if session.venue_latitude is not None else course.venue_latitude
    lon = session.venue_longitude if session.venue_longitude is not None else course.venue_longitude
    radius = (
        session.geofence_radius_meters
        if session.geofence_radius_meters is not None
        else course.geofence_radius_meters
    )
    return lat, lon, radius


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine (geodesic) distance in meters between two coordinates."""
    return geodesic((lat1, lon1), (lat2, lon2)).meters
