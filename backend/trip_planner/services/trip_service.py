"""
trip_service.py — Top-level trip orchestration service
=======================================================

SPEC §27 — The service layer sits between views.py (thin) and the individual
service modules (HOS, routing, geocoding, ELD).

Flow:
    validate inputs
        ↓
    geocode locations           (geocoding.py)
        ↓
    fetch OSRM route            (routing.py)
        ↓
    run HOS simulation          (hos_engine.py)
        ↓  canonical TripEvent[]
    build ELD daily logs        (eld.py)
        ↓  DailyLog[]
    assemble TripPlanResult
        ↓
    return to views.py

This module never touches Django request/response objects —
all inputs and outputs are plain Python.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from trip_planner.services.eld import DailyLog, ELDError, build_daily_logs
from trip_planner.services.geocoding import GeocodingError, geocode_locations
from trip_planner.services.hos_engine import (
    EventType,
    Location,
    Reason,
    RouteLeg,
    TripEvent,
    TripRequest,
    TripResult,
    plan_trip,
)
from trip_planner.services.routing import RoutingError, fetch_route

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TripPlanResult:
    """
    Full result returned to the view layer (SPEC §26).

    All fields may be absent/None on complete failure, but the structure
    is always present so the view can always serialize a valid response.
    """
    # Core trip data
    trip_start_time:   Optional[str]             = None   # ISO-8601 string
    route:             Optional[dict]            = None   # serialised legs + totals
    events:            list[TripEvent]           = field(default_factory=list)
    daily_logs:        list[DailyLog]            = field(default_factory=list)
    stops:             list[TripEvent]           = field(default_factory=list)
    summary:           Optional[dict]            = None
    compliance:        Optional[dict]            = None
    warnings:          list[str]                 = field(default_factory=list)
    errors:            list[dict]                = field(default_factory=list)

    # Locations (for inspection / integration tests)
    current_location:  Optional[Location]        = None
    pickup_location:   Optional[Location]        = None
    dropoff_location:  Optional[Location]        = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_route_dict(leg1: RouteLeg, leg2: RouteLeg) -> dict:
    """Serialise two RouteLeg objects into the API route shape (SPEC §26)."""
    def _leg_dict(leg: RouteLeg) -> dict:
        return {
            "from":             leg.from_label,
            "to":               leg.to_label,
            "distance_miles":   leg.distance_miles,
            "duration_minutes": leg.duration_minutes,
            "geometry": [
                {
                    "lat": pt.lat,
                    "lon": pt.lon,
                    "cumulative_distance_miles": pt.cumulative_distance_miles,
                }
                for pt in leg.geometry
            ],
        }

    total_distance  = leg1.distance_miles + leg2.distance_miles
    total_driving   = leg1.duration_minutes + leg2.duration_minutes

    return {
        "legs":                  [_leg_dict(leg1), _leg_dict(leg2)],
        "total_distance_miles":  round(total_distance, 1),
        "total_driving_minutes": total_driving,
    }


def _build_summary(
    route:          dict,
    result:         TripResult,
    cycle_used_hrs: float,
) -> dict:
    """Build the summary dict (SPEC §26)."""
    driving_events   = [e for e in result.events if e.type == EventType.DRIVING]
    fuel_events      = [e for e in result.events if e.reason == Reason.FUEL]
    reset_events     = [e for e in result.events if e.reason == Reason.RESET_10H]

    total_driving_min = sum(e.duration_minutes for e in driving_events)
    cycle_end_min     = result.events[-1].clocks_after.cycle_used_min if result.events else int(cycle_used_hrs * 60)

    return {
        "total_distance_miles":      route["total_distance_miles"],
        "total_driving_hours":       round(total_driving_min / 60, 2),
        "total_trip_days":           len(set(e.day_index for e in result.events)),
        "fuel_stop_count":           len(fuel_events),
        "rest_stop_count":           len(reset_events),
        "cycle_used_at_start_hours": cycle_used_hrs,
        "cycle_remaining_at_end_hours": round(
            (70 * 60 - cycle_end_min) / 60, 2
        ),
    }


def _build_stops(events: list[TripEvent]) -> list[TripEvent]:
    """
    Flatten non-driving, non-day_fill events for the map/timeline (SPEC §26).
    """
    return [
        e for e in events
        if e.type != EventType.DRIVING and not e.is_rendering_only
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def plan_trip_full(
    current_location_str:    str,
    pickup_location_str:     str,
    dropoff_location_str:    str,
    current_cycle_used_hours: float,
) -> TripPlanResult:
    """
    Full trip planning orchestration (SPEC §26/§27).

    Steps:
      1. Geocode all three locations.
      2. Fetch OSRM route (two legs).
      3. Run HOS simulation.
      4. Build ELD daily logs from canonical events.
      5. Assemble and return TripPlanResult.

    On partial failure (geocoding/routing), returns a TripPlanResult with
    `errors` populated and no trip data — never raises unhandled exceptions.

    On HOS failure (cycle exhausted), returns a partial plan with errors.

    Args:
        current_location_str:     e.g. "Chicago, IL"
        pickup_location_str:      e.g. "Indianapolis, IN"
        dropoff_location_str:     e.g. "Denver, CO"
        current_cycle_used_hours: hours already used in the 70h cycle

    Returns:
        TripPlanResult — always a valid Python object, never raises.
    """
    result = TripPlanResult()

    # ------------------------------------------------------------------
    # Step 1 — Input validation
    # ------------------------------------------------------------------
    errors: list[dict] = []

    if current_cycle_used_hours < 0:
        errors.append({"code": "INVALID_CYCLE", "field": "current_cycle_used_hours",
                        "message": "Cycle hours cannot be negative."})
    if current_cycle_used_hours >= 70:
        errors.append({"code": "CYCLE_EXHAUSTED", "field": "current_cycle_used_hours",
                        "message": f"Cannot plan a trip: cycle hours ({current_cycle_used_hours:.1f}h) "
                                   f"are at or above the 70-hour limit."})

    if not current_location_str or not current_location_str.strip():
        errors.append({"code": "MISSING_FIELD", "field": "current_location",
                        "message": "Current location is required."})
    if not pickup_location_str or not pickup_location_str.strip():
        errors.append({"code": "MISSING_FIELD", "field": "pickup_location",
                        "message": "Pickup location is required."})
    if not dropoff_location_str or not dropoff_location_str.strip():
        errors.append({"code": "MISSING_FIELD", "field": "dropoff_location",
                        "message": "Dropoff location is required."})

    if errors:
        result.errors = errors
        return result

    # ------------------------------------------------------------------
    # Step 2 — Geocoding
    # ------------------------------------------------------------------
    try:
        current_loc, pickup_loc, dropoff_loc = geocode_locations(
            current_location_str,
            pickup_location_str,
            dropoff_location_str,
        )
    except GeocodingError as exc:
        log.warning("Geocoding failed: %s", exc)
        result.errors = [exc.to_dict()]
        return result
    except Exception as exc:
        log.error("Unexpected geocoding error: %s", exc, exc_info=True)
        result.errors = [{"code": "GEOCODING_ERROR", "message": str(exc)}]
        return result

    result.current_location = current_loc
    result.pickup_location  = pickup_loc
    result.dropoff_location = dropoff_loc

    # ------------------------------------------------------------------
    # Step 3 — Routing
    # ------------------------------------------------------------------
    try:
        leg1, leg2 = fetch_route(current_loc, pickup_loc, dropoff_loc)
    except RoutingError as exc:
        log.warning("Routing failed: %s", exc)
        result.errors = [exc.to_dict()]
        return result
    except Exception as exc:
        log.error("Unexpected routing error: %s", exc, exc_info=True)
        result.errors = [{"code": "ROUTING_ERROR", "message": str(exc)}]
        return result

    route_dict     = _build_route_dict(leg1, leg2)
    result.route   = route_dict

    # ------------------------------------------------------------------
    # Step 4 — Trip start time (deterministic: 00:00 UTC today, SPEC §5)
    # ------------------------------------------------------------------
    today          = date.today()
    trip_start_dt  = datetime(today.year, today.month, today.day, 0, 0, 0,
                               tzinfo=timezone.utc)
    result.trip_start_time = trip_start_dt.isoformat()

    # ------------------------------------------------------------------
    # Step 5 — HOS simulation
    # ------------------------------------------------------------------
    try:
        hos_request  = TripRequest(
            legs                     = [leg1, leg2],
            current_cycle_used_hours = current_cycle_used_hours,
            trip_start_dt            = trip_start_dt,
        )
        hos_result = plan_trip(hos_request)
    except ValueError as exc:
        # Cycle validation failure (SPEC §4)
        result.errors = [{"code": "INVALID_INPUT", "message": str(exc)}]
        return result
    except Exception as exc:
        log.error("HOS engine error: %s", exc, exc_info=True)
        result.errors = [{"code": "HOS_ENGINE_ERROR", "message": str(exc)}]
        return result

    # Attach canonical events (never modified after this point)
    result.events     = hos_result.events
    result.compliance = hos_result.compliance
    result.warnings   = hos_result.warnings
    result.errors     = hos_result.errors

    # ------------------------------------------------------------------
    # Step 6 — ELD daily logs
    # ------------------------------------------------------------------
    try:
        result.daily_logs = build_daily_logs(hos_result.events, trip_start_dt)
    except ELDError as exc:
        log.error("ELD processing error: %s", exc)
        # ELD failure is non-fatal: return the partial plan with an error
        result.errors = result.errors + [exc.to_dict()]
        result.daily_logs = []
    except Exception as exc:
        log.error("Unexpected ELD error: %s", exc, exc_info=True)
        result.errors = result.errors + [{"code": "ELD_ERROR", "message": str(exc)}]
        result.daily_logs = []

    # ------------------------------------------------------------------
    # Step 7 — Stops + summary
    # ------------------------------------------------------------------
    result.stops   = _build_stops(hos_result.events)
    result.summary = _build_summary(route_dict, hos_result, current_cycle_used_hours)

    return result
