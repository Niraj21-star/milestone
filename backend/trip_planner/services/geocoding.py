"""
geocoding.py — Google Geocoding API client
=========================================

SPEC §13–§14.

All calls are backend-only; React never touches this.
Timeout = 5s, 1 retry (SPEC §13).
Results are cached per unique input string within a call to geocode_locations().
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

from trip_planner.services.hos_engine import Location

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GOOGLE_GEOCODE_BASE = "https://maps.googleapis.com/maps/api/geocode/json"
TIMEOUT_SECONDS     = 5
MAX_RETRIES         = 1
THROTTLE_SECONDS    = 0.0

# Module-level throttle tracker (shared across a process)
_last_geocoding_call: float = 0.0


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
    """Throttle tracker maintained for backward compatibility with existing test patches."""
    global _last_geocoding_call
    _last_geocoding_call = time.monotonic()


def _google_geocode_get(params: dict) -> dict:
    """
    GET from Google Geocoding API with timeout and one retry.
    Returns parsed JSON dict.
    Raises GeocodingError on all failure modes.
    NEVER logs the API key.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    request_params = dict(params)
    if "key" not in request_params:
        request_params["key"] = api_key

    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            _throttle()
            resp = requests.get(GOOGLE_GEOCODE_BASE, params=request_params, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout as exc:
            last_exc = exc
            log.warning("Geocoding API timeout (attempt %d)", attempt + 1)
        except requests.HTTPError as exc:
            last_exc = exc
            log.warning("Geocoding API HTTP error (attempt %d): %s", attempt + 1, exc)
            break  # HTTP errors are not retried (server-side issue)
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("Geocoding API request error (attempt %d): %s", attempt + 1, exc)

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
    Resolve a user-entered location string to lat/lon via Google Geocoding API.

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
        "address": location_str.strip(),
    }

    try:
        data = _google_geocode_get(params)
    except GeocodingError as exc:
        exc.field = field
        raise

    if not isinstance(data, dict):
        raise GeocodingError(
            "GEOCODING_MALFORMED",
            "Expected a JSON object from geocoding service.",
            field=field,
        )

    status = data.get("status")
    results = data.get("results", [])

    if status == "ZERO_RESULTS" or (isinstance(results, list) and len(results) == 0):
        raise GeocodingError(
            "GEOCODING_NO_RESULT",
            f"We couldn't find '{location_str}' — try a more specific city, state.",
            field=field,
        )

    if status != "OK":
        raise GeocodingError(
            "GEOCODING_UNAVAILABLE",
            f"Geocoding service returned status: {status}",
            field=field,
        )

    try:
        first_result = results[0]
        geometry     = first_result["geometry"]
        location     = geometry["location"]
        lat          = float(location["lat"])
        lon          = float(location["lng"])
        label        = first_result.get("formatted_address", location_str)
    except (KeyError, ValueError, TypeError, IndexError) as exc:
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
    Attempt to produce a human-readable label for an interpolated coordinate via Google Geocoding API.

    Returns:
        A formatted_address string, or None on any failure.
        Never raises — failure degrades label only.
    """
    params = {
        "latlng": f"{lat:.6f},{lon:.6f}",
    }
    try:
        data = _google_geocode_get(params)
        if isinstance(data, dict) and data.get("status") == "OK":
            results = data.get("results", [])
            if results and isinstance(results, list) and "formatted_address" in results[0]:
                return results[0]["formatted_address"]
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
