"""Centralized configuration for SpatialParse."""

import os
import logging
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- API ---
API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

if not API_KEY:
    logger.warning("OPENROUTER_API_KEY not set. LLM functions will be unavailable.")

# --- Nominatim ---
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org/search.php"
NOMINATIM_HEADERS = {"User-Agent": "SpatialParse/2.0"}
NOMINATIM_MIN_INTERVAL = 1.1  # seconds between requests
NOMINATIM_MAX_RETRIES = 3
NOMINATIM_TIMEOUT = 15
TLS_VERIFY = os.getenv("SPATIALPARSE_TLS_VERIFY", "true").strip().lower() not in {
    "0", "false", "no", "off",
}

# --- Cache ---
GEOCACHE_DB_PATH = PROJECT_ROOT / "geocache.db"
GEOCACHE_TTL_DAYS = 30

# --- Directions ---
DIRECTION_BEARINGS = {
    "north": 0, "south": 180, "east": 90, "west": 270,
    "northeast": 45, "northwest": 315, "southeast": 135, "southwest": 225,
    "north east": 45, "north west": 315, "south east": 135, "south west": 225,
    "north-east": 45, "north-west": 315, "south-east": 135, "south-west": 225,
}

# --- Country codes ---
COUNTRY_CODES = {
    "russia": "ru", "china": "cn", "usa": "us", "united states": "us",
    "united kingdom": "gb", "uk": "gb", "france": "fr", "germany": "de",
    "italy": "it", "spain": "es", "japan": "jp", "south korea": "kr",
    "india": "in", "brazil": "br", "canada": "ca", "australia": "au",
    "turkey": "tr", "mexico": "mx", "indonesia": "id", "netherlands": "nl",
    "saudi arabia": "sa", "switzerland": "ch", "argentina": "ar",
    "poland": "pl", "sweden": "se", "belgium": "be", "austria": "at",
    "norway": "no", "denmark": "dk", "finland": "fi", "portugal": "pt",
    "czech republic": "cz", "czechia": "cz", "greece": "gr",
    "israel": "il", "egypt": "eg", "thailand": "th", "vietnam": "vn",
    "ukraine": "ua", "kazakhstan": "kz", "uzbekistan": "uz",
    "iran": "ir", "iraq": "iq", "pakistan": "pk", "bangladesh": "bd",
    "malaysia": "my", "singapore": "sg", "philippines": "ph",
    "new zealand": "nz", "ireland": "ie", "romania": "ro",
    "hungary": "hu", "colombia": "co", "chile": "cl", "peru": "pe",
}

# --- Adaptive radius by Nominatim type ---
TYPE_RADIUS_MAP = {
    "building": 0.2, "hotel": 0.3, "restaurant": 0.2, "shop": 0.2,
    "amenity": 0.3, "tourism": 0.3, "house": 0.15, "apartments": 0.2,
    "station": 0.5, "bus_stop": 0.2, "railway": 0.5,
    "neighbourhood": 1.0, "quarter": 1.5, "suburb": 2.0,
    "village": 1.0, "hamlet": 0.5, "town": 3.0,
    "residential": 1.5, "park": 1.0, "garden": 0.5,
    "city": 5.0, "administrative": 3.0, "county": 10.0,
    "state": 20.0, "country": 50.0,
}

SETTLEMENT_KEYWORDS = [
    "kvartal", "квартал", "microdistrict", "микрорайон", "district",
    "поселок", "посёлок", "село", "деревня", "village", "settlement",
]


def get_openai_client():
    """Create and return a configured OpenAI client."""
    from openai import OpenAI
    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set.")
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=API_KEY)
