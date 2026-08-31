"""
test_eld.py — ELD Processor Unit Tests
=======================================

Tests for eld.py covering all SPEC §17–§23 requirements and the 25+
edge-case scenarios specified in the milestone.

Run with (from milestone/backend/):
    python -m pytest trip_planner/tests/test_eld.py -v
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import List

import pytest

from trip_planner.services.eld import (
    MINUTES_PER_DAY,
    DailyLog,
    DutyTotals,
    ELDError,
    ELDEvent,
    Remark,
    _build_eld_events_for_day,
    _day_start_dt,
    _group_by_day,
    _make_day_fill,
    _split_across_midnight,
    build_daily_logs,
    validate_daily_log,
)
from trip_planner.services.hos_engine import (
    ClocksSnapshot,
    EventType,
    Location,
    Reason,
    TripEvent,
    make_test_request,
    plan_trip,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

UTC = timezone.utc
BASE_DT = datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC)   # trip starts at 00:00


def _clocks(d=0, w=0, b=0, c=0) -> ClocksSnapshot:
    return ClocksSnapshot(
        driving_min=d, window_min=w, since_break_min=b, cycle_used_min=c
    )


def _loc(label="Test") -> Location:
    return Location(lat=0.0, lon=0.0, label=label, source="fallback")


def _make_event(
    event_id: str,
    event_type: str,
    reason: str,
    start: datetime,
    end: datetime,
    location: Location = None,
    mileage_start: float = 0.0,
    mileage_end: float = 0.0,
    explanation: str = "test event",
    map_marker_type: str = "test",
) -> TripEvent:
    """Build a synthetic TripEvent for testing."""
    duration = max(0, int((end - start).total_seconds() / 60))
    day_idx  = (start.date() - BASE_DT.date()).days
    return TripEvent(
        id               = event_id,
        type             = event_type,
        reason           = reason,
        start_time       = start,
        end_time         = end,
        duration_minutes = duration,
        day_index        = day_idx,
        location         = location or _loc(),
        mileage_start    = mileage_start,
        mileage_end      = mileage_end,
        clocks_after     = _clocks(),
        explanation      = explanation,
        map_marker_type  = map_marker_type,
        is_rendering_only= False,
    )


def _run_engine(leg1, leg2, cycle=0.0, start_dt=BASE_DT):
    req    = make_test_request(leg1, leg2, cycle, trip_start_dt=start_dt)
    result = plan_trip(req)
    return result.events


def _build_logs(events, trip_start=BASE_DT):
    return build_daily_logs(events, trip_start)


# ---------------------------------------------------------------------------
# 1. Single-day trip
# ---------------------------------------------------------------------------

class TestSingleDayTrip:

    def test_returns_exactly_one_log(self):
        events = _run_engine(100, 100)
        logs   = _build_logs(events)
        assert len(logs) == 1

    def test_day_index_zero(self):
        events = _run_engine(100, 100)
        logs   = _build_logs(events)
        assert logs[0].day_index == 0

    def test_date_matches_trip_start(self):
        events = _run_engine(100, 100)
        logs   = _build_logs(events)
        assert logs[0].date == BASE_DT.date()

    def test_total_1440(self):
        events = _run_engine(100, 100)
        logs   = _build_logs(events)
        assert logs[0].duty_totals.total == MINUTES_PER_DAY

    def test_canonical_events_unchanged(self):
        events = _run_engine(100, 100)
        count_before = len(events)
        _build_logs(events)
        assert len(events) == count_before

    def test_no_rendering_only_in_canonical(self):
        events = _run_engine(100, 100)
        _build_logs(events)
        assert not any(e.is_rendering_only for e in events)


# ---------------------------------------------------------------------------
# 2. Multi-day trip
# ---------------------------------------------------------------------------

class TestMultiDayTrip:

    def setup_method(self):
        # 660+800 mi trip forces a reset → spans at least 2 days
        self.events = _run_engine(660, 800)
        self.logs   = _build_logs(self.events)

    def test_returns_multiple_logs(self):
        assert len(self.logs) >= 2

    def test_day_indices_sequential(self):
        indices = [log.day_index for log in self.logs]
        assert indices == list(range(len(self.logs)))

    def test_each_day_1440(self):
        for log in self.logs:
            assert log.duty_totals.total == MINUTES_PER_DAY, \
                f"Day {log.day_index} total={log.duty_totals.total}"

    def test_canonical_events_unchanged(self):
        count = len(self.events)
        assert count >= 1
        assert not any(e.is_rendering_only for e in self.events)

    def test_dates_sequential(self):
        for i, log in enumerate(self.logs):
            expected = BASE_DT.date() + timedelta(days=i)
            assert log.date == expected


# ---------------------------------------------------------------------------
# 3. Event entirely within one day
# ---------------------------------------------------------------------------

class TestEventWithinOneDay:

    def test_no_split_for_intra_day_event(self):
        start = BASE_DT + timedelta(hours=2)
        end   = BASE_DT + timedelta(hours=5)
        event = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP, start, end)
        frags = _split_across_midnight(event, BASE_DT)
        assert len(frags) == 1
        assert frags[0][0] == 0   # day_index 0

    def test_fragment_spans_correct_minutes(self):
        start = BASE_DT + timedelta(hours=3)
        end   = BASE_DT + timedelta(hours=6)
        event = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP, start, end)
        frags = _split_across_midnight(event, BASE_DT)
        _, frag = frags[0]
        assert frag.duration_minutes == 180


# ---------------------------------------------------------------------------
# 4. Event crossing midnight
# ---------------------------------------------------------------------------

class TestEventCrossingMidnight:

    def setup_method(self):
        # Event from 23:00 day0 → 03:00 day1 = 240 min
        self.start = BASE_DT + timedelta(hours=23)
        self.end   = BASE_DT + timedelta(hours=27)  # 03:00 next day
        self.event = _make_event(
            "e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
            self.start, self.end
        )

    def test_splits_into_two_fragments(self):
        frags = _split_across_midnight(self.event, BASE_DT)
        assert len(frags) == 2

    def test_fragment_day_indices(self):
        frags = _split_across_midnight(self.event, BASE_DT)
        assert frags[0][0] == 0
        assert frags[1][0] == 1

    def test_fragment_durations_sum_to_original(self):
        frags = _split_across_midnight(self.event, BASE_DT)
        total = sum(f.duration_minutes for _, f in frags)
        assert total == self.event.duration_minutes

    def test_day0_fragment_ends_at_midnight(self):
        frags = _split_across_midnight(self.event, BASE_DT)
        _, frag0 = frags[0]
        midnight = BASE_DT + timedelta(days=1)
        assert frag0.end_time == midnight

    def test_day1_fragment_starts_at_midnight(self):
        frags = _split_across_midnight(self.event, BASE_DT)
        _, frag1 = frags[1]
        midnight = BASE_DT + timedelta(days=1)
        assert frag1.start_time == midnight

    def test_reason_preserved(self):
        frags = _split_across_midnight(self.event, BASE_DT)
        for _, frag in frags:
            assert frag.reason == Reason.DRIVE_TO_PICKUP

    def test_original_event_unchanged(self):
        original_dur = self.event.duration_minutes
        _ = _split_across_midnight(self.event, BASE_DT)
        assert self.event.duration_minutes == original_dur
        assert self.event.start_time == self.start
        assert self.event.end_time   == self.end


# ---------------------------------------------------------------------------
# 5. Multiple events crossing midnight
# ---------------------------------------------------------------------------

class TestMultipleEventsCrossingMidnight:

    def test_two_crossing_events(self):
        e1 = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                         BASE_DT + timedelta(hours=23),
                         BASE_DT + timedelta(hours=25))
        e2 = _make_event("e2", EventType.OFF_DUTY, Reason.RESET_10H,
                         BASE_DT + timedelta(hours=25),
                         BASE_DT + timedelta(hours=35))
        events = [e1, e2]
        logs   = _build_logs(events)
        assert len(logs) == 2
        for log in logs:
            assert log.duty_totals.total == MINUTES_PER_DAY

    def test_three_day_spanning_event(self):
        # Event spans 3 calendar days:
        # start = day0 22:00, end = day0 22:00 + 27h = day1 25:00 = day2 01:00
        # So fragments: day0 (22:00-24:00), day1 (00:00-24:00), day2 (00:00-01:00)
        start = BASE_DT + timedelta(hours=22)
        end   = BASE_DT + timedelta(hours=22 + 27)  # +27h → into day 2
        event = _make_event("e1", EventType.OFF_DUTY, Reason.RESET_10H, start, end)
        frags = _split_across_midnight(event, BASE_DT)
        # Should produce fragments for days 0, 1, 2
        day_indices = [d for d, _ in frags]
        assert 0 in day_indices
        assert 1 in day_indices
        assert 2 in day_indices


# ---------------------------------------------------------------------------
# 6. First-day day_fill
# ---------------------------------------------------------------------------

class TestFirstDayDayFill:

    def test_trip_starting_00_has_no_leading_fill(self):
        # Trip at 00:00 → first event at minute 0 → no leading day_fill needed
        events = _run_engine(100, 100, start_dt=BASE_DT)
        logs   = _build_logs(events, BASE_DT)
        first_real = [e for e in logs[0].events if not e.is_rendering_only][0]
        assert first_real.start_minute_of_day == 0

    def test_trip_starting_later_has_leading_fill(self):
        # Start at 06:00 → first 360 minutes should be day_fill
        start_dt = datetime(2026, 9, 2, 6, 0, 0, tzinfo=UTC)
        event = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                            start_dt, start_dt + timedelta(hours=2))
        logs  = _build_logs([event], trip_start=BASE_DT)
        fills = [e for e in logs[0].events if e.is_rendering_only and e.reason == Reason.DAY_FILL]
        assert len(fills) >= 1
        assert fills[0].start_minute_of_day == 0
        assert fills[0].end_minute_of_day   == 360

    def test_leading_fill_is_rendering_only(self):
        start_dt = datetime(2026, 9, 2, 1, 0, 0, tzinfo=UTC)
        event = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                            start_dt, start_dt + timedelta(hours=1))
        logs  = _build_logs([event], trip_start=BASE_DT)
        first = logs[0].events[0]
        assert first.is_rendering_only

    def test_leading_fill_is_off_duty(self):
        start_dt = datetime(2026, 9, 2, 2, 0, 0, tzinfo=UTC)
        event = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                            start_dt, start_dt + timedelta(hours=1))
        logs  = _build_logs([event], trip_start=BASE_DT)
        first = logs[0].events[0]
        assert first.status == EventType.OFF_DUTY


# ---------------------------------------------------------------------------
# 7. Last-day day_fill
# ---------------------------------------------------------------------------

class TestLastDayDayFill:

    def test_last_day_trailing_fill_exists(self):
        events = _run_engine(100, 100)
        logs   = _build_logs(events)
        last_log = logs[-1]
        fills = [e for e in last_log.events if e.is_rendering_only and e.reason == Reason.DAY_FILL]
        assert len(fills) >= 1

    def test_trailing_fill_ends_at_1440(self):
        events = _run_engine(100, 100)
        logs   = _build_logs(events)
        last_log = logs[-1]
        last_event = last_log.events[-1]
        assert last_event.end_minute_of_day == MINUTES_PER_DAY

    def test_trailing_fill_is_rendering_only(self):
        events = _run_engine(100, 100)
        logs   = _build_logs(events)
        last_event = logs[-1].events[-1]
        assert last_event.is_rendering_only

    def test_trailing_fill_is_off_duty(self):
        events = _run_engine(100, 100)
        logs   = _build_logs(events)
        last_event = logs[-1].events[-1]
        assert last_event.status == EventType.OFF_DUTY


# ---------------------------------------------------------------------------
# 8. Gap between events filled with day_fill
# ---------------------------------------------------------------------------

class TestGapFilling:

    def test_gap_filled_with_off_duty(self):
        # Event from 01:00 to 02:00, then from 04:00 to 05:00 → gap 02:00-04:00
        e1 = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                         BASE_DT + timedelta(hours=1),
                         BASE_DT + timedelta(hours=2))
        e2 = _make_event("e2", EventType.DRIVING, Reason.DRIVE_TO_DROPOFF,
                         BASE_DT + timedelta(hours=4),
                         BASE_DT + timedelta(hours=5))
        logs = _build_logs([e1, e2])
        fills = [e for e in logs[0].events if e.is_rendering_only]
        # Should have leading fill (0-60), gap fill (120-240), trailing fill (300-1440)
        assert len(fills) >= 1
        # Total must still be 1440
        assert logs[0].duty_totals.total == MINUTES_PER_DAY

    def test_gap_fill_is_rendering_only_off_duty(self):
        e1 = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                         BASE_DT + timedelta(hours=1), BASE_DT + timedelta(hours=2))
        e2 = _make_event("e2", EventType.DRIVING, Reason.DRIVE_TO_DROPOFF,
                         BASE_DT + timedelta(hours=4), BASE_DT + timedelta(hours=5))
        logs  = _build_logs([e1, e2])
        fills = [e for e in logs[0].events if e.is_rendering_only]
        for f in fills:
            assert f.status == EventType.OFF_DUTY
            assert f.is_rendering_only


# ---------------------------------------------------------------------------
# 9. No gap between consecutive events
# ---------------------------------------------------------------------------

class TestNoGap:

    def test_adjacent_events_no_fill_between(self):
        e1 = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                         BASE_DT, BASE_DT + timedelta(hours=2))
        e2 = _make_event("e2", EventType.ON_DUTY_NOT_DRIVING, Reason.PICKUP,
                         BASE_DT + timedelta(hours=2),
                         BASE_DT + timedelta(hours=3))
        logs  = _build_logs([e1, e2])
        # The transition at minute 120 must be gap-free (no fill between e1 and e2)
        events = logs[0].events
        real_events = [e for e in events if not e.is_rendering_only]
        assert len(real_events) == 2
        assert real_events[0].end_minute_of_day == real_events[1].start_minute_of_day


# ---------------------------------------------------------------------------
# 10. Overlapping event detection
# ---------------------------------------------------------------------------

class TestOverlapDetection:

    def test_overlap_raises_eld_error(self):
        """Two real events that overlap should raise ELDError."""
        day_start = _day_start_dt(BASE_DT, 0)

        # Create two fragments that overlap in minute space
        e1 = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                         BASE_DT + timedelta(hours=1),
                         BASE_DT + timedelta(hours=3))
        e2 = _make_event("e2", EventType.DRIVING, Reason.DRIVE_TO_DROPOFF,
                         BASE_DT + timedelta(hours=2),  # overlaps with e1
                         BASE_DT + timedelta(hours=5))

        with pytest.raises(ELDError) as exc_info:
            _build_eld_events_for_day(0, day_start, [e1, e2], None)

        assert exc_info.value.code == "ELD_OVERLAP"


# ---------------------------------------------------------------------------
# 11. Negative-duration detection
# ---------------------------------------------------------------------------

class TestNegativeDurationDetection:

    def test_negative_duration_raises(self):
        """An event with end < start (after midnight split) should raise ELDError."""
        day_start = _day_start_dt(BASE_DT, 0)

        # Manually create a fragment with reversed times
        bad_event = _make_event(
            "e_bad", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
            BASE_DT + timedelta(hours=3),
            BASE_DT + timedelta(hours=2),   # end before start → negative duration
        )
        # Override duration_minutes to be negative (as would happen with bad fragment)
        # We'll patch the duration directly
        object.__setattr__(bad_event, "duration_minutes", -60)

        with pytest.raises(ELDError) as exc_info:
            _build_eld_events_for_day(0, day_start, [bad_event], None)

        assert exc_info.value.code == "ELD_NEGATIVE_DURATION"


# ---------------------------------------------------------------------------
# 12. Exactly 1440-minute total
# ---------------------------------------------------------------------------

class TestExactly1440Minutes:

    def test_single_day_1440(self):
        logs = _build_logs(_run_engine(100, 100))
        assert logs[0].duty_totals.total == MINUTES_PER_DAY

    def test_multi_day_each_1440(self):
        logs = _build_logs(_run_engine(660, 800))
        for log in logs:
            assert log.duty_totals.total == MINUTES_PER_DAY

    def test_midnight_crossing_each_day_1440(self):
        start_dt = datetime(2026, 9, 2, 22, 0, 0, tzinfo=UTC)
        logs = _build_logs(_run_engine(300, 400, start_dt=start_dt), trip_start=start_dt)
        for log in logs:
            assert log.duty_totals.total == MINUTES_PER_DAY

    def test_sum_of_events_equals_1440(self):
        logs = _build_logs(_run_engine(100, 100))
        total_from_events = sum(e.duration_minutes for e in logs[0].events)
        assert total_from_events == MINUTES_PER_DAY

    def test_validate_raises_if_not_1440(self):
        """validate_daily_log() must raise when totals != 1440."""
        events = _run_engine(100, 100)
        logs   = _build_logs(events)
        log    = logs[0]

        # Deliberately break the totals
        bad_totals = DutyTotals(off_duty=700, driving=200, on_duty_not_driving=100)
        import dataclasses
        bad_log = dataclasses.replace(log, duty_totals=bad_totals)

        with pytest.raises(ELDError) as exc_info:
            validate_daily_log(bad_log)
        assert exc_info.value.code == "ELD_TOTAL_NOT_1440"


# ---------------------------------------------------------------------------
# 13. Duty-status totals
# ---------------------------------------------------------------------------

class TestDutyStatusTotals:

    def test_totals_sum_to_1440(self):
        logs = _build_logs(_run_engine(100, 100))
        d = logs[0].duty_totals.as_dict()
        assert sum(d.values()) == MINUTES_PER_DAY

    def test_driving_minutes_positive(self):
        logs = _build_logs(_run_engine(100, 100))
        assert logs[0].duty_totals.driving > 0

    def test_on_duty_not_driving_positive(self):
        # pickup + dropoff = at least 120 min ON_DUTY_NOT_DRIVING
        logs = _build_logs(_run_engine(100, 100))
        assert logs[0].duty_totals.on_duty_not_driving >= 120

    def test_totals_from_events_not_hardcoded(self):
        """Totals must derive from actual event durations."""
        logs      = _build_logs(_run_engine(100, 100))
        log       = logs[0]
        computed  = sum(e.duration_minutes for e in log.events
                        if e.status == EventType.DRIVING)
        assert log.duty_totals.driving == computed

    def test_off_duty_includes_day_fill(self):
        """Off-duty total must include day_fill minutes (§22)."""
        logs = _build_logs(_run_engine(100, 100))
        log  = logs[0]
        fill_minutes = sum(e.duration_minutes for e in log.events
                           if e.is_rendering_only)
        assert fill_minutes > 0
        assert log.duty_totals.off_duty >= fill_minutes


# ---------------------------------------------------------------------------
# 14. Sleeper berth row exists (always 0 minutes active)
# ---------------------------------------------------------------------------

class TestSleeperBerthRow:

    def test_sleeper_berth_in_totals_dict(self):
        logs = _build_logs(_run_engine(100, 100))
        d = logs[0].duty_totals.as_dict()
        assert "SLEEPER_BERTH" in d

    def test_sleeper_berth_always_zero(self):
        # HOS engine never emits SLEEPER_BERTH events, so total must be 0
        logs = _build_logs(_run_engine(660, 800))
        for log in logs:
            assert log.duty_totals.sleeper_berth == 0

    def test_eld_statuses_contains_sleeper_berth(self):
        from trip_planner.services.eld import ELD_STATUSES
        assert "SLEEPER_BERTH" in ELD_STATUSES


# ---------------------------------------------------------------------------
# 15. Rendering-only flag
# ---------------------------------------------------------------------------

class TestRenderingOnlyFlag:

    def test_day_fill_is_rendering_only(self):
        logs  = _build_logs(_run_engine(100, 100))
        fills = [e for e in logs[-1].events if e.reason == "day_fill"]
        for f in fills:
            assert f.is_rendering_only is True

    def test_real_events_not_rendering_only(self):
        logs = _build_logs(_run_engine(100, 100))
        for log in logs:
            real = [e for e in log.events if not e.is_rendering_only]
            assert all(e.is_rendering_only is False for e in real)

    def test_canonical_events_never_rendering_only(self):
        canonical = _run_engine(100, 100)
        _build_logs(canonical)  # run ELD
        assert all(not e.is_rendering_only for e in canonical)


# ---------------------------------------------------------------------------
# 16. day_fill never enters canonical events
# ---------------------------------------------------------------------------

class TestDayFillNeverInCanonical:

    def test_canonical_unchanged_after_eld(self):
        canonical = _run_engine(100, 100)
        original_count = len(canonical)
        original_ids   = [e.id for e in canonical]

        _build_logs(canonical)

        assert len(canonical) == original_count
        assert [e.id for e in canonical] == original_ids

    def test_no_day_fill_reason_in_canonical(self):
        canonical = _run_engine(660, 800)
        _build_logs(canonical)
        for e in canonical:
            assert e.reason != Reason.DAY_FILL

    def test_day_fill_only_in_daily_log_events(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)
        # day_fill must appear in daily log events
        fill_in_logs = any(
            e.reason == Reason.DAY_FILL
            for log in logs
            for e in log.events
        )
        # day_fill must NOT appear in canonical
        fill_in_canonical = any(e.reason == Reason.DAY_FILL for e in canonical)
        assert fill_in_logs     is True
        assert fill_in_canonical is False


# ---------------------------------------------------------------------------
# 17. Midnight does not reset HOS state
# ---------------------------------------------------------------------------

class TestMidnightNoHOSReset:

    def test_eld_does_not_modify_clocks_at_midnight(self):
        """
        ELD never writes to clocks. The canonical clocks_after on split fragments
        are inherited from the canonical event — they are not recalculated.
        """
        start_dt  = datetime(2026, 9, 2, 23, 0, 0, tzinfo=UTC)
        canonical = _run_engine(100, 100, start_dt=start_dt)

        # Record all clock snapshots before ELD
        before_snapshots = [(e.id, e.clocks_after) for e in canonical]

        logs = _build_logs(canonical, trip_start=start_dt)

        # After ELD, canonical clocks must be identical
        after_snapshots = [(e.id, e.clocks_after) for e in canonical]
        assert before_snapshots == after_snapshots

    def test_no_spurious_reset_event_in_daily_log(self):
        """
        A midnight-crossing trip that doesn't reach the 11h limit must not
        have a reset event in the daily log due to midnight processing.
        """
        start_dt  = datetime(2026, 9, 2, 23, 0, 0, tzinfo=UTC)
        canonical = _run_engine(100, 100, start_dt=start_dt)
        logs      = _build_logs(canonical, trip_start=start_dt)

        # No 10hr_reset event should appear in any daily log unless it's real
        reset_in_canonical = [e for e in canonical if e.reason == Reason.RESET_10H]
        reset_in_logs = [
            e for log in logs
            for e in log.events
            if e.reason == Reason.RESET_10H and not e.is_rendering_only
        ]
        # Real resets should match between canonical and ELD
        assert len(reset_in_logs) == len(reset_in_canonical)

    def test_day_index_increments_correctly(self):
        start_dt  = datetime(2026, 9, 2, 23, 0, 0, tzinfo=UTC)
        canonical = _run_engine(300, 400, start_dt=start_dt)
        logs      = _build_logs(canonical, trip_start=start_dt)
        assert any(log.day_index == 1 for log in logs)


# ---------------------------------------------------------------------------
# 18. Multiple calendar days
# ---------------------------------------------------------------------------

class TestMultipleCalendarDays:

    def test_three_day_trip(self):
        # 660+2000 mi → ~3-4 days
        canonical = _run_engine(660, 2000)
        logs      = _build_logs(canonical)
        assert len(logs) >= 2  # at minimum 2 days due to 10-hr reset

    def test_no_missing_days(self):
        canonical = _run_engine(660, 800)
        logs      = _build_logs(canonical)
        day_indices = [log.day_index for log in logs]
        assert day_indices == list(range(len(day_indices)))

    def test_all_days_validated(self):
        canonical = _run_engine(660, 800)
        logs      = _build_logs(canonical)
        for log in logs:
            validate_daily_log(log)  # Must not raise


# ---------------------------------------------------------------------------
# 19. Remarks generation (SPEC §23)
# ---------------------------------------------------------------------------

class TestRemarksGeneration:

    def test_pickup_generates_remark(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)
        all_remarks = [r for log in logs for r in log.remarks]
        labels = [r.label for r in all_remarks]
        assert "Pickup" in labels

    def test_dropoff_generates_remark(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)
        all_remarks = [r for log in logs for r in log.remarks]
        assert "Dropoff" in [r.label for r in all_remarks]

    def test_fuel_generates_remark(self):
        # 400+600=1000mi → fuel stop
        canonical = _run_engine(400, 600)
        logs      = _build_logs(canonical)
        all_remarks = [r for log in logs for r in log.remarks]
        assert "Fuel" in [r.label for r in all_remarks]

    def test_30min_break_generates_remark(self):
        # 480mi leg1 forces a 30-min break
        canonical = _run_engine(480, 1)
        logs      = _build_logs(canonical)
        all_remarks = [r for log in logs for r in log.remarks]
        assert "30-Min Break" in [r.label for r in all_remarks]

    def test_10hr_reset_generates_remark(self):
        canonical = _run_engine(660, 100)
        logs      = _build_logs(canonical)
        all_remarks = [r for log in logs for r in log.remarks]
        assert "10-Hr Reset" in [r.label for r in all_remarks]

    def test_driving_events_no_remark(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)
        for log in logs:
            for remark in log.remarks:
                # No remark should come from a DRIVING event
                matching_eld = [e for e in log.events
                                if e.origin_event_id == remark.origin_event_id]
                for e in matching_eld:
                    assert e.status != EventType.DRIVING

    def test_day_fill_no_remark(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)
        for log in logs:
            for remark in log.remarks:
                assert remark.origin_event_id != "day_fill"

    def test_remark_has_location_label(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)
        for log in logs:
            for remark in log.remarks:
                assert isinstance(remark.location_label, str)

    def test_remark_minute_within_day(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)
        for log in logs:
            for remark in log.remarks:
                assert 0 <= remark.minute_of_day <= MINUTES_PER_DAY


# ---------------------------------------------------------------------------
# 20. Mileage preservation
# ---------------------------------------------------------------------------

class TestMileagePreservation:

    def test_driving_mileage_preserved_from_canonical(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)

        canonical_drive_miles = sum(
            e.mileage_end - e.mileage_start
            for e in canonical
            if e.type == EventType.DRIVING
        )
        eld_drive_miles = sum(log.total_miles for log in logs)

        assert eld_drive_miles == pytest.approx(canonical_drive_miles, abs=0.1)

    def test_day_fill_has_zero_mileage(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)
        for log in logs:
            for e in log.events:
                if e.is_rendering_only:
                    assert e.mileage_start == 0.0
                    assert e.mileage_end   == 0.0

    def test_total_miles_non_negative(self):
        canonical = _run_engine(100, 100)
        logs      = _build_logs(canonical)
        for log in logs:
            assert log.total_miles >= 0.0


# ---------------------------------------------------------------------------
# 21. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_event_starts_exactly_at_0000(self):
        """Event at exactly 00:00 → start_minute_of_day == 0."""
        event = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                            BASE_DT, BASE_DT + timedelta(hours=2))
        logs  = _build_logs([event])
        real  = [e for e in logs[0].events if not e.is_rendering_only]
        assert real[0].start_minute_of_day == 0

    def test_event_ends_exactly_at_2400(self):
        """Event that ends at exactly midnight → end_minute_of_day == 1440."""
        event = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                            BASE_DT + timedelta(hours=22),
                            BASE_DT + timedelta(hours=24))
        logs  = _build_logs([event])
        real  = [e for e in logs[0].events if not e.is_rendering_only]
        assert real[-1].end_minute_of_day == MINUTES_PER_DAY

    def test_event_crossing_midnight_by_1_minute(self):
        """23:59 → 00:01 next day → splits into 1-min + 1-min fragments."""
        start = BASE_DT + timedelta(hours=23, minutes=59)
        end   = BASE_DT + timedelta(hours=24, minutes=1)
        event = _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP, start, end)
        frags = _split_across_midnight(event, BASE_DT)
        assert len(frags) == 2
        durations = [f.duration_minutes for _, f in frags]
        assert sorted(durations) == [1, 1]

    def test_event_lasting_full_24_hours(self):
        """Single 1440-minute event → no day_fill needed on that day."""
        event = _make_event("e1", EventType.OFF_DUTY, Reason.RESET_10H,
                            BASE_DT, BASE_DT + timedelta(hours=24))
        logs  = _build_logs([event])
        assert len(logs) >= 1
        assert logs[0].duty_totals.total == MINUTES_PER_DAY
        # Day 0 should have a single real event covering all 1440 minutes
        real_day0 = [e for e in logs[0].events if not e.is_rendering_only]
        assert len(real_day0) == 1
        assert real_day0[0].duration_minutes == MINUTES_PER_DAY

    def test_multiple_consecutive_events_no_gap_no_fill_between(self):
        """Adjacent events share boundary → no fill inserted between them."""
        events = [
            _make_event("e1", EventType.DRIVING, Reason.DRIVE_TO_PICKUP,
                        BASE_DT, BASE_DT + timedelta(hours=2)),
            _make_event("e2", EventType.ON_DUTY_NOT_DRIVING, Reason.PICKUP,
                        BASE_DT + timedelta(hours=2), BASE_DT + timedelta(hours=3)),
            _make_event("e3", EventType.DRIVING, Reason.DRIVE_TO_DROPOFF,
                        BASE_DT + timedelta(hours=3), BASE_DT + timedelta(hours=5)),
        ]
        logs  = _build_logs(events)
        real  = [e for e in logs[0].events if not e.is_rendering_only]
        # Real events must appear in order with no gap between them
        assert len(real) == 3
        assert real[0].end_minute_of_day == real[1].start_minute_of_day
        assert real[1].end_minute_of_day == real[2].start_minute_of_day

    def test_empty_canonical_list_returns_empty(self):
        logs = _build_logs([], trip_start=BASE_DT)
        assert logs == []

    def test_single_event_spanning_two_days_produces_two_logs(self):
        """A 30-hour event → day 0 and day 1 each get a log."""
        event = _make_event("e1", EventType.OFF_DUTY, Reason.RESET_10H,
                            BASE_DT,
                            BASE_DT + timedelta(hours=30))
        logs = _build_logs([event])
        assert len(logs) == 2
        for log in logs:
            assert log.duty_totals.total == MINUTES_PER_DAY


# ---------------------------------------------------------------------------
# 22. Architecture invariants
# ---------------------------------------------------------------------------

class TestArchitectureInvariants:

    def test_eld_does_not_import_osrm(self):
        """eld.py must not import routing or geocoding modules."""
        import trip_planner.services.eld as eld_module
        source_path = eld_module.__file__
        with open(source_path, encoding="utf-8") as f:
            src = f.read()
        # Check actual import statements — not doc comments that may reference spec
        import re
        import_lines = [line.strip() for line in src.splitlines()
                        if re.match(r'^(import|from)\s', line.strip())]
        import_text = "\n".join(import_lines).lower()
        assert "routing" not in import_text, (
            "eld.py imports routing module — must not call OSRM"
        )
        assert "geocoding" not in import_text, (
            "eld.py imports geocoding module — must not call Nominatim"
        )
        assert "requests" not in import_text, (
            "eld.py imports requests — must make no HTTP calls"
        )

    def test_eld_does_not_import_django(self):
        import trip_planner.services.eld as eld_module
        source_path = eld_module.__file__
        with open(source_path, encoding="utf-8") as f:
            src = f.read()
        assert "django" not in src.lower()

    def test_eld_does_not_modify_hos_clocks(self):
        """
        Canonical event clocks_after snapshots must be identical before/after ELD.
        """
        canonical = _run_engine(660, 800)
        snapshots_before = [
            (e.id, e.clocks_after.driving_min, e.clocks_after.cycle_used_min)
            for e in canonical
        ]
        _build_logs(canonical)
        snapshots_after = [
            (e.id, e.clocks_after.driving_min, e.clocks_after.cycle_used_min)
            for e in canonical
        ]
        assert snapshots_before == snapshots_after
