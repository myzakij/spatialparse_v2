"""Pure geospatial math — no external API calls, no state."""

import math
import re
import numpy as np
import quantities as pq

from backend.config import DIRECTION_BEARINGS


def get_kilometers(d, unit):
    """Convert distance value + unit string to kilometers."""
    q = float(d) * pq.CompoundUnit(unit)
    q.units = pq.km
    return q.magnitude


def parse_distance(dist_str):
    """Parse '5 km' -> km value."""
    dist_str = str(dist_str)
    digits = re.findall(r'[\d.]+', dist_str)
    units = re.findall(r'[a-zA-Zа-яА-ЯёЁ]+', dist_str)
    if digits and units:
        unit = units[0].lower()
        unit_aliases = {
            "км": "km",
            "километр": "km",
            "километра": "km",
            "километров": "km",
            "м": "m",
            "метр": "m",
            "метра": "m",
            "метров": "m",
            "ми": "mile",
            "миля": "mile",
            "мили": "mile",
            "миль": "mile",
            "фут": "ft",
            "фута": "ft",
            "футов": "ft",
        }
        return get_kilometers(digits[0], unit_aliases.get(unit, unit))
    elif digits:
        return float(digits[0])
    return 1.0


def parse_angle(angle_val):
    """Parse angle: int, float, or string like '120°' -> float degrees."""
    s = re.sub(r'[^0-9.\-]', '', str(angle_val))
    return float(s) if s else 0.0


def haversine(lon1, lat1, lon2, lat2):
    """Distance in km between two (lon, lat) points."""
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def calculate_bearing(pointA, pointB):
    """Compass bearing from pointA to pointB. Points are (lon, lat)."""
    if not isinstance(pointA, (tuple, list)) or not isinstance(pointB, (tuple, list)):
        return 400
    if len(pointA) < 2 or len(pointB) < 2:
        return 400
    lat1 = math.radians(pointA[1])
    lat2 = math.radians(pointB[1])
    dlon = math.radians(pointB[0] - pointA[0])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def haversine_project(lon, lat, bearing_deg, dist_km):
    """Project a point at exact bearing/distance. Returns (new_lon, new_lat)."""
    R = 6378.1
    brng = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(dist_km / R) +
                     math.cos(lat1) * math.sin(dist_km / R) * math.cos(brng))
    lon2 = lon1 + math.atan2(math.sin(brng) * math.sin(dist_km / R) * math.cos(lat1),
                             math.cos(dist_km / R) - math.sin(lat1) * math.sin(lat2))
    return (math.degrees(lon2), math.degrees(lat2))


def make_circle(center, radius_km=1, n_points=100):
    """Generate a circle polygon using Haversine projection.

    Each point is projected at exact distance from center at 360 bearings.
    Produces a true circle on the Earth's surface at any latitude.
    """
    circle = []
    for bearing in np.linspace(0, 360, num=n_points, endpoint=False):
        lon, lat = haversine_project(center[0], center[1], float(bearing), radius_km)
        circle.append((float(lon), float(lat)))
    # Close the polygon
    circle.append(circle[0])
    return circle, center


def make_circle_at_offset(center, kms, direction, radius_km=1):
    """Create a circle offset by kms in direction from center."""
    if direction and kms > 0:
        bearing = DIRECTION_BEARINGS.get(direction.lower())
        if bearing is not None:
            new_center = haversine_project(center[0], center[1], bearing, kms)
            return make_circle(new_center, radius_km)
    return make_circle(center, radius_km)


def direction_to_bearing(direction_str):
    """Convert direction string to bearing degrees. Returns None if unknown."""
    return DIRECTION_BEARINGS.get(direction_str.lower().strip()) if direction_str else None


# ── Uncertainty ellipse ──────────────────────────────────

def make_ellipse(center, semi_along, semi_across, bearing_deg, n_points=100):
    """Generate an ellipse polygon using Haversine projection.

    Each point is computed by varying the distance from center
    according to the ellipse equation, then projected at exact bearing.
    Accurate at any latitude.

    Args:
        center: (lon, lat)
        semi_along: semi-axis along the bearing direction (km)
        semi_across: semi-axis perpendicular to bearing (km)
        bearing_deg: orientation of the long axis (degrees from north)

    Returns:
        (points_list, center)
    """
    bearing_rad = np.radians(bearing_deg)
    points = []

    for theta in np.linspace(0, 2 * np.pi, num=n_points, endpoint=False):
        # Ellipse in local frame
        local_x = semi_across * np.cos(theta)  # perpendicular to bearing
        local_y = semi_along * np.sin(theta)    # along bearing

        # Rotate to get displacement in North/East km
        dn_km = local_x * np.cos(bearing_rad) - local_y * np.sin(bearing_rad)
        de_km = local_x * np.sin(bearing_rad) + local_y * np.cos(bearing_rad)

        # Distance and bearing from center to this point
        dist_km = math.sqrt(dn_km ** 2 + de_km ** 2)
        if dist_km < 0.001:
            points.append((float(center[0]), float(center[1])))
            continue
        point_bearing = math.degrees(math.atan2(de_km, dn_km)) % 360

        lon, lat = haversine_project(center[0], center[1], point_bearing, dist_km)
        points.append((float(lon), float(lat)))

    points.append(points[0])  # close polygon
    return points, center


def uncertainty_for_function(func, distance_km=None, direction=None):
    """Compute ellipse semi-axes based on the type of spatial expression.

    Returns:
        (semi_along, semi_across, bearing_deg) — parameters for make_ellipse
    """
    if func == "Relative":
        # Direction is fuzzy (±15°), distance is moderately precise (±10%)
        d = distance_km or 5
        semi_along = max(0.3, d * 0.10)    # ±10% along direction
        semi_across = max(0.5, d * 0.25)   # ±25% across (direction uncertainty)
        bearing = direction_to_bearing(direction) if direction else 0
        return semi_along, semi_across, bearing or 0

    elif func == "Azimuth":
        # Bearing is precise, distance moderately precise
        d = distance_km or 5
        semi_along = max(0.3, d * 0.08)    # ±8% along bearing
        semi_across = max(0.3, d * 0.08)   # nearly circular (bearing is exact)
        return semi_along, semi_across, 0

    elif func == "Along":
        # Along a road — less cross-track error than Toward (constrained to road)
        d = distance_km or 5
        semi_along = max(0.3, d * 0.08)    # ±8% along road
        semi_across = max(0.2, d * 0.05)   # ±5% across (road constrains)
        return semi_along, semi_across, 0

    elif func == "Intersection":
        # Street intersection — very precise
        return 0.15, 0.15, 0

    elif func == "Near":
        # Near — uncertainty IS the result (circle represents vagueness)
        return 1.0, 1.0, 0

    elif func == "Inside":
        # Inside — polygon is the result
        return 1.0, 1.0, 0

    elif func == "Toward":
        # Similar to Relative but bearing is computed, not named
        # Slightly less uncertain across (bearing is exact)
        d = distance_km or 5
        semi_along = max(0.3, d * 0.10)    # ±10% along direction
        semi_across = max(0.3, d * 0.15)   # ±15% across (less than Relative)
        return semi_along, semi_across, 0

    elif func in ("Between", "Fraction"):
        # Uncertainty elongated along the line between two points
        semi_along = 2.0   # along the A→B line
        semi_across = 1.0  # across
        return semi_along, semi_across, 0

    elif func in ("Locate", "Location"):
        # Place lookup — roughly circular
        return 1.0, 1.0, 0

    # Default
    return 1.0, 1.0, 0
