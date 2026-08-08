"""Geocoding engine: Nominatim with SQLite cache + positioning functions."""

import json
import math
import re
import time
import sqlite3
import logging
from datetime import datetime, timedelta

import requests
import numpy as np
from shapely.geometry import Polygon

from backend.config import (
    NOMINATIM_BASE_URL, NOMINATIM_HEADERS, NOMINATIM_MIN_INTERVAL,
    NOMINATIM_MAX_RETRIES, NOMINATIM_TIMEOUT, GEOCACHE_DB_PATH,
    GEOCACHE_TTL_DAYS, TLS_VERIFY, SETTLEMENT_KEYWORDS, COUNTRY_CODES,
    TYPE_RADIUS_MAP, DEFAULT_MODEL, get_openai_client,
)
from backend.geo_math import (
    haversine_project, make_circle, make_ellipse, parse_distance, parse_angle,
    direction_to_bearing, get_kilometers, uncertainty_for_function, calculate_bearing,
    haversine,
)

logger = logging.getLogger(__name__)

# ── SQLite Cache ──────────────────────────────────────────

def _init_cache():
    conn = sqlite3.connect(str(GEOCACHE_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geocache (
            query TEXT PRIMARY KEY,
            response TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _cache_get(query):
    try:
        conn = _init_cache()
        row = conn.execute("SELECT response, fetched_at FROM geocache WHERE query = ?",
                           (query,)).fetchone()
        conn.close()
        if row:
            fetched = datetime.fromisoformat(row[1])
            if datetime.now() - fetched < timedelta(days=GEOCACHE_TTL_DAYS):
                return json.loads(row[0])
    except Exception:
        pass
    return None


def _cache_set(query, response):
    try:
        conn = _init_cache()
        conn.execute(
            "INSERT OR REPLACE INTO geocache (query, response, fetched_at) VALUES (?, ?, ?)",
            (query, json.dumps(response), datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def llm_cache_get(key):
    """Get a cached LLM result (location context, translation, etc.)."""
    try:
        conn = _init_cache()
        row = conn.execute("SELECT value FROM llm_cache WHERE key = ?", (key,)).fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def llm_cache_set(key, value):
    """Cache an LLM result."""
    try:
        conn = _init_cache()
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Rate-limited Nominatim ────────────────────────────────

_last_request_time = 0.0


def _rate_limited_get(url):
    global _last_request_time
    for attempt in range(NOMINATIM_MAX_RETRIES):
        elapsed = time.time() - _last_request_time
        if elapsed < NOMINATIM_MIN_INTERVAL:
            time.sleep(NOMINATIM_MIN_INTERVAL - elapsed)
        _last_request_time = time.time()
        try:
            resp = requests.get(
                url,
                headers=NOMINATIM_HEADERS,
                verify=TLS_VERIFY,
                timeout=NOMINATIM_TIMEOUT,
            )
            if resp.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == NOMINATIM_MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)
    raise ValueError("Nominatim request failed after retries")


def _nominatim_search(
    query,
    country_code=None,
    auto_featuretype=True,
    viewbox=None,
    bounded=False,
    limit=5,
):
    """Search Nominatim. Returns parsed JSON or raises ValueError."""
    import urllib.parse as up

    # Check cache first
    cache_key = f"{query}|{country_code}|{auto_featuretype}|{viewbox}|{bounded}|{limit}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug("Cache hit: '%s'", query)
        return cached

    params = {
        "q": query, "polygon_geojson": "1", "accept-language": "ru,en",
        "format": "jsonv2", "addressdetails": "1", "limit": str(limit),
    }
    if country_code:
        params["countrycodes"] = country_code
    if viewbox:
        params["viewbox"] = viewbox
    if bounded:
        params["bounded"] = "1"
    if auto_featuretype:
        if any(kw in query.lower() for kw in SETTLEMENT_KEYWORDS):
            params["featuretype"] = "settlement"

    url = NOMINATIM_BASE_URL + "?" + up.urlencode(params)
    resp = _rate_limited_get(url)

    if resp.status_code != 200 or not resp.content.strip():
        raise ValueError(f"Nominatim error for '{query}'")

    data = resp.json()

    # Retry without featuretype if empty
    if not data and "featuretype" in params:
        del params["featuretype"]
        url = NOMINATIM_BASE_URL + "?" + up.urlencode(params)
        resp = _rate_limited_get(url)
        data = resp.json() if resp.status_code == 200 else []

    if not data:
        raise ValueError(f"No Nominatim results for '{query}'")

    data.sort(key=lambda x: float(x.get("importance", 0)), reverse=True)
    _cache_set(cache_key, data)
    return data


# ── LLM-assisted geocoding ────────────────────────────────

def _resolve_location_context(location):
    """Use LLM to get Cyrillic name + country code. Results cached in SQLite."""
    cache_key = f"resolve:{location}"
    cached = llm_cache_get(cache_key)
    if cached:
        logger.debug("LLM cache hit for '%s'", location)
        return tuple(cached)

    try:
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": (
                    "You are a geographic disambiguation assistant for OpenStreetMap Nominatim.\n"
                    "Given a location, provide 3 lines:\n"
                    "query: <best Nominatim search query>\n"
                    "cyrillic: <Cyrillic name or NONE>\n"
                    "country: <country name>\n\n"
                    "Example:\n  Input: Leskhoz, Tatarstan, Russia\n"
                    "  query: Лесхоз, Сабинский район, Татарстан\n"
                    "  cyrillic: Лесхоз\n  country: Russia"
                )},
                {"role": "user", "content": location},
            ],
        )
        result = resp.choices[0].message.content.strip()
        enriched, cyrillic, cc = location, None, None
        for line in result.split("\n"):
            line = line.strip()
            if line.lower().startswith("query:"):
                enriched = line.split(":", 1)[1].strip()
            elif line.lower().startswith("cyrillic:"):
                c = line.split(":", 1)[1].strip()
                if c.upper() != "NONE":
                    cyrillic = c
            elif line.lower().startswith("country:"):
                cc = COUNTRY_CODES.get(line.split(":", 1)[1].strip().lower())
        llm_cache_set(cache_key, [enriched, cyrillic, cc])
        return enriched, cyrillic, cc
    except Exception:
        return location, None, None


def _get_alternative_names(location):
    """Ask LLM for alternative search queries."""
    try:
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": (
                    "The place below was NOT found in OpenStreetMap. "
                    "Generate 5 alternative search queries (Cyrillic, transliterations, "
                    "with region context), one per line. Output ONLY the queries."
                )},
                {"role": "user", "content": location},
            ],
        )
        return [line.strip().lstrip("0123456789.-) ")
                for line in resp.choices[0].message.content.strip().split("\n")
                if line.strip()]
    except Exception:
        return []


def _get_radius_for_type(nominatim_result):
    """Determine visualization radius based on place type."""
    t = nominatim_result.get("type", "").lower()
    cat = nominatim_result.get("category", "").lower()
    imp = float(nominatim_result.get("importance", 0.5))
    if t in TYPE_RADIUS_MAP:
        return TYPE_RADIUS_MAP[t]
    if cat in TYPE_RADIUS_MAP:
        return TYPE_RADIUS_MAP[cat]
    if imp < 0.2: return 0.5
    if imp < 0.4: return 1.0
    if imp < 0.6: return 2.0
    if imp < 0.8: return 3.0
    return 5.0


def _extract_coords(data, location):
    """Extract coordinates + centroid + radius_hint from Nominatim result."""
    best = data[0]
    geo_type = best.get("geojson", {}).get("type", "")
    centroid = (float(best["lon"]), float(best["lat"]))
    radius = _get_radius_for_type(best)

    if geo_type == "Point":
        return best["geojson"]["coordinates"], centroid, radius
    if geo_type == "MultiPolygon":
        coords = best["geojson"]["coordinates"][0][0]
    elif geo_type == "Polygon":
        coords = best["geojson"]["coordinates"][0]
    else:
        return [centroid[0], centroid[1]], centroid, radius

    if len(coords) >= 3:
        try:
            if Polygon(coords).area > 0.1:
                return [centroid[0], centroid[1]], centroid, radius
        except Exception:
            return [centroid[0], centroid[1]], centroid, radius
    return coords, centroid, radius


def _build_query_variants(location):
    """Build progressive Nominatim query variants for one location name."""
    enriched, cyrillic, cc = _resolve_location_context(location)

    seen, variants = set(), []

    def add(q, c=None, af=True):
        k = (q, c, af)
        if k not in seen:
            seen.add(k)
            variants.append(k)

    add(enriched, cc)
    if cyrillic:
        add(cyrillic, cc)
        add(cyrillic, cc, False)
    add(location, cc)
    add(location, None)
    add(location, cc, False)
    add(location, None, False)
    parts = [p.strip() for p in location.split(",")]
    if len(parts) >= 2:
        add(", ".join(parts[:2]), cc)
        add(", ".join(parts[:2]), None, False)

    return variants, cc


def _viewbox_around(center, radius_km):
    lon, lat = center
    lat_delta = radius_km / 111.0
    lon_scale = max(0.2, math.cos(math.radians(lat)))
    lon_delta = radius_km / (111.0 * lon_scale)
    min_lon = max(-180.0, lon - lon_delta)
    max_lon = min(180.0, lon + lon_delta)
    min_lat = max(-90.0, lat - lat_delta)
    max_lat = min(90.0, lat + lat_delta)
    return f"{min_lon},{min_lat},{max_lon},{max_lat}"


def _sort_results_by_distance(data, context_centroid, max_distance_km=None):
    scored = []
    for item in data:
        try:
            center = (float(item["lon"]), float(item["lat"]))
        except (KeyError, TypeError, ValueError):
            continue
        distance = haversine(
            context_centroid[0], context_centroid[1],
            center[0], center[1],
        )
        if max_distance_km is None or distance <= max_distance_km:
            scored.append((distance, item))
    scored.sort(key=lambda pair: pair[0])
    return [item for _, item in scored]


def get_coordinates(location):
    """Geocode a location with progressive fallback. Returns (coords, centroid, radius)."""
    variants, cc = _build_query_variants(location)

    for q, c, af in variants:
        try:
            data = _nominatim_search(q, c, af)
            logger.info("Geocoded '%s' via '%s'", location, q)
            return _extract_coords(data, location)
        except ValueError:
            continue

    # LLM alternatives
    for alt in _get_alternative_names(location):
        for c in [cc, None]:
            try:
                data = _nominatim_search(alt, c, False)
                return _extract_coords(data, location)
            except ValueError:
                continue

    raise ValueError(f"Cannot geocode '{location}'")


def get_coordinates_near(location, context_centroid, radius_km=120):
    """Geocode a location constrained by a nearby already-resolved marker."""
    variants, cc = _build_query_variants(location)
    viewbox = _viewbox_around(context_centroid, radius_km)

    for q, c, af in variants:
        try:
            data = _nominatim_search(q, c, af, viewbox=viewbox, bounded=True)
            nearby = _sort_results_by_distance(data, context_centroid)
            if nearby:
                logger.info(
                    "Context geocoded '%s' via '%s' within %.0f km",
                    location, q, radius_km,
                )
                return _extract_coords(nearby, location)
        except ValueError:
            continue

    for q, c, af in variants:
        try:
            data = _nominatim_search(q, c, af)
            nearby = _sort_results_by_distance(data, context_centroid, radius_km)
            if nearby:
                logger.info(
                    "Context selected nearest '%s' via '%s' within %.0f km",
                    location, q, radius_km,
                )
                return _extract_coords(nearby, location)
        except ValueError:
            continue

    for alt in _get_alternative_names(location):
        for c in [cc, None]:
            try:
                data = _nominatim_search(alt, c, False, viewbox=viewbox, bounded=True)
                nearby = _sort_results_by_distance(data, context_centroid)
                if nearby:
                    return _extract_coords(nearby, location)
            except ValueError:
                continue

    raise ValueError(f"Cannot geocode '{location}' near context")


# ── OSRM: road snapping & routing ─────────────────────────

_OSRM_BASE = "https://router.project-osrm.org"


def snap_to_road(lon, lat):
    """Snap a point to the nearest road via OSRM. Returns (snapped_lon, snapped_lat) or original."""
    try:
        url = f"{_OSRM_BASE}/nearest/v1/driving/{lon},{lat}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("code") == "Ok" and data.get("waypoints"):
            loc = data["waypoints"][0]["location"]
            logger.debug("Snapped (%.5f,%.5f) -> (%.5f,%.5f)", lon, lat, loc[0], loc[1])
            return (loc[0], loc[1])
    except Exception as e:
        logger.warning("OSRM snap failed: %s", e)
    return (lon, lat)


def road_distance(lon1, lat1, lon2, lat2):
    """Get road distance in km between two points via OSRM. Returns (road_km, straight_km)."""
    from backend.geo_math import haversine as h_dist
    straight = h_dist(lon1, lat1, lon2, lat2)
    try:
        url = f"{_OSRM_BASE}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("code") == "Ok" and data.get("routes"):
            road_m = data["routes"][0]["distance"]
            return road_m / 1000, straight
    except Exception as e:
        logger.warning("OSRM route failed: %s", e)
    return straight, straight


def road_route(lon1, lat1, lon2, lat2):
    """Get road route geometry between two points via OSRM.
    Returns list of [lon, lat] coordinates or None."""
    try:
        url = (f"{_OSRM_BASE}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
               f"?overview=full&geometries=geojson")
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("code") == "Ok" and data.get("routes"):
            route = data["routes"][0]
            coords = route["geometry"]["coordinates"]  # [[lon,lat], ...]
            distance_km = route["distance"] / 1000
            return coords, distance_km
    except Exception as e:
        logger.warning("OSRM route geometry failed: %s", e)
    return None, None


# ── Overpass API: street geometry ──────────────────────────

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def get_street_geometry(street_name, city=None):
    """Get street geometry (list of [lon, lat] points) from Overpass API.
    Returns list of (lon, lat) tuples or raises ValueError."""

    # First geocode the city to get a bounding box for faster search
    bbox = ""
    if city:
        try:
            _, city_center, _ = get_coordinates(city)
            # ~15 km box around city center
            d = 0.15
            bbox = f"({city_center[1]-d},{city_center[0]-d},{city_center[1]+d},{city_center[0]+d})"
        except Exception:
            pass

    # Build search variants: original + LLM Cyrillic translation
    street_variants = [street_name]
    try:
        cached = llm_cache_get(f"street:{street_name}")
        if cached:
            street_variants.insert(0, cached)
        else:
            client = get_openai_client()
            resp = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": (
                        "Given a street name, return its FULL official name as it appears in OpenStreetMap, "
                        "in the local language. For Russian streets, include the word 'улица/проспект/переулок' etc.\n"
                        "Examples:\n"
                        "  Vishnevsky Street -> улица Вишневского\n"
                        "  Oxford Street -> Oxford Street\n"
                        "  Nevsky Prospect -> Невский проспект\n"
                        "Output ONLY the name."
                    )},
                    {"role": "user", "content": street_name},
                ],
            )
            local_name = resp.choices[0].message.content.strip()
            if local_name and local_name != street_name:
                street_variants.insert(0, local_name)
                llm_cache_set(f"street:{street_name}", local_name)
                logger.debug("Street variant: '%s' -> '%s'", street_name, local_name)
    except Exception:
        pass

    elements = []
    for variant in street_variants:
        for use_exact in [True, False]:
            if use_exact:
                name_filter = f'["name"="{variant}"]'
            else:
                name_filter = f'["name"~"{variant}",i]'

            if bbox:
                query = f'[out:json][timeout:25];way{name_filter}["highway"]{bbox};out geom;'
            else:
                query = f'[out:json][timeout:25];way{name_filter}["highway"];out geom 1;'

            try:
                resp = requests.post(_OVERPASS_URL, data={"data": query}, timeout=30)
                if resp.status_code == 200 and resp.content.strip():
                    result_data = resp.json()
                    elements = result_data.get("elements", [])
                    if elements:
                        logger.info("Found street '%s' via '%s' (exact=%s)", street_name, variant, use_exact)
                        break
            except Exception:
                continue
        if elements:
            break

    if not elements:
        raise ValueError(f"Street '{street_name}' not found in Overpass")

    # Merge all segments into one line
    points = []
    for el in elements:
        if "geometry" in el:
            for pt in el["geometry"]:
                points.append((pt["lon"], pt["lat"]))

    if not points:
        raise ValueError(f"No geometry for street '{street_name}'")

    logger.info("Street '%s': %d points from %d segments", street_name, len(points), len(elements))
    return points


def intersect_street_direction(street_points, landmark_centroid, from_centroid=None):
    """Find the point on street closest to the direction toward a landmark.

    If from_centroid is given, finds the point on the street where you would
    'turn towards' the landmark while traveling from from_centroid.

    Returns (lon, lat) of the best intersection point.
    """
    from backend.geo_math import haversine, calculate_bearing

    if not street_points:
        raise ValueError("No street points")

    if from_centroid:
        # Find the point on the street where the bearing to landmark
        # is most perpendicular to the street direction (= turning point)
        best_point = None
        best_score = float('inf')

        for i in range(len(street_points) - 1):
            p = street_points[i]
            p_next = street_points[i + 1]

            # Street direction at this point
            street_bearing = calculate_bearing(p, p_next)
            # Bearing from this point to landmark
            landmark_bearing = calculate_bearing(p, landmark_centroid)

            # Angle difference — looking for ~90° (perpendicular = turning point)
            diff = abs(street_bearing - landmark_bearing) % 360
            if diff > 180:
                diff = 360 - diff
            turn_score = abs(diff - 90)

            # Also factor in distance from the 'from' point
            # (should be between from and landmark, not behind)
            dist_from = haversine(from_centroid[0], from_centroid[1], p[0], p[1])

            score = turn_score + dist_from * 0.01  # slight preference for closer points

            if score < best_score:
                best_score = score
                best_point = p

        return best_point or street_points[len(street_points) // 2]

    else:
        # Simple: find closest point on street to landmark
        best_point = None
        best_dist = float('inf')
        for p in street_points:
            d = haversine(p[0], p[1], landmark_centroid[0], landmark_centroid[1])
            if d < best_dist:
                best_dist = d
                best_point = p
        return best_point or street_points[0]


# ── Qualifier scale factors for Near ─────────────────────

_NEAR_QUALIFIERS = {
    "adjacent": 1.5,    # рядом, у, возле, при
    "close": 3.0,       # недалеко, близко, неподалёку
    "vicinity": 5.0,    # в окрестностях, в районе
    "region": 10.0,     # в регионе, в области
}


# ── Positioning functions ─────────────────────────────────

def near(location, qualifier="close"):
    """Locate a place and return an uncertainty zone scaled by object type and qualifier.

    Unlike Locate (returns the object itself), Near returns a larger zone
    representing the vagueness of 'near', 'nearby', 'in the vicinity', etc.
    The zone radius adapts to the type of object (building vs city).

    Args:
        location: place name string
        qualifier: 'adjacent' | 'close' | 'vicinity' | 'region'

    Returns (circle_coords, centroid).
    """
    coords, centroid, type_radius = get_coordinates(location)
    scale = _NEAR_QUALIFIERS.get(qualifier, 3.0)
    near_radius = type_radius * scale
    logger.info("Near '%s' (qualifier=%s): type_radius=%.1f × %.1f = %.1f km",
                location, qualifier, type_radius, scale, near_radius)
    return make_circle(centroid, radius_km=near_radius)


def inside(location):
    """Return the actual polygon boundary of a place.

    Unlike Locate (which may simplify large polygons to circles),
    Inside always returns the full polygon from Nominatim.
    Used for 'within city limits', 'inside the park', etc.

    Returns (polygon_coords, centroid).
    """
    enriched, cyrillic, cc = _resolve_location_context(location)

    # Build query variants (same as get_coordinates)
    seen, variants = set(), []
    def add(q, c=None, af=True):
        k = (q, c, af)
        if k not in seen:
            seen.add(k); variants.append(k)

    add(enriched, cc)
    if cyrillic:
        add(cyrillic, cc); add(cyrillic, cc, False)
    add(location, cc); add(location, None)

    for q, c, af in variants:
        try:
            data = _nominatim_search(q, c, af)
            best = data[0]
            geo_type = best.get("geojson", {}).get("type", "")
            centroid = (float(best["lon"]), float(best["lat"]))

            # Extract polygon — keep it even if large
            if geo_type == "MultiPolygon":
                coords = best["geojson"]["coordinates"][0][0]
            elif geo_type == "Polygon":
                coords = best["geojson"]["coordinates"][0]
            else:
                # No polygon — fall back to circle with type-based radius
                radius = _get_radius_for_type(best)
                return make_circle(centroid, radius_km=radius)

            if len(coords) >= 3:
                logger.info("Inside '%s': polygon with %d points", location, len(coords))
                return coords, centroid

            radius = _get_radius_for_type(best)
            return make_circle(centroid, radius_km=radius)
        except ValueError:
            continue

    raise ValueError(f"Cannot geocode '{location}' for Inside")


def relative(centroid, direction, distance_str, uncertainty=False):
    """Move from centroid in direction by distance. Returns (shape, new_center)."""
    kms = parse_distance(distance_str)
    bearing = direction_to_bearing(direction)
    if bearing is not None:
        new_center = haversine_project(centroid[0], centroid[1], bearing, kms)
        if uncertainty:
            sa, sc, _ = uncertainty_for_function("Relative", kms, direction)
            return make_ellipse(new_center, sa, sc, bearing)
        return make_circle(new_center, radius_km=max(1, kms * 0.1))
    raise ValueError(f"Unknown direction: {direction}")


def azimuth(centroid, angle, distance_str, uncertainty=False):
    """Move from centroid at specific bearing. Returns (shape, new_center)."""
    kms = parse_distance(distance_str)
    bearing = parse_angle(angle)
    new_center = haversine_project(centroid[0], centroid[1], bearing, kms)
    if uncertainty:
        sa, sc, _ = uncertainty_for_function("Azimuth", kms)
        return make_ellipse(new_center, sa, sc, bearing)
    return make_circle(new_center, radius_km=max(1, kms * 0.1))


def between(center1, center2, uncertainty=False):
    """Midpoint between two centroids. Returns (shape, midpoint)."""
    return fraction(center1, center2, 0.5, uncertainty)


def fraction(center1, center2, ratio, uncertainty=False):
    """Point at fractional position between two centroids."""
    frac = (
        center1[0] + (center2[0] - center1[0]) * float(ratio),
        center1[1] + (center2[1] - center1[1]) * float(ratio),
    )
    if uncertainty:
        bearing = calculate_bearing(center1, center2)
        sa, sc, _ = uncertainty_for_function("Between")
        return make_ellipse(frac, sa, sc, bearing)
    return make_circle(frac, radius_km=2)


def intersection(street1_name, street2_name, city=None):
    """Find the intersection point of two streets.

    Queries Overpass for both streets, then finds the closest pair of points.
    Returns (circle, center_point).
    """
    pts1 = get_street_geometry(street1_name, city)
    pts2 = get_street_geometry(street2_name, city)

    from backend.geo_math import haversine
    best_point = None
    best_dist = float('inf')

    for p1 in pts1:
        for p2 in pts2:
            d = haversine(p1[0], p1[1], p2[0], p2[1])
            if d < best_dist:
                best_dist = d
                best_point = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)

    if best_point is None:
        raise ValueError(f"Cannot find intersection of '{street1_name}' and '{street2_name}'")

    logger.info("Intersection: '%s' x '%s' -> (%.5f, %.5f), dist=%.3f km",
                street1_name, street2_name, best_point[0], best_point[1], best_dist)

    return make_circle(best_point, radius_km=0.2)


def along(from_centroid, toward_centroid, distance_str, uncertainty=False):
    """Move from from_centroid toward toward_centroid by distance ALONG the road.

    Unlike Toward (straight line), this follows the actual road geometry via OSRM.
    Falls back to straight-line projection if OSRM fails.
    Returns (shape, new_center).
    """
    kms = parse_distance(distance_str)

    # Try OSRM route
    route_coords, total_km = road_route(
        from_centroid[0], from_centroid[1],
        toward_centroid[0], toward_centroid[1],
    )

    if route_coords and total_km and total_km > 0:
        # Walk along route geometry for the requested distance
        from backend.geo_math import haversine
        walked = 0.0
        new_center = (route_coords[0][0], route_coords[0][1])

        for i in range(1, len(route_coords)):
            p_prev = route_coords[i - 1]
            p_curr = route_coords[i]
            seg_km = haversine(p_prev[0], p_prev[1], p_curr[0], p_curr[1])

            if walked + seg_km >= kms:
                # Interpolate within this segment
                remaining = kms - walked
                ratio = remaining / seg_km if seg_km > 0 else 0
                new_center = (
                    p_prev[0] + (p_curr[0] - p_prev[0]) * ratio,
                    p_prev[1] + (p_curr[1] - p_prev[1]) * ratio,
                )
                break
            walked += seg_km
            new_center = (p_curr[0], p_curr[1])

        logger.info("Along (road): %.1f km along route (total %.1f km) -> (%.5f, %.5f)",
                     kms, total_km, new_center[0], new_center[1])

        if uncertainty:
            bearing_val = calculate_bearing(from_centroid, toward_centroid)
            sa, sc, _ = uncertainty_for_function("Along", kms)
            return make_ellipse(new_center, sa, sc, bearing_val)
        return make_circle(new_center, radius_km=max(0.5, kms * 0.05))

    # Fallback: straight-line projection (same as Toward)
    logger.warning("Along: OSRM failed, falling back to straight-line projection")
    bearing_val = calculate_bearing(from_centroid, toward_centroid)
    new_center = haversine_project(from_centroid[0], from_centroid[1], bearing_val, kms)
    if uncertainty:
        sa, sc, _ = uncertainty_for_function("Along", kms)
        return make_ellipse(new_center, sa, sc, bearing_val)
    return make_circle(new_center, radius_km=max(0.5, kms * 0.05))


def toward(from_centroid, toward_centroid, distance_str, uncertainty=False):
    """Move from from_centroid toward toward_centroid by distance.

    Unlike Relative (fixed cardinal direction), the bearing is computed
    dynamically from the source point to the target point.

    Returns (shape, new_center).
    """
    kms = parse_distance(distance_str)
    bearing = calculate_bearing(from_centroid, toward_centroid)
    new_center = haversine_project(from_centroid[0], from_centroid[1], bearing, kms)
    if uncertainty:
        sa, sc, _ = uncertainty_for_function("Toward", kms)
        return make_ellipse(new_center, sa, sc, bearing)
    return make_circle(new_center, radius_km=max(1, kms * 0.1))


def street_turn(street_name, toward_place, from_place=None, city=None):
    """Find the point on a street where you turn toward a landmark.

    Args:
        street_name: name of the street to follow
        toward_place: place name you turn towards
        from_place: optional starting direction (place you come from)
        city: city context for Overpass search

    Returns (circle, center_point)
    """
    # Get street geometry
    street_pts = get_street_geometry(street_name, city)

    # Geocode landmark
    _, toward_centroid, _ = get_coordinates(toward_place)

    # Geocode starting direction if given
    from_centroid = None
    if from_place:
        _, from_centroid, _ = get_coordinates(from_place)

    # Find intersection point
    point = intersect_street_direction(street_pts, toward_centroid, from_centroid)

    logger.info("StreetTurn: on '%s' toward '%s' -> (%.5f, %.5f)",
                street_name, toward_place, point[0], point[1])

    return make_circle(point, radius_km=0.3)


# ── Step executor ─────────────────────────────────────────

def _try_parse_step_ref(value, data):
    """Try interpreting a string as step reference ('RelativeResult1' -> step 1)."""
    if not isinstance(value, str):
        return None
    digits = re.findall(r"\d+", value)
    if not digits:
        return None
    patterns = [r"(?i)result", r"(?i)step", r"(?i)output", r"^#\d+$", r"^\d+$"]
    if any(re.search(p, value) for p in patterns):
        sid = int(digits[0])
        if sid in data:
            return sid
    return None


def resolve_pair_centroids(loc1, loc2, max_pair_distance_km=250, context_radius_km=120):
    """Resolve two locations, using either one as context if the pair looks mismatched."""
    c1 = _to_centroid(loc1)
    c2 = _to_centroid(loc2)

    try:
        base_distance = haversine(c1[0], c1[1], c2[0], c2[1])
    except Exception:
        return c1, c2

    if base_distance <= max_pair_distance_km:
        return c1, c2

    best_distance, best_c1, best_c2 = base_distance, c1, c2

    if isinstance(loc1, str):
        try:
            _, local_c1, _ = get_coordinates_near(loc1, c2, radius_km=context_radius_km)
            distance = haversine(local_c1[0], local_c1[1], c2[0], c2[1])
            if distance < best_distance:
                best_distance, best_c1, best_c2 = distance, local_c1, c2
        except Exception:
            pass

    if isinstance(loc2, str):
        try:
            _, local_c2, _ = get_coordinates_near(loc2, c1, radius_km=context_radius_km)
            distance = haversine(c1[0], c1[1], local_c2[0], local_c2[1])
            if distance < best_distance:
                best_distance, best_c1, best_c2 = distance, c1, local_c2
        except Exception:
            pass

    if best_distance < base_distance:
        logger.info(
            "Context adjusted pair distance %.1f km -> %.1f km for '%s' / '%s'",
            base_distance, best_distance, loc1, loc2,
        )

    return best_c1, best_c2


def execute_steps(steps, uncertainty=False):
    """Execute a chain of positioning steps. Returns {step_id: (coords, centroid)}."""
    data = {}

    for step in steps:
        sid = step["id"]
        func = step["function"]
        inputs = step.get("inputs", [])

        # Resolve references
        resolved = []
        for inp in inputs:
            if isinstance(inp, int) and inp in data:
                resolved.append(data[inp])
            elif isinstance(inp, int):
                resolved.append(inp)  # literal int (e.g. angle)
            else:
                ref = _try_parse_step_ref(inp, data)
                resolved.append(data[ref] if ref else inp)

        if func == "Near":
            place = resolved[0] if len(resolved) > 0 else ""
            qualifier = resolved[1] if len(resolved) > 1 and isinstance(resolved[1], str) else "close"
            data[sid] = near(place, qualifier)

        elif func == "Inside":
            place = resolved[0] if len(resolved) > 0 else ""
            data[sid] = inside(place)

        elif func == "Locate" or func == "Location":
            place = resolved[0]
            if isinstance(place, str):
                coords, centroid, radius = get_coordinates(place)
                too_small = not isinstance(coords, list) or len(coords) < 3
                if not too_small:
                    try:
                        too_small = Polygon(coords).area < 0.00001
                    except Exception:
                        too_small = True
                if too_small:
                    coords, centroid = make_circle(centroid, radius_km=radius)
                data[sid] = (coords, centroid)
            else:
                data[sid] = place

        elif func == "Relative":
            loc, direction, distance = resolved
            centroid = _to_centroid(loc)
            data[sid] = relative(centroid, direction, str(distance), uncertainty=uncertainty)

        elif func == "Between":
            loc1, loc2 = resolved
            c1, c2 = resolve_pair_centroids(loc1, loc2)
            data[sid] = between(c1, c2, uncertainty=uncertainty)

        elif func == "Fraction":
            loc1, loc2, ratio = resolved
            c1, c2 = resolve_pair_centroids(loc1, loc2)
            data[sid] = fraction(c1, c2, ratio, uncertainty=uncertainty)

        elif func == "Azimuth":
            loc, angle, distance = resolved
            centroid = _to_centroid(loc)
            data[sid] = azimuth(centroid, angle, str(distance), uncertainty=uncertainty)

        elif func == "Toward":
            from_loc, toward_loc, distance = resolved
            c_from, c_toward = resolve_pair_centroids(from_loc, toward_loc)
            data[sid] = toward(c_from, c_toward, str(distance), uncertainty=uncertainty)

        elif func == "Along":
            from_loc, toward_loc, distance = resolved
            c_from, c_toward = resolve_pair_centroids(from_loc, toward_loc)
            data[sid] = along(c_from, c_toward, str(distance), uncertainty=uncertainty)

        elif func == "Intersection":
            street1 = resolved[0] if len(resolved) > 0 else ""
            street2 = resolved[1] if len(resolved) > 1 else ""
            city_ctx = resolved[2] if len(resolved) > 2 and isinstance(resolved[2], str) else None
            data[sid] = intersection(street1, street2, city_ctx)

        elif func == "StreetTurn":
            # StreetTurn(street, toward_place, from_place, city)
            # from_place and city are optional
            street = resolved[0] if len(resolved) > 0 else ""
            toward_p = resolved[1] if len(resolved) > 1 else ""
            from_p = resolved[2] if len(resolved) > 2 and isinstance(resolved[2], str) else None
            city = resolved[3] if len(resolved) > 3 and isinstance(resolved[3], str) else None
            data[sid] = street_turn(street, toward_p, from_p, city)

        else:
            raise ValueError(f"Unknown function: {func}")

    return data


def _to_centroid(loc):
    """Extract centroid from various location formats."""
    if isinstance(loc, str):
        _, centroid, _ = get_coordinates(loc)
        return centroid
    if isinstance(loc, (tuple, list)):
        if len(loc) == 2 and isinstance(loc[0], (int, float)):
            return tuple(loc)  # already a (lon, lat) pair
        if len(loc) >= 2:
            return tuple(loc[1]) if isinstance(loc[1], (tuple, list)) else loc[1]
    return loc


def make_geojson(steps_data, parsed_steps=None):
    """Convert step results to a GeoJSON FeatureCollection."""
    features = []
    step_info = {
        s.get("id"): s
        for s in (parsed_steps or [])
        if isinstance(s, dict) and "id" in s
    }

    for sid in sorted(steps_data.keys()):
        coords, centroid = steps_data[sid]
        is_final = sid == max(steps_data.keys())
        step = step_info.get(sid, {})
        func = step.get("function", "?")
        inputs = step.get("inputs", [])

        latlngs = []
        if isinstance(coords, list) and len(coords) >= 3:
            for p in coords:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    latlngs.append([float(p[0]), float(p[1])])
            if latlngs:
                # Close polygon ring if not already closed
                if latlngs[0] != latlngs[-1]:
                    latlngs.append(latlngs[0])

        if latlngs:
            geometry = {
                "type": "Polygon",
                "coordinates": [latlngs],
            }
        else:
            geometry = {
                "type": "Point",
                "coordinates": [float(centroid[0]), float(centroid[1])],
            }

        features.append({
            "type": "Feature",
            "properties": {
                "step_id": sid,
                "function": func,
                "inputs": [str(i) if not isinstance(i, (int, float)) else i for i in inputs],
                "centroid": [float(centroid[0]), float(centroid[1])],
                "is_final": is_final,
            },
            "geometry": geometry,
        })

    return {"type": "FeatureCollection", "features": features}
