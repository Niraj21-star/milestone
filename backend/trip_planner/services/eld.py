"""
eld.py — ELD Daily Log Processor
===================================

SPEC §17–§23.

Converts the canonical continuous HOS event timeline into per-day 24-hour ELD log data.

Architecture:
    HOS ENGINE
        ↓ canonical events[] (is_rendering_only=False, continuous, never modified here)
        ↓
    ELD PROCESSOR (this module)
        ↓ daily_logs[] (midnight-split + day_fill, rendering-only)

Strict invariants:
  - The canonical events[] list is NEVER modified.
  - day_fill events exist ONLY in daily_logs[].events.
  - day_fill events never trigger HOS clock changes.
  - HOS clocks are never read or written here.
  - No OSRM or Nominatim calls.
  - Every daily sheet covers exactly 1440 minutes.
  - Overlapping rendered events raise ELDError.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from trip_planner.services.hos_engine import (
    ClocksSnapshot,
    EventType,
    Location,
    Reason,
    TripEvent,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ELD-specific constants
# ---------------------------------------------------------------------------

MINUTES_PER_DAY = 1440

# ELD duty-status rows (SPEC §18, in FMCSA order)
ELD_STATUSES = [
    EventType.OFF_DUTY,
    "SLEEPER_BERTH",        # present on form, never active in this implementation
    EventType.DRIVING,
    EventType.ON_DUTY_NOT_DRIVING,
]

# Remark labels (SPEC §23)
_REMARK_LABELS: dict[str, str] = {
    Reason.PICKUP:   "Pickup",
    Reason.DROPOFF:  "Dropoff",
    Reason.FUEL:     "Fuel",
    Reason.BREAK_30: "30-Min Break",
    Reason.RESET_10H: "10-Hr Reset",
}


# ---------------------------------------------------------------------------
# Structured error
# ---------------------------------------------------------------------------

class ELDError(Exception):
    """Raised when ELD processing detects an inconsistency."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code    = code
        self.message = message

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ELDEvent:
    """
    One rendered event in a daily ELD sheet (SPEC §19/§20/§21).

    start_minute_of_day and end_minute_of_day are in [0, 1440].
    """
    # Origin canonical event id (or "day_fill" for synthetic ones)
    origin_event_id:    str

    # ELD duty status — one of EventType.* or "SLEEPER_BERTH"
    status:             str

    # Reason string carried from canonical event or "day_fill"
    reason:             str

    # Position within 24-hour sheet [0, 1440]
    start_minute_of_day: int
    end_minute_of_day:   int
    duration_minutes:    int

    # Metadata
    explanation:        str
    location:           Location
    mileage_start:      float
    mileage_end:        float

    # Is this a synthetic rendering-only event? (day_fill only)
    is_rendering_only:  bool

    # Inherited clocks snapshot (day_fill inherits prior real event's snapshot)
    clocks_after:       Optional[ClocksSnapshot]

    # Remark text for ELD remarks row (SPEC §23) — None for driving/day_fill
    remark:             Optional[str]

    # UTC wall-clock times (reconstructed from trip_start_dt + minute offsets)
    start_time:         datetime
    end_time:           datetime


@dataclass
class DutyTotals:
    """Minute-totals for one 24-hour sheet (SPEC §22)."""
    off_duty:             int = 0
    sleeper_berth:        int = 0
    driving:              int = 0
    on_duty_not_driving:  int = 0

    def as_dict(self) -> dict:
        return {
            "OFF_DUTY":            self.off_duty,
            "SLEEPER_BERTH":       self.sleeper_berth,
            "DRIVING":             self.driving,
            "ON_DUTY_NOT_DRIVING": self.on_duty_not_driving,
        }

    @property
    def total(self) -> int:
        return (
            self.off_duty
            + self.sleeper_berth
            + self.driving
            + self.on_duty_not_driving
        )


@dataclass
class Remark:
    """One remark entry (SPEC §23)."""
    minute_of_day:  int
    label:          str
    location_label: str
    origin_event_id: str


@dataclass
class DailyLog:
    """
    One 24-hour ELD sheet (SPEC §18/§21/§22/§23).

    events covers exactly 1440 minutes after day_fill is applied.
    Canonical events[] is never modified.
    """
    day_index:       int
    date:            date           # calendar date of this sheet
    events:          list[ELDEvent] # midnight-split + day_fill, full 1440-min coverage
    duty_totals:     DutyTotals
    remarks:         list[Remark]
    total_miles:     float          # sum of mileage_end - mileage_start for DRIVING events
    trip_start_dt:   datetime       # trip start (for reconstructing absolute times)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _minute_of_day(dt: datetime, day_start: datetime) -> int:
    """
    Minutes elapsed since day_start (00:00 of the calendar day).
    Clamped to [0, 1440].
    """
    delta = int((dt - day_start).total_seconds() / 60)
    return max(0, min(MINUTES_PER_DAY, delta))


def _day_start_dt(trip_start_dt: datetime, day_index: int) -> datetime:
    """Return 00:00:00 UTC for calendar day (trip_start + day_index days)."""
    base_date = trip_start_dt.date() + timedelta(days=day_index)
    # Re-use same tzinfo as trip_start_dt
    tz = trip_start_dt.tzinfo
    return datetime(base_date.year, base_date.month, base_date.day, 0, 0, 0, tzinfo=tz)


def _event_remark(event: TripEvent) -> Optional[str]:
    """Return remark label for SPEC §23 events, or None."""
    return _REMARK_LABELS.get(event.reason)


def _fallback_clocks(events: list[ELDEvent]) -> Optional[ClocksSnapshot]:
    """Return the most recent non-day_fill clocks_after snapshot, or None."""
    for e in reversed(events):
        if not e.is_rendering_only and e.clocks_after is not None:
            return e.clocks_after
    return None


def _make_day_fill(
    day_index: int,
    day_start:  datetime,
    start_min:  int,
    end_min:    int,
    inherited_clocks: Optional[ClocksSnapshot],
    fallback_location: Optional[Location],
) -> ELDEvent:
    """Synthesise a rendering-only OFF_DUTY day_fill event."""
    duration = end_min - start_min
    loc = fallback_location or Location(lat=0.0, lon=0.0, label="", source="fallback")
    return ELDEvent(
        origin_event_id     = "day_fill",
        status              = EventType.OFF_DUTY,
        reason              = Reason.DAY_FILL,
        start_minute_of_day = start_min,
        end_minute_of_day   = end_min,
        duration_minutes    = duration,
        explanation         = "Off-duty (day fill — rendering only).",
        location            = loc,
        mileage_start       = 0.0,
        mileage_end         = 0.0,
        is_rendering_only   = True,
        clocks_after        = inherited_clocks,
        remark              = None,
        start_time          = day_start + timedelta(minutes=start_min),
        end_time            = day_start + timedelta(minutes=end_min),
    )


# ---------------------------------------------------------------------------
# Step 1 — Midnight splitting (SPEC §20)
# ---------------------------------------------------------------------------

def _split_across_midnight(
    event: TripEvent,
    trip_start_dt: datetime,
) -> list[tuple[int, TripEvent]]:
    """
    Split a canonical TripEvent by calendar-day boundaries.
    Returns a list of (day_index, fragment) where each fragment is a
    *synthetic copy* of the original event truncated to one calendar day.

    The original canonical event is NEVER modified.
    Fragments are used only for ELD rendering.
    """
    from copy import copy

    tz        = trip_start_dt.tzinfo
    trip_date = trip_start_dt.date()

    start = event.start_time
    end   = event.end_time

    results: list[tuple[int, TripEvent]] = []
    current_start = start

    # Walk forward by calendar day until we've covered the whole event
    while current_start < end:
        current_date = current_start.date()
        day_idx      = (current_date - trip_date).days

        # Midnight of the NEXT calendar day
        next_midnight = datetime(
            current_date.year, current_date.month, current_date.day,
            tzinfo=tz
        ) + timedelta(days=1)

        # End of this fragment = whichever is earlier: event end or next midnight
        current_end = min(end, next_midnight)

        # Duration of this fragment in minutes (at least 1 for non-zero fragments)
        frag_dur = max(0, int((current_end - current_start).total_seconds() / 60))

        if frag_dur > 0:
            # Build a minimal fragment (copy-on-write, do NOT modify original)
            frag = copy(event)
            object.__setattr__(frag, "start_time",       current_start)
            object.__setattr__(frag, "end_time",         current_end)
            object.__setattr__(frag, "duration_minutes", frag_dur)
            object.__setattr__(frag, "day_index",        day_idx)
            results.append((day_idx, frag))

        current_start = current_end

    return results


# ---------------------------------------------------------------------------
# Step 2 — Build per-day raw (un-filled) event lists
# ---------------------------------------------------------------------------

def _group_by_day(
    canonical_events: list[TripEvent],
    trip_start_dt: datetime,
) -> dict[int, list[TripEvent]]:
    """
    Group canonical events (potentially split across midnight) by day_index.
    Returns {day_index: [fragment, ...]} ordered by start_time.
    Original canonical_events list is NOT modified.
    """
    by_day: dict[int, list[TripEvent]] = {}
    for event in canonical_events:
        fragments = _split_across_midnight(event, trip_start_dt)
        for day_idx, frag in fragments:
            by_day.setdefault(day_idx, []).append(frag)

    # Sort each day's fragments by start_time
    for day_idx in by_day:
        by_day[day_idx].sort(key=lambda e: e.start_time)

    return by_day


# ---------------------------------------------------------------------------
# Step 3 — Convert fragment → ELDEvent, then fill gaps and validate
# ---------------------------------------------------------------------------

def _fragment_to_eld_event(
    frag: TripEvent,
    day_start: datetime,
) -> ELDEvent:
    """Convert a (possibly midnight-split) TripEvent fragment to an ELDEvent."""
    start_min = _minute_of_day(frag.start_time, day_start)
    end_min   = _minute_of_day(frag.end_time,   day_start)
    duration  = end_min - start_min

    return ELDEvent(
        origin_event_id     = frag.id,
        status              = frag.type,
        reason              = frag.reason,
        start_minute_of_day = start_min,
        end_minute_of_day   = end_min,
        duration_minutes    = duration,
        explanation         = frag.explanation,
        location            = frag.location,
        mileage_start       = frag.mileage_start,
        mileage_end         = frag.mileage_end,
        is_rendering_only   = False,
        clocks_after        = frag.clocks_after,
        remark              = _event_remark(frag),
        start_time          = frag.start_time,
        end_time            = frag.end_time,
    )


def _build_eld_events_for_day(
    day_index: int,
    day_start: datetime,
    fragments: list[TripEvent],
    last_real_clocks: Optional[ClocksSnapshot],
) -> list[ELDEvent]:
    """
    Convert fragments to ELDEvents, fill gaps with day_fill, enforce ordering.
    Returns a list of ELDEvents covering exactly 1440 minutes.

    Raises ELDError on overlap or negative duration in real events.
    """
    eld_events: list[ELDEvent] = []
    cursor = 0  # minutes from 00:00 covered so far

    for frag in fragments:
        eld = _fragment_to_eld_event(frag, day_start)

        # Reject negative duration
        if eld.duration_minutes < 0:
            raise ELDError(
                "ELD_NEGATIVE_DURATION",
                f"Event {eld.origin_event_id} has negative duration "
                f"({eld.duration_minutes} min) on day {day_index}.",
            )

        # Skip zero-length fragments (can arise at exact midnight boundary)
        if eld.duration_minutes == 0:
            continue

        # Detect overlap with prior event
        if eld.start_minute_of_day < cursor:
            raise ELDError(
                "ELD_OVERLAP",
                f"Event {eld.origin_event_id} starts at minute "
                f"{eld.start_minute_of_day} on day {day_index}, but "
                f"prior events already cover up to minute {cursor}.",
            )

        # Fill gap before this event
        if eld.start_minute_of_day > cursor:
            inherited = _fallback_clocks(eld_events) or last_real_clocks
            first_loc = eld_events[0].location if eld_events else eld.location
            eld_events.append(_make_day_fill(
                day_index, day_start, cursor, eld.start_minute_of_day,
                inherited, first_loc,
            ))

        eld_events.append(eld)
        cursor = eld.end_minute_of_day

    # Fill remaining time to 1440
    if cursor < MINUTES_PER_DAY:
        inherited = _fallback_clocks(eld_events) or last_real_clocks
        last_loc  = eld_events[-1].location if eld_events else None
        eld_events.append(_make_day_fill(
            day_index, day_start, cursor, MINUTES_PER_DAY,
            inherited, last_loc,
        ))

    return eld_events


# ---------------------------------------------------------------------------
# Step 4 — Compute duty totals and remarks
# ---------------------------------------------------------------------------

def _compute_totals(eld_events: list[ELDEvent]) -> DutyTotals:
    """Sum duty-status minutes for one day's events (SPEC §22)."""
    totals = DutyTotals()
    for e in eld_events:
        if e.status == EventType.OFF_DUTY:
            totals.off_duty += e.duration_minutes
        elif e.status == "SLEEPER_BERTH":
            totals.sleeper_berth += e.duration_minutes
        elif e.status == EventType.DRIVING:
            totals.driving += e.duration_minutes
        elif e.status == EventType.ON_DUTY_NOT_DRIVING:
            totals.on_duty_not_driving += e.duration_minutes
    return totals


def _compute_remarks(eld_events: list[ELDEvent]) -> list[Remark]:
    """Generate remarks for non-driving, non-day_fill events (SPEC §23)."""
    remarks = []
    for e in eld_events:
        if e.is_rendering_only:
            continue
        if e.status == EventType.DRIVING:
            continue
        label = _REMARK_LABELS.get(e.reason)
        if label is None:
            continue
        remarks.append(Remark(
            minute_of_day   = e.start_minute_of_day,
            label           = label,
            location_label  = e.location.label if e.location else "",
            origin_event_id = e.origin_event_id,
        ))
    return remarks


def _compute_total_miles(eld_events: list[ELDEvent]) -> float:
    """Sum miles from DRIVING events on this day."""
    return sum(
        e.mileage_end - e.mileage_start
        for e in eld_events
        if e.status == EventType.DRIVING and not e.is_rendering_only
    )


# ---------------------------------------------------------------------------
# Step 5 — Validation (SPEC §22, §34)
# ---------------------------------------------------------------------------

def validate_daily_log(log: DailyLog) -> None:
    """
    Raise ELDError if a daily log violates any structural invariant.

    Checked:
    - Total duty minutes == 1440
    - Events are chronological
    - No overlaps
    - No negative durations
    - All events have valid ELD statuses
    """
    valid_statuses = {
        EventType.OFF_DUTY,
        EventType.DRIVING,
        EventType.ON_DUTY_NOT_DRIVING,
        "SLEEPER_BERTH",
    }

    # 1440 check
    if log.duty_totals.total != MINUTES_PER_DAY:
        raise ELDError(
            "ELD_TOTAL_NOT_1440",
            f"Day {log.day_index}: duty totals sum to {log.duty_totals.total}, "
            f"expected {MINUTES_PER_DAY}.",
        )

    cursor = 0
    for e in log.events:
        # Status validity
        if e.status not in valid_statuses:
            raise ELDError(
                "ELD_INVALID_STATUS",
                f"Day {log.day_index}: event {e.origin_event_id} has "
                f"invalid status '{e.status}'.",
            )
        # Negative duration
        if e.duration_minutes < 0:
            raise ELDError(
                "ELD_NEGATIVE_DURATION",
                f"Day {log.day_index}: event {e.origin_event_id} has "
                f"negative duration {e.duration_minutes}.",
            )
        # Chronological / no overlap
        if e.start_minute_of_day < cursor:
            raise ELDError(
                "ELD_OVERLAP",
                f"Day {log.day_index}: event {e.origin_event_id} overlaps at "
                f"minute {e.start_minute_of_day} (cursor={cursor}).",
            )
        cursor = e.end_minute_of_day

    if cursor != MINUTES_PER_DAY:
        raise ELDError(
            "ELD_COVERAGE_INCOMPLETE",
            f"Day {log.day_index}: events cover only {cursor} minutes, "
            f"expected {MINUTES_PER_DAY}.",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_daily_logs(
    canonical_events: list[TripEvent],
    trip_start_dt: datetime,
) -> list[DailyLog]:
    """
    Convert a canonical HOS event list into per-day ELD logs.

    SPEC §20/§21/§22/§23.

    Args:
        canonical_events: Output of HOSEngine.run().events — never modified.
        trip_start_dt:    Trip start datetime (timezone-aware).

    Returns:
        List of DailyLog objects, one per calendar day, chronologically ordered.
        Each daily log covers exactly 1440 minutes.

    Raises:
        ELDError on structural violations (overlap, negative duration, etc.)
    """
    if not canonical_events:
        return []

    # Group fragments by day
    by_day = _group_by_day(canonical_events, trip_start_dt)

    # Ensure we cover every day from 0..max_day (no gaps between days)
    max_day   = max(by_day.keys())
    all_days  = range(max_day + 1)
    base_date = trip_start_dt.date()

    daily_logs: list[DailyLog] = []
    last_real_clocks: Optional[ClocksSnapshot] = None

    for day_idx in all_days:
        day_start  = _day_start_dt(trip_start_dt, day_idx)
        cal_date   = base_date + timedelta(days=day_idx)
        fragments  = by_day.get(day_idx, [])

        # Build ELDEvents (with gaps filled)
        eld_events = _build_eld_events_for_day(
            day_idx, day_start, fragments, last_real_clocks
        )

        # Update last_real_clocks for next day's day_fill inheritance
        for e in reversed(eld_events):
            if not e.is_rendering_only and e.clocks_after is not None:
                last_real_clocks = e.clocks_after
                break

        totals  = _compute_totals(eld_events)
        remarks = _compute_remarks(eld_events)
        miles   = _compute_total_miles(eld_events)

        daily_log = DailyLog(
            day_index     = day_idx,
            date          = cal_date,
            events        = eld_events,
            duty_totals   = totals,
            remarks       = remarks,
            total_miles   = miles,
            trip_start_dt = trip_start_dt,
        )

        # Validate before appending
        validate_daily_log(daily_log)
        daily_logs.append(daily_log)

    return daily_logs
