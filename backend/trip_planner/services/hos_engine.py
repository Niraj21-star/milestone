"""
hos_engine.py — Milepost HOS Simulation Engine
================================================

Pure Python, zero Django/HTTP/database imports.
Implements SPEC §4–§16 exactly.

Clock model (SPEC §6):
  A  driving_min          — resets at 10-hr OFF_DUTY          — limit 660 min (11h)
  B  window_min           — resets at 10-hr OFF_DUTY          — limit 840 min (14h)
  C  since_break_min      — resets at any qualifying ≥30-min non-driving event — limit 480 min (8h)
  D  cycle_used_min       — NEVER reset mid-simulation        — limit 4200 min (70h)

Midnight is a calendar/rendering boundary only — it resets NO clock.

Public interface:
  plan_trip(request: TripRequest) -> TripResult
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Constants (integer minutes throughout — SPEC §12)
# ---------------------------------------------------------------------------

DRIVING_LIMIT_MIN   = 11 * 60      # 660
WINDOW_LIMIT_MIN    = 14 * 60      # 840
BREAK_LIMIT_MIN     = 8  * 60      # 480  (driving before mandatory break)
RESET_DURATION_MIN  = 10 * 60      # 600
BREAK_DURATION_MIN  = 30
CYCLE_LIMIT_MIN     = 70 * 60      # 4200
FUEL_INTERVAL_MILES = 1000.0       # decimal miles (SPEC §11)
PICKUP_MIN          = 60
DROPOFF_MIN         = 60
FUEL_MIN            = 30
CYCLE_WARNING_PCT   = 0.10         # 10% threshold for WARNING (SPEC §24)

# ---------------------------------------------------------------------------
# Event types and reasons (SPEC §15)
# ---------------------------------------------------------------------------

class EventType:
    DRIVING              = "DRIVING"
    OFF_DUTY             = "OFF_DUTY"
    ON_DUTY_NOT_DRIVING  = "ON_DUTY_NOT_DRIVING"

class Reason:
    START           = "start"
    DRIVE_TO_PICKUP = "drive_to_pickup"
    DRIVE_TO_DROPOFF= "drive_to_dropoff"
    PICKUP          = "pickup"
    DROPOFF         = "dropoff"
    FUEL            = "fuel"
    BREAK_30        = "30_min_break"
    RESET_10H       = "10hr_reset"
    DAY_FILL        = "day_fill"

class ComplianceStatus:
    COMPLIANT = "COMPLIANT"
    WARNING   = "WARNING"
    BLOCKED   = "BLOCKED"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Location:
    lat: float
    lon: float
    label: str
    source: str  # "geocoded" | "route_interpolated" | "fallback"


@dataclass
class ClocksSnapshot:
    driving_min:     int
    window_min:      int
    since_break_min: int
    cycle_used_min:  int


@dataclass
class TripEvent:
    id:               str
    type:             str        # EventType constant
    reason:           str        # Reason constant
    start_time:       datetime
    end_time:         datetime
    duration_minutes: int
    day_index:        int
    location:         Location
    mileage_start:    float
    mileage_end:      float
    clocks_after:     ClocksSnapshot
    explanation:      str
    map_marker_type:  str
    is_rendering_only: bool


@dataclass
class RouteGeometryPoint:
    """One vertex in an OSRM route geometry, pre-annotated with cumulative distance."""
    lat: float
    lon: float
    cumulative_distance_miles: float


@dataclass
class RouteLeg:
    """One driving leg (current→pickup or pickup→dropoff)."""
    from_label:       str   # "current" or "pickup"
    to_label:         str   # "pickup"  or "dropoff"
    distance_miles:   float
    duration_minutes: int
    geometry:         list[RouteGeometryPoint]
    start_location:   Location
    end_location:     Location


@dataclass
class TripRequest:
    """
    Everything the HOS engine needs.  Callers (views / tests) provide this.
    Route geometry is pre-computed by routing.py (Step 4) and passed in here.
    For Step-2 unit tests, geometry is synthesised directly in the test helpers.
    """
    legs:                    list[RouteLeg]
    current_cycle_used_hours: float
    trip_start_dt:           datetime   # timezone-aware, already fixed to 00:00 origin tz


@dataclass
class TripResult:
    events:      list[TripEvent]
    compliance:  dict
    warnings:    list[str]
    errors:      list[dict]
    blocked:     bool


# ---------------------------------------------------------------------------
# Internal mutable clock state (never exposed directly)
# ---------------------------------------------------------------------------

@dataclass
class _Clocks:
    driving_min:     int = 0
    window_min:      int = 0
    since_break_min: int = 0
    cycle_used_min:  int = 0

    def snapshot(self) -> ClocksSnapshot:
        return ClocksSnapshot(
            driving_min     = self.driving_min,
            window_min      = self.window_min,
            since_break_min = self.since_break_min,
            cycle_used_min  = self.cycle_used_min,
        )


# ---------------------------------------------------------------------------
# Geometry helpers (inline so hos_engine.py has zero external deps)
# ---------------------------------------------------------------------------

def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in decimal miles."""
    R = 3958.8  # Earth radius, miles
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _interpolate_location(
    geometry: list[RouteGeometryPoint],
    target_cumulative_miles: float,
    fallback_label: str,
) -> Location:
    """
    Linearly interpolate lat/lon at target_cumulative_miles along geometry.
    SPEC §14 — result must lie between the two bracketing vertices.
    """
    if not geometry:
        return Location(lat=0.0, lon=0.0, label=fallback_label, source="fallback")

    # Clamp to end if target exceeds geometry length
    if target_cumulative_miles >= geometry[-1].cumulative_distance_miles:
        g = geometry[-1]
        return Location(lat=g.lat, lon=g.lon, label=fallback_label, source="route_interpolated")

    for i in range(1, len(geometry)):
        prev = geometry[i - 1]
        curr = geometry[i]
        if prev.cumulative_distance_miles <= target_cumulative_miles <= curr.cumulative_distance_miles:
            seg_len = curr.cumulative_distance_miles - prev.cumulative_distance_miles
            if seg_len == 0:
                frac = 0.0
            else:
                frac = (target_cumulative_miles - prev.cumulative_distance_miles) / seg_len
            lat = prev.lat + frac * (curr.lat - prev.lat)
            lon = prev.lon + frac * (curr.lon - prev.lon)
            return Location(lat=round(lat, 6), lon=round(lon, 6),
                            label=fallback_label, source="route_interpolated")

    # fallback — return last point
    g = geometry[-1]
    return Location(lat=g.lat, lon=g.lon, label=fallback_label, source="route_interpolated")


# ---------------------------------------------------------------------------
# Explanation templates (SPEC §25)
# ---------------------------------------------------------------------------

def _explain_fuel(miles_since_fuel: float) -> str:
    return f"Fuel stop scheduled after {miles_since_fuel:.1f} route miles."


def _explain_break(driving_since_break_min: int) -> str:
    hours = driving_since_break_min / 60
    return f"30-minute driving interruption required after {hours:.1f} cumulative hours of driving."


def _explain_reset(trigger: str, clock_value_min: int, limit_min: int) -> str:
    clock_h  = clock_value_min / 60
    limit_h  = limit_min / 60
    return (
        f"10-hour off-duty period required — {trigger} reached "
        f"({clock_h:.1f}h / {limit_h:.0f}h)."
    )


# ---------------------------------------------------------------------------
# map_marker_type mapping
# ---------------------------------------------------------------------------

def _marker_type(reason: str) -> str:
    return {
        Reason.START:            "start",
        Reason.DRIVE_TO_PICKUP:  "driving",
        Reason.DRIVE_TO_DROPOFF: "driving",
        Reason.PICKUP:           "pickup",
        Reason.DROPOFF:          "dropoff",
        Reason.FUEL:             "fuel",
        Reason.BREAK_30:         "rest",
        Reason.RESET_10H:        "rest",
        Reason.DAY_FILL:         "day_fill",
    }.get(reason, reason)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class HOSEngine:
    """
    Simulates an HOS-compliant trip given pre-computed route geometry.
    Pure Python — no Django, no HTTP, no DB.
    """

    def __init__(self, request: TripRequest) -> None:
        self._request   = request
        self._clocks    = _Clocks(
            cycle_used_min = round(request.current_cycle_used_hours * 60)
        )
        self._events:    list[TripEvent] = []
        self._event_counter              = 0
        self._now:       datetime        = request.trip_start_dt  # wall-clock cursor
        self._miles:     float           = 0.0   # cumulative route miles
        self._fuel_miles: float          = 0.0   # miles since last fuel
        self._blocked    = False
        self._warnings:  list[str]       = []
        self._errors:    list[dict]      = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> TripResult:
        """Execute the simulation and return a TripResult."""
        legs = self._request.legs

        # Leg 1: current → pickup
        pickup_location = legs[0].end_location
        self._drive_leg(legs[0], Reason.DRIVE_TO_PICKUP, pickup_location)

        if not self._blocked:
            # Pickup operation (SPEC §10)
            self._do_stop(
                event_type    = EventType.ON_DUTY_NOT_DRIVING,
                reason        = Reason.PICKUP,
                duration_min  = PICKUP_MIN,
                location      = pickup_location,
                explanation   = "Scheduled 1-hour pickup operation.",
            )

        if not self._blocked:
            # Leg 2: pickup → dropoff
            dropoff_location = legs[1].end_location
            self._drive_leg(legs[1], Reason.DRIVE_TO_DROPOFF, dropoff_location)

        if not self._blocked:
            # Dropoff operation
            self._do_stop(
                event_type    = EventType.ON_DUTY_NOT_DRIVING,
                reason        = Reason.DROPOFF,
                duration_min  = DROPOFF_MIN,
                location      = dropoff_location,
                explanation   = "Scheduled 1-hour dropoff operation.",
            )

        # Determine compliance
        compliance = self._compute_compliance()
        return TripResult(
            events     = self._events,
            compliance = compliance,
            warnings   = self._warnings,
            errors     = self._errors,
            blocked    = self._blocked,
        )

    # ------------------------------------------------------------------
    # Core driving simulator for one leg
    # ------------------------------------------------------------------

    def _drive_leg(
        self,
        leg: RouteLeg,
        driving_reason: str,
        dest_location: Location,
    ) -> None:
        """
        Drive one leg in chunks, inserting fuel/break/reset events as needed.
        Stops early (sets self._blocked) if cycle capacity is exhausted.
        """
        leg_miles_remaining = leg.distance_miles
        # Speed = distance / time → minutes per mile
        if leg.duration_minutes > 0 and leg.distance_miles > 0:
            min_per_mile = leg.duration_minutes / leg.distance_miles
        else:
            min_per_mile = 0.0

        leg_miles_driven = 0.0   # within this leg only

        while leg_miles_remaining > 0.001 and not self._blocked:
            # How many miles can we drive before each constraint fires?
            miles_to_fuel   = FUEL_INTERVAL_MILES - self._fuel_miles
            miles_to_break  = self._miles_until_break_limit(min_per_mile)
            miles_to_reset  = self._miles_until_reset_limit(min_per_mile)
            miles_to_cycle  = self._miles_until_cycle_exhausted(min_per_mile)

            # Priority ordering (SPEC §8):
            # 1. Fuel
            # 2. Pickup/dropoff — handled externally, not here
            # 3. 30-min break (Clock C)
            # 4. 11-hr driving / 14-hr window → 10-hr reset
            # 5. Cycle exhausted → BLOCKED

            # Choose the binding constraint (minimum positive miles)
            # We treat "no constraint" as infinity
            candidates = {
                "fuel":  miles_to_fuel  if miles_to_fuel  > 0.001 else math.inf,
                "break": miles_to_break if miles_to_break > 0.001 else math.inf,
                "reset": miles_to_reset if miles_to_reset > 0.001 else math.inf,
                "cycle": miles_to_cycle if miles_to_cycle > 0.001 else math.inf,
                "dest":  leg_miles_remaining,
            }

            binding = min(candidates, key=lambda k: candidates[k])
            miles_this_chunk = candidates[binding]

            # Never overshoot destination
            if miles_this_chunk > leg_miles_remaining:
                miles_this_chunk = leg_miles_remaining
                binding = "dest"

            # Never drive 0 miles (guard against floating-point noise)
            if miles_this_chunk < 0.001:
                # Something is at a limit right now — handle the event first
                if binding == "cycle" or candidates["cycle"] <= 0.001:
                    self._set_blocked()
                    return
                if binding == "reset" or candidates["reset"] <= 0.001:
                    self._insert_reset("11-hour driving limit"
                                       if self._clocks.driving_min >= DRIVING_LIMIT_MIN
                                       else "14-hour duty window")
                    continue
                if binding == "break" or candidates["break"] <= 0.001:
                    self._insert_break(current_miles=self._miles)
                    continue
                if binding == "fuel" or candidates["fuel"] <= 0.001:
                    self._insert_fuel(current_miles=self._miles, geometry=leg.geometry)
                    continue
                # Nothing to do — destination reached with near-zero remainder
                break

            # ---- Emit the DRIVING chunk --------------------------------
            drive_min = max(1, round(miles_this_chunk * min_per_mile))

            # Final pre-drive cycle check
            if self._clocks.cycle_used_min + drive_min > CYCLE_LIMIT_MIN:
                # Truncate to available cycle
                available = CYCLE_LIMIT_MIN - self._clocks.cycle_used_min
                if available <= 0:
                    self._set_blocked()
                    return
                # How many miles fit in available minutes?
                if min_per_mile > 0:
                    miles_this_chunk = available / min_per_mile
                drive_min = available
                binding = "cycle"

            chunk_start_miles = self._miles
            chunk_end_miles   = round(self._miles + miles_this_chunk, 1)

            # Interpolate location at end of chunk
            global_start = self._global_cumulative_miles_for_leg(leg, leg_miles_driven)
            global_end   = global_start + miles_this_chunk

            end_location = _interpolate_location(
                leg.geometry,
                miles_this_chunk + (leg.distance_miles - leg_miles_remaining - miles_this_chunk + leg_miles_driven + miles_this_chunk),
                dest_location.label,
            )
            # Simpler: use proportional position in geometry
            end_location = self._location_at_miles_in_leg(
                leg, leg_miles_driven + miles_this_chunk, dest_location.label
            )

            evt = self._make_driving_event(
                reason         = driving_reason,
                duration_min   = drive_min,
                location_start = self._location_at_miles_in_leg(leg, leg_miles_driven, dest_location.label),
                location_end   = end_location,
                mileage_start  = chunk_start_miles,
                mileage_end    = chunk_end_miles,
            )
            self._emit(evt)

            # Advance counters
            leg_miles_driven    += miles_this_chunk
            leg_miles_remaining -= miles_this_chunk
            self._miles          = chunk_end_miles
            self._fuel_miles    += miles_this_chunk
            # Clocks updated in _make_driving_event

            if binding == "fuel":
                self._insert_fuel(current_miles=self._miles, geometry=leg.geometry)
            elif binding == "break":
                self._insert_break(current_miles=self._miles)
            elif binding in ("reset", "cycle"):
                if binding == "cycle":
                    self._set_blocked()
                    return
                # Determine which clock triggered the reset
                trigger = (
                    "11-hour driving limit" if self._clocks.driving_min >= DRIVING_LIMIT_MIN
                    else "14-hour duty window"
                )
                self._insert_reset(trigger)

    # ------------------------------------------------------------------
    # Helper: miles until each limit fires
    # ------------------------------------------------------------------

    def _miles_until_break_limit(self, min_per_mile: float) -> float:
        """Miles of driving before Clock C hits 480 min (8h)."""
        remaining_break = BREAK_LIMIT_MIN - self._clocks.since_break_min
        if remaining_break <= 0:
            return 0.0
        if min_per_mile <= 0:
            return math.inf
        return remaining_break / min_per_mile

    def _miles_until_reset_limit(self, min_per_mile: float) -> float:
        """Miles until Clock A or Clock B fires, whichever is sooner."""
        remaining_drive  = DRIVING_LIMIT_MIN - self._clocks.driving_min
        remaining_window = WINDOW_LIMIT_MIN  - self._clocks.window_min
        # Clock B ticks for every wall-clock minute — equal to driving minutes during driving
        remaining = min(remaining_drive, remaining_window)
        if remaining <= 0:
            return 0.0
        if min_per_mile <= 0:
            return math.inf
        return remaining / min_per_mile

    def _miles_until_cycle_exhausted(self, min_per_mile: float) -> float:
        """Miles until Clock D (cycle) would hit 4200 min (70h)."""
        remaining_cycle = CYCLE_LIMIT_MIN - self._clocks.cycle_used_min
        if remaining_cycle <= 0:
            return 0.0
        if min_per_mile <= 0:
            return math.inf
        return remaining_cycle / min_per_mile

    # ------------------------------------------------------------------
    # Event factories
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        self._event_counter += 1
        return f"evt_{self._event_counter:04d}"

    def _day_index(self, dt: datetime) -> int:
        """Calendar day offset from trip start date."""
        start_date = self._request.trip_start_dt.date()
        return (dt.date() - start_date).days

    def _make_driving_event(
        self,
        reason:         str,
        duration_min:   int,
        location_start: Location,
        location_end:   Location,
        mileage_start:  float,
        mileage_end:    float,
    ) -> TripEvent:
        """Build a DRIVING event and advance ALL clocks."""
        start_time = self._now
        end_time   = start_time + timedelta(minutes=duration_min)

        # Advance clocks
        self._clocks.driving_min     += duration_min
        self._clocks.window_min      += duration_min
        self._clocks.since_break_min += duration_min
        self._clocks.cycle_used_min  += duration_min

        return TripEvent(
            id               = self._next_id(),
            type             = EventType.DRIVING,
            reason           = reason,
            start_time       = start_time,
            end_time         = end_time,
            duration_minutes = duration_min,
            day_index        = self._day_index(start_time),
            location         = location_end,   # stop position = end of drive
            mileage_start    = mileage_start,
            mileage_end      = mileage_end,
            clocks_after     = self._clocks.snapshot(),
            explanation      = f"Driving segment — {mileage_end - mileage_start:.1f} miles.",
            map_marker_type  = _marker_type(reason),
            is_rendering_only= False,
        )

    def _emit(self, event: TripEvent) -> None:
        """Update wall-clock and append event."""
        self._now = event.end_time
        self._events.append(event)

    def _insert_fuel(self, current_miles: float, geometry: list[RouteGeometryPoint]) -> None:
        """Insert a FUEL stop; reset Clock C (it's a qualifying break)."""
        location = _interpolate_location(geometry, self._fuel_miles, "Fuel stop")
        evt = self._do_stop(
            event_type   = EventType.ON_DUTY_NOT_DRIVING,
            reason       = Reason.FUEL,
            duration_min = FUEL_MIN,
            location     = location,
            explanation  = _explain_fuel(self._fuel_miles),
        )
        # Reset fuel mileage counter AFTER building explanation
        self._fuel_miles = 0.0

    def _insert_break(self, current_miles: float) -> None:
        """Insert a mandatory 30-min break; resets Clock C."""
        # Location = current position (already set externally by driving chunk)
        location = Location(lat=0.0, lon=0.0, label="Rest area", source="fallback")
        if self._events:
            last = self._events[-1]
            location = last.location
        self._do_stop(
            event_type   = EventType.OFF_DUTY,
            reason       = Reason.BREAK_30,
            duration_min = BREAK_DURATION_MIN,
            location     = location,
            explanation  = _explain_break(self._clocks.since_break_min),
        )

    def _insert_reset(self, trigger: str) -> None:
        """Insert a 10-hour OFF_DUTY reset; resets Clocks A, B, C (NOT D)."""
        if self._clocks.driving_min >= DRIVING_LIMIT_MIN:
            clock_value = self._clocks.driving_min
            limit       = DRIVING_LIMIT_MIN
        else:
            clock_value = self._clocks.window_min
            limit       = WINDOW_LIMIT_MIN

        location = Location(lat=0.0, lon=0.0, label="Rest stop", source="fallback")
        if self._events:
            location = self._events[-1].location

        self._do_stop(
            event_type   = EventType.OFF_DUTY,
            reason       = Reason.RESET_10H,
            duration_min = RESET_DURATION_MIN,
            location     = location,
            explanation  = _explain_reset(trigger, clock_value, limit),
        )

    def _do_stop(
        self,
        event_type:   str,
        reason:       str,
        duration_min: int,
        location:     Location,
        explanation:  str,
    ) -> TripEvent:
        """
        Insert any non-driving stop event.
        Advances window_min and cycle_used_min; resets since_break_min if qualifying.
        For 10-hr resets also resets driving_min and window_min.
        """
        start_time = self._now
        end_time   = start_time + timedelta(minutes=duration_min)

        # Cycle check: does this on-duty stop fit in remaining cycle?
        if event_type == EventType.ON_DUTY_NOT_DRIVING:
            if self._clocks.cycle_used_min + duration_min > CYCLE_LIMIT_MIN:
                self._set_blocked()
                return None   # type: ignore[return-value]

        # Advance clocks before snapshot
        if event_type == EventType.ON_DUTY_NOT_DRIVING:
            self._clocks.window_min     += duration_min
            self._clocks.cycle_used_min += duration_min

        elif event_type == EventType.OFF_DUTY:
            # OFF_DUTY: does NOT consume driving, window, or cycle
            pass

        # Reset logic
        if reason == Reason.RESET_10H:
            # 10-hour reset: resets A, B, C — not D
            self._clocks.driving_min     = 0
            self._clocks.window_min      = 0
            self._clocks.since_break_min = 0
        elif self._is_break_qualifying(event_type, duration_min):
            # Qualifying break: resets C only
            self._clocks.since_break_min = 0

        evt = TripEvent(
            id               = self._next_id(),
            type             = event_type,
            reason           = reason,
            start_time       = start_time,
            end_time         = end_time,
            duration_minutes = duration_min,
            day_index        = self._day_index(start_time),
            location         = location,
            mileage_start    = self._miles,
            mileage_end      = self._miles,
            clocks_after     = self._clocks.snapshot(),
            explanation      = explanation,
            map_marker_type  = _marker_type(reason),
            is_rendering_only= False,
        )
        self._emit(evt)
        return evt

    # ------------------------------------------------------------------
    # Break qualification (SPEC §8)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_break_qualifying(event_type: str, duration_min: int) -> bool:
        return (
            event_type in (EventType.OFF_DUTY, EventType.ON_DUTY_NOT_DRIVING)
            and duration_min >= BREAK_DURATION_MIN
        )

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _location_at_miles_in_leg(
        self,
        leg: RouteLeg,
        miles_into_leg: float,
        fallback_label: str,
    ) -> Location:
        """Interpolate a location at 'miles_into_leg' within the leg geometry."""
        if not leg.geometry:
            return leg.end_location
        target = min(miles_into_leg, leg.distance_miles)
        return _interpolate_location(leg.geometry, target, fallback_label)

    def _global_cumulative_miles_for_leg(self, leg: RouteLeg, leg_miles_driven: float) -> float:
        """Total cumulative trip miles at the start of the remaining portion of a leg."""
        return self._miles - leg_miles_driven

    # ------------------------------------------------------------------
    # BLOCKED
    # ------------------------------------------------------------------

    def _set_blocked(self) -> None:
        self._blocked = True
        self._errors.append({
            "code":    "BLOCKED",
            "message": (
                "Trip cannot be completed within available cycle capacity "
                f"({self._clocks.cycle_used_min / 60:.1f}h used of 70h). "
                "Partial plan returned."
            ),
        })

    # ------------------------------------------------------------------
    # Compliance (SPEC §24)
    # ------------------------------------------------------------------

    def _compute_compliance(self) -> dict:
        if self._blocked:
            return {
                "status":  ComplianceStatus.BLOCKED,
                "message": "Trip is blocked — cycle capacity exhausted before reaching dropoff.",
            }
        remaining_min = CYCLE_LIMIT_MIN - self._clocks.cycle_used_min
        warning_threshold = CYCLE_LIMIT_MIN * CYCLE_WARNING_PCT  # 420 min = 7h
        if remaining_min <= warning_threshold:
            return {
                "status":  ComplianceStatus.WARNING,
                "message": (
                    "Compliant under modeled HOS assumptions. "
                    f"Warning: only {remaining_min / 60:.1f}h of cycle capacity remaining."
                ),
            }
        return {
            "status":  ComplianceStatus.COMPLIANT,
            "message": "Compliant under modeled HOS assumptions.",
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def plan_trip(request: TripRequest) -> TripResult:
    """
    Run the HOS simulation for the given trip request.

    Args:
        request: TripRequest with pre-computed route legs and cycle hours used.

    Returns:
        TripResult with canonical events, compliance status, warnings, errors.

    Raises:
        ValueError: if current_cycle_used_hours >= 70 (SPEC §4).
    """
    # SPEC §4: reject at validation if cycle is already at/over limit
    if request.current_cycle_used_hours >= 70.0:
        raise ValueError(
            f"current_cycle_used_hours ({request.current_cycle_used_hours}) must be < 70."
        )
    if request.current_cycle_used_hours < 0:
        raise ValueError("current_cycle_used_hours cannot be negative.")

    engine = HOSEngine(request)
    return engine.run()


# ---------------------------------------------------------------------------
# Test/utility helpers (used only by unit tests and CLI validation)
# ---------------------------------------------------------------------------

def make_simple_geometry(
    start_lat: float, start_lon: float,
    end_lat: float,   end_lon: float,
    distance_miles: float,
) -> list[RouteGeometryPoint]:
    """
    Synthetic two-point geometry for unit tests.
    Assigns cumulative_distance_miles linearly.
    """
    return [
        RouteGeometryPoint(lat=start_lat, lon=start_lon, cumulative_distance_miles=0.0),
        RouteGeometryPoint(lat=end_lat,   lon=end_lon,   cumulative_distance_miles=distance_miles),
    ]


def make_test_request(
    leg1_miles: float,
    leg2_miles: float,
    cycle_used_hours: float,
    trip_start_dt: Optional[datetime] = None,
    speed_mph: float = 60.0,
) -> TripRequest:
    """
    Build a TripRequest with synthetic straight-line geometry.
    Speed defaults to 60 mph → duration_minutes = distance_miles.
    """
    if trip_start_dt is None:
        today = date.today()
        trip_start_dt = datetime(today.year, today.month, today.day, 0, 0, 0,
                                 tzinfo=timezone.utc)

    def _minutes(miles: float) -> int:
        return max(1, round(miles / speed_mph * 60))

    # Leg 1: (0,0) → (0, leg1_lon)  (trivial horizontal line)
    leg1_lon = leg1_miles / 60.0  # 1 degree ≈ 60 miles
    leg1_geo = make_simple_geometry(0.0, 0.0, 0.0, leg1_lon, leg1_miles)
    leg1 = RouteLeg(
        from_label      = "current",
        to_label        = "pickup",
        distance_miles  = leg1_miles,
        duration_minutes= _minutes(leg1_miles),
        geometry        = leg1_geo,
        start_location  = Location(lat=0.0, lon=0.0,      label="Origin",  source="geocoded"),
        end_location    = Location(lat=0.0, lon=leg1_lon,  label="Pickup",  source="geocoded"),
    )

    # Leg 2: pickup → dropoff
    leg2_lon = leg1_lon + leg2_miles / 60.0
    leg2_geo = [
        RouteGeometryPoint(lat=0.0, lon=leg1_lon, cumulative_distance_miles=0.0),
        RouteGeometryPoint(lat=0.0, lon=leg2_lon, cumulative_distance_miles=leg2_miles),
    ]
    leg2 = RouteLeg(
        from_label      = "pickup",
        to_label        = "dropoff",
        distance_miles  = leg2_miles,
        duration_minutes= _minutes(leg2_miles),
        geometry        = leg2_geo,
        start_location  = Location(lat=0.0, lon=leg1_lon, label="Pickup",  source="geocoded"),
        end_location    = Location(lat=0.0, lon=leg2_lon, label="Dropoff", source="geocoded"),
    )

    return TripRequest(
        legs                     = [leg1, leg2],
        current_cycle_used_hours = cycle_used_hours,
        trip_start_dt            = trip_start_dt,
    )