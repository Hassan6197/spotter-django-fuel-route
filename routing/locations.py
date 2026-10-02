"""
Turn user input into US coordinates, spending as few network calls as possible.

Resolution order:
  1. "lat,lon" literal: no network.
  2. "City, ST" or "City, State Name": offline Census place index: no network.
  3. Anything else (street addresses, landmarks): one Nominatim call, US only.
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import requests
from django.conf import settings

from .textnorm import normalize

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}

COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

US_BOXES = (
    (24.3, 49.5, -125.1, -66.8),    # contiguous states
    (51.0, 71.6, -170.0, -129.9),   # Alaska (mainland and southeast)
    (18.8, 22.4, -160.6, -154.7),   # Hawaii
)


class LocationError(ValueError):
    """The input could not be located, or is outside the USA."""


def in_usa(lat: float, lon: float) -> bool:
    return any(a <= lat <= b and c <= lon <= d for a, b, c, d in US_BOXES)


@functools.lru_cache(maxsize=1)
def _places() -> dict:
    path = Path(settings.BASE_DIR) / "routing" / "data" / "places.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _from_place_index(text: str):
    if "," not in text:
        return None
    city, _, region = text.rpartition(",")
    region = re.sub(r"\b(usa|us|united states)\b", "", region.strip(), flags=re.I).strip(" ,")
    city = city.strip()
    if not city:
        return None
    state = region.upper() if len(region) == 2 else STATE_NAMES.get(region.lower())
    if not state:
        return None
    hit = _places().get(f"{normalize(city)}|{state}")
    return tuple(hit) if hit else None


def _nominatim(text: str):
    try:
        resp = requests.get(
            settings.NOMINATIM_URL,
            params={"q": text, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
            timeout=settings.HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise LocationError(f"Geocoding service unavailable for '{text}': {exc}") from exc
    if not data:
        raise LocationError(f"Could not find '{text}' in the USA")
    return float(data[0]["lat"]), float(data[0]["lon"])


def resolve_location(text: str, label: str = "location") -> tuple[float, float, str]:
    """Return (lat, lon, method) where method is 'coordinates', 'place_index', or 'nominatim'."""
    text = (text or "").strip()
    if not text:
        raise LocationError(f"{label} is required")

    m = COORD_RE.match(text)
    if m:
        lat, lon, method = float(m.group(1)), float(m.group(2)), "coordinates"
    elif (hit := _from_place_index(text)) is not None:
        (lat, lon), method = hit, "place_index"
    else:
        (lat, lon), method = _nominatim(text), "nominatim"

    if not in_usa(lat, lon):
        raise LocationError(f"{label} '{text}' is outside the USA")
    return lat, lon, method
