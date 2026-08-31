"""
geocoding.py — Nominatim geocoding / reverse-geocoding client
==============================================================

SPEC §13–§14.

All calls are backend-only; React never touches this.
Rate-limited to ~1 req/sec (SPEC §13).
Timeout = 5s, 1 retry (SPEC §13).
Results are cached per unique input string within a call to geocode_locations().
"""

from __future__ import annotations

import logging
import math
import time
from typing import Optional

import requests

from trip_planner.services.hos_engine import Location

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NOMINATIM_BASE      = "https://nominatim.openstreetmap.org"
NOMINATIM_USER_AGENT = "milepost-trip-planner/1.0"
TIMEOUT_SECONDS     = 5
MAX_RETRIES         = 1
THROTTLE_SECONDS    = 1.1   # ~1 req/sec (SPEC §13)

# Module-level throttle tracker (shared across a process)
_last_nominatim_call: float = 0.0


# ---------------------------------------------------------------------------
# Structured error
# ---------------------------------------------------------------------------

class GeocodingError(Exception):
    """Raised when a location cannot be resolved."""

    def __init__(self, code: str, message: str, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.code    = code
        self.message = message
        self.field   = field  # which input field caused the error, if known

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.field:
            d["field"] = self.field
        return d


# ---------------------------------------------------------------------------
# Internal HTTP helper
# ---------------------------------------------------------------------------

def _throttle() -> None:
    """Block until THROTTLE_SECONDS have elapsed since the last call."""
    global _last_nominatim_call
    elapsed = time.monotonic() - _last_nominatim_call
    if elapsed < THROTTLE_SECONDS:
        time.sleep(THROTTLE_SECONDS - elapsed)
    _last_nominatim_call = time.monotonic()


def _nominatim_get(path: str, params: dict) -> dict | list:
    """
    GET from Nominatim with timeout and one retry.
    Returns parsed JSON.
    Raises GeocodingError on all failure modes.
    """
    url = f"{NOMINATIM_BASE}{path}"
    headers = {"User-Agent": NOMINATIM_USER_AGENT, "Accept-Language": "en"}

    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            _throttle()
            resp = requests.get(url, params=params, headers=headers,
                                timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout as exc:
            last_exc = exc
            log.warning("Nominatim timeout (attempt %d): %s %s", attempt + 1, url, params)
        except requests.HTTPError as exc:
            last_exc = exc
            log.warning("Nominatim HTTP error (attempt %d): %s", attempt + 1, exc)
            break  # HTTP errors are not retried (server-side issue)
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("Nominatim request error (attempt %d): %s", attempt + 1, exc)

    # All attempts exhausted
    if isinstance(last_exc, requests.Timeout):
        raise GeocodingError(
            "GEOCODING_TIMEOUT",
            "Geocoding service timed out. Please try again.",
        )
    raise GeocodingError(
        "GEOCODING_UNAVAILABLE",
        f"Geocoding service is temporarily unavailable: {last_exc}",
    )


# ---------------------------------------------------------------------------
# Forward geocoding
# ---------------------------------------------------------------------------

def geocode(location_str: str, field: Optional[str] = None) -> Location:
    """
    Resolve a user-entered location string to lat/lon via Nominatim.

    Args:
        location_str: e.g. "Chicago, IL"
        field:        optional field name for error context ("current_location", etc.)

    Returns:
        Location with source="geocoded"

    Raises:
        GeocodingError on any failure or no result.
    """
    if not location_str or not location_str.strip():
        raise GeocodingError(
            "GEOCODING_EMPTY_INPUT",
            "Location string cannot be empty.",
            field=field,
        )

    params = {
        "q":              location_str.strip(),
        "format":         "json",
        "limit":          1,
        "addressdetails": 0,
    }

    try:
        data = _nominatim_get("/search", params)
    except GeocodingError as exc:
        exc.field = field
        raise

    if not isinstance(data, list) or len(data) == 0:
        raise GeocodingError(
            "GEOCODING_NO_RESULT",
            f"We couldn't find '{location_str}' — try a more specific city, state.",
            field=field,
        )

    try:
        result = data[0]
        lat    = float(result["lat"])
        lon    = float(result["lon"])
        label  = result.get("display_name", location_str)
    except (KeyError, ValueError, TypeError) as exc:
        raise GeocodingError(
            "GEOCODING_MALFORMED",
            f"Unexpected geocoding response format: {exc}",
            field=field,
        )

    return Location(lat=lat, lon=lon, label=label, source="geocoded")


def geocode_locations(
    current: str,
    pickup: str,
    dropoff: str,
) -> tuple[Location, Location, Location]:
    """
    Geocode all three trip inputs, caching duplicate strings.
    Returns (current_loc, pickup_loc, dropoff_loc).
    Raises GeocodingError with field context on first failure.
    """
    cache: dict[str, Location] = {}

    def _cached_geocode(s: str, field: str) -> Location:
        key = s.strip().lower()
        if key not in cache:
            cache[key] = geocode(s, field=field)
        return cache[key]

    current_loc  = _cached_geocode(current,  "current_location")
    pickup_loc   = _cached_geocode(pickup,   "pickup_location")
    dropoff_loc  = _cached_geocode(dropoff,  "dropoff_location")
    return current_loc, pickup_loc, dropoff_loc


# ---------------------------------------------------------------------------
# Reverse geocoding (SPEC §14)
# ---------------------------------------------------------------------------

def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """
    Attempt to produce a human-readable label for an interpolated coordinate.

    Returns:
        A display_name string, or None on any failure.
        Never raises — failure degrades label only.
    """
    params = {
        "lat":    f"{lat:.6f}",
        "lon":    f"{lon:.6f}",
        "format": "json",
        "zoom":   10,   # city/town level label
    }
    try:
        data = _nominatim_get("/reverse", params)
        if isinstance(data, dict) and "display_name" in data:
            return data["display_name"]
        return None
    except GeocodingError:
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("Unexpected reverse-geocode error: %s", exc)
        return None


def label_for_interpolated_location(
    lat: float,
    lon: float,
    fallback: str = "",
) -> tuple[str, str]:
    """
    Try to produce (label, source) for a route-interpolated coordinate.

    Attempts reverse geocoding. On failure uses fallback or formatted coords.
    Never raises.

    Returns:
        (label, source) where source is "route_interpolated" or "fallback".
    """
    label = reverse_geocode(lat, lon)
    if label:
        return label, "route_interpolated"

    # Fallback: use provided label or formatted coordinate string
    if fallback:
        return fallback, "fallback"
    return f"{lat:.4f}°, {lon:.4f}°", "fallback"
