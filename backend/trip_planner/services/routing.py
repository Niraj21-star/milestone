"""
routing.py — OSRM routing client + geometry annotation + stop interpolation
===========================================================================

SPEC §13–§14.

Responsibilities:
  1. Fetch two-leg routes from OSRM (current→pickup, pickup→dropoff).
  2. Decode OSRM polyline geometry and annotate each vertex with its
     cumulative distance in decimal miles (haversine summation, §14).
  3. Expose interpolate_location() — given a geometry and a target
     cumulative mileage, return a lat/lon on the actual route.
  4. Handle all failure modes with structured errors; never raise raw 500s.

All calls are backend-only; React never touches this.
Timeout = 5s, 1 retry (SPEC §13).
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import requests

from trip_planner.services.hos_engine import (
    Location,
    RouteLeg,
    RouteGeometryPoint,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OSRM_BASE        = "http://router.project-osrm.org"
TIMEOUT_SECONDS  = 5
MAX_RETRIES      = 1
METERS_PER_MILE  = 1609.344


# ---------------------------------------------------------------------------
# Structured error
# ---------------------------------------------------------------------------

class RoutingError(Exception):
    """Raised when the route cannot be computed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code    = code
        self.message = message

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


# ---------------------------------------------------------------------------
# Haversine helper (SPEC §14 — cumulative distance via haversine)
# ---------------------------------------------------------------------------

_EARTH_RADIUS_MILES = 3958.8


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in decimal miles."""
    φ1 = math.radians(lat1)
    φ2 = math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a  = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return _EARTH_RADIUS_MILES * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Polyline decoder (OSRM returns encoded polyline by default)
# ---------------------------------------------------------------------------

def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """
    Decode a Google/OSRM encoded polyline string into (lat, lon) pairs.
    Reference: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
    """
    coords: list[tuple[float, float]] = []
    index  = 0
    length = len(encoded)
    lat    = 0
    lon    = 0

    while index < length:
        # Latitude
        shift  = 0
        result = 0
        while True:
            b       = ord(encoded[index]) - 63
            index  += 1
            result |= (b & 0x1F) << shift
            shift  += 5
            if b < 0x20:
                break
        lat += (~result >> 1) if (result & 1) else (result >> 1)

        # Longitude
        shift  = 0
        result = 0
        while True:
            b       = ord(encoded[index]) - 63
            index  += 1
            result |= (b & 0x1F) << shift
            shift  += 5
            if b < 0x20:
                break
        lon += (~result >> 1) if (result & 1) else (result >> 1)

        coords.append((lat / 1e5, lon / 1e5))

    return coords


# ---------------------------------------------------------------------------
# Geometry annotation (SPEC §14 step 1)
# ---------------------------------------------------------------------------

def annotate_geometry(
    coords: list[tuple[float, float]],
) -> list[RouteGeometryPoint]:
    """
    Given ordered (lat, lon) pairs, return RouteGeometryPoint list where
    each point carries its cumulative_distance_miles from the start.

    Uses haversine for each consecutive pair — never integer-mile rounding.
    """
    if not coords:
        return []

    points: list[RouteGeometryPoint] = []
    cumulative = 0.0

    for i, (lat, lon) in enumerate(coords):
        if i == 0:
            cumulative = 0.0
        else:
            prev_lat, prev_lon = coords[i - 1]
            cumulative += haversine_miles(prev_lat, prev_lon, lat, lon)
        points.append(
            RouteGeometryPoint(
                lat=lat,
                lon=lon,
                cumulative_distance_miles=cumulative,
            )
        )

    return points


# ---------------------------------------------------------------------------
# Stop interpolation (SPEC §14 steps 2–4)
# ---------------------------------------------------------------------------

def interpolate_location(
    geometry: list[RouteGeometryPoint],
    target_cumulative_miles: float,
    fallback_label: str = "",
) -> Location:
    """
    Linearly interpolate a location on a route at target_cumulative_miles.

    SPEC §14:
    - Find the two consecutive vertices whose cumulative distances bracket the target.
    - Linearly interpolate lat/lon proportional to the fractional distance.
    - source = "route_interpolated"
    - On empty geometry or out-of-range target, return a safe fallback.

    Args:
        geometry:                Annotated geometry from annotate_geometry().
        target_cumulative_miles: Where along the route to interpolate.
        fallback_label:          Human-readable label used if coordinates cannot be labelled.

    Returns:
        Location with source="route_interpolated" (or "fallback" if geometry is empty).
    """
    if not geometry:
        return Location(lat=0.0, lon=0.0, label=fallback_label or "Unknown", source="fallback")

    # Clamp to start
    if target_cumulative_miles <= 0.0:
        g = geometry[0]
        return Location(lat=g.lat, lon=g.lon, label=fallback_label, source="route_interpolated")

    # Clamp to end
    if target_cumulative_miles >= geometry[-1].cumulative_distance_miles:
        g = geometry[-1]
        return Location(lat=g.lat, lon=g.lon, label=fallback_label, source="route_interpolated")

    # Binary search for the bracketing segment
    for i in range(1, len(geometry)):
        prev = geometry[i - 1]
        curr = geometry[i]
        if prev.cumulative_distance_miles <= target_cumulative_miles <= curr.cumulative_distance_miles:
            seg_len = curr.cumulative_distance_miles - prev.cumulative_distance_miles
            frac    = (
                (target_cumulative_miles - prev.cumulative_distance_miles) / seg_len
                if seg_len > 0 else 0.0
            )
            lat = prev.lat + frac * (curr.lat - prev.lat)
            lon = prev.lon + frac * (curr.lon - prev.lon)
            return Location(
                lat    = round(lat, 6),
                lon    = round(lon, 6),
                label  = fallback_label,
                source = "route_interpolated",
            )

    # Fallback — return last vertex
    g = geometry[-1]
    return Location(lat=g.lat, lon=g.lon, label=fallback_label, source="route_interpolated")


# ---------------------------------------------------------------------------
# OSRM HTTP helper
# ---------------------------------------------------------------------------

def _osrm_get(path: str, params: dict) -> dict:
    """
    GET from OSRM with timeout and one retry.
    Returns parsed JSON dict.
    Raises RoutingError on all failure modes.
    """
    url = f"{OSRM_BASE}{path}"
    last_exc: Optional[Exception] = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout as exc:
            last_exc = exc
            log.warning("OSRM timeout (attempt %d): %s", attempt + 1, url)
        except requests.HTTPError as exc:
            last_exc = exc
            log.warning("OSRM HTTP error (attempt %d): %s", attempt + 1, exc)
            break  # HTTP errors not retried
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("OSRM request error (attempt %d): %s", attempt + 1, exc)

    if isinstance(last_exc, requests.Timeout):
        raise RoutingError(
            "ROUTING_TIMEOUT",
            "Route service timed out. Please try again.",
        )
    raise RoutingError(
        "ROUTING_UNAVAILABLE",
        f"Route service is temporarily unavailable: {last_exc}",
    )


# ---------------------------------------------------------------------------
# Single-leg route fetch
# ---------------------------------------------------------------------------

def _fetch_leg(
    from_loc: Location,
    to_loc:   Location,
    from_label: str,
    to_label:   str,
) -> RouteLeg:
    """
    Fetch a single driving leg from OSRM and return an annotated RouteLeg.

    OSRM endpoint: /route/v1/driving/{lon},{lat};{lon},{lat}
    Parameters:
        overview=full   — full route geometry (encoded polyline)
        geometries=polyline — standard encoded polyline format
        steps=false     — we only need the overall geometry
    """
    coord_str = (
        f"{from_loc.lon:.6f},{from_loc.lat:.6f};"
        f"{to_loc.lon:.6f},{to_loc.lat:.6f}"
    )
    path   = f"/route/v1/driving/{coord_str}"
    params = {
        "overview":   "full",
        "geometries": "polyline",
        "steps":      "false",
    }

    try:
        data = _osrm_get(path, params)
    except RoutingError:
        raise

    # Validate response shape
    try:
        code = data.get("code", "")
        if code != "Ok":
            raise RoutingError(
                "ROUTING_NO_ROUTE",
                f"OSRM could not find a route (code={code}). "
                f"Check that locations are reachable by road.",
            )

        route    = data["routes"][0]
        legs     = route["legs"]
        leg_data = legs[0]

        distance_meters   = float(route["distance"])
        duration_seconds  = float(route["duration"])
        geometry_encoded  = route.get("geometry", "")

    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RoutingError(
            "ROUTING_MALFORMED",
            f"Unexpected OSRM response format: {exc}",
        )

    # Decode geometry → annotated geometry points
    try:
        raw_coords = decode_polyline(geometry_encoded)
    except Exception as exc:  # noqa: BLE001
        raise RoutingError(
            "ROUTING_GEOMETRY_ERROR",
            f"Could not decode route geometry: {exc}",
        )

    geometry = annotate_geometry(raw_coords)

    # Use geometry's total cumulative distance for precision (not OSRM's rounded value)
    if geometry:
        distance_miles = geometry[-1].cumulative_distance_miles
    else:
        distance_miles = distance_meters / METERS_PER_MILE

    duration_minutes = max(1, round(duration_seconds / 60))

    return RouteLeg(
        from_label       = from_label,
        to_label         = to_label,
        distance_miles   = round(distance_miles, 1),
        duration_minutes = duration_minutes,
        geometry         = geometry,
        start_location   = from_loc,
        end_location     = to_loc,
    )


# ---------------------------------------------------------------------------
# Public interface: two-leg route
# ---------------------------------------------------------------------------

def fetch_route(
    current_loc: Location,
    pickup_loc:  Location,
    dropoff_loc: Location,
) -> tuple[RouteLeg, RouteLeg]:
    """
    Fetch both driving legs (SPEC §13 — exactly two legs, current→pickup and pickup→dropoff).

    Args:
        current_loc:  Geocoded origin.
        pickup_loc:   Geocoded pickup.
        dropoff_loc:  Geocoded dropoff.

    Returns:
        (leg1, leg2) — both annotated with cumulative geometry.

    Raises:
        RoutingError on any failure.
    """
    leg1 = _fetch_leg(current_loc, pickup_loc,  from_label="current", to_label="pickup")
    leg2 = _fetch_leg(pickup_loc,  dropoff_loc, from_label="pickup",  to_label="dropoff")
    return leg1, leg2
