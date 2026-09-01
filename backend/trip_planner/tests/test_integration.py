"""
test_integration.py — Step 5 Integration Tests
===============================================

Tests the full application pipeline:
    Request → Geocoding → Routing → HOS Engine → ELD → API Response

All external HTTP calls (Nominatim/OSRM) are mocked.
The internal pipeline (HOS + ELD) runs with real logic.

Run with (from milestone/backend/):
    python -m pytest trip_planner/tests/test_integration.py -v
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests as requests_lib

# Must be set before importing anything Django-aware
import django
from django.conf import settings
if not settings.configured:
    import os
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
    django.setup()

from rest_framework.test import APIClient, APIRequestFactory

from trip_planner.services.eld import MINUTES_PER_DAY, build_daily_logs
from trip_planner.services.hos_engine import (
    EventType,
    Reason,
    make_test_request,
    plan_trip,
)
from trip_planner.services.trip_service import TripPlanResult, plan_trip_full
from trip_planner.serializers import TripPlanResultSerializer

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def _geo_response(lat: float = 41.0, lon: float = -87.0, label: str = "Test City") -> MagicMock:
    """Mock Google Geocoding forward geocoding response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "status": "OK",
        "results": [
            {
                "formatted_address": label,
                "geometry": {
                    "location": {"lat": lat, "lng": lon}
                }
            }
        ]
    }
    return resp


def _osrm_response(distance_m: float = 100_000, duration_s: float = 6_000) -> MagicMock:
    """Mock OSRM routing response with a simple encoded polyline."""
    # Simple encoded polyline: _p~iF~ps|U_ulLnnqC  (~Chicago → ~Indy area)
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "code": "Ok",
        "routes": [{
            "distance": distance_m,
            "duration": duration_s,
            "geometry": "_p~iF~ps|U_ulLnnqC_mqNvxq`@",
            "legs":     [{"distance": distance_m, "duration": duration_s, "steps": []}],
        }],
        "waypoints": [],
    }
    return resp


def _rev_geo_response(label: str = "Somewhere, TX") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "status": "OK",
        "results": [{"formatted_address": label}]
    }
    return resp


def _mock_requests_get(url, **kwargs):
    """Side effect for requests.get to route to the correct mock based on URL."""
    if "googleapis" in url or "nominatim" in url or "geocode" in url:
        return _geo_response()
    if "project-osrm" in url:
        return _osrm_response()
    raise ValueError(f"Unexpected mocked URL: {url}")


# ---------------------------------------------------------------------------
# A. Single-day trip integration test
# ---------------------------------------------------------------------------

class TestIntegrationSingleDay:
    """Test A — Single-day trip through the full pipeline."""

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_trip_succeeds(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)

        assert result.errors == [] or all(e["code"] != "GEOCODING_NO_RESULT" for e in result.errors)
        assert len(result.events) > 0
        assert result.compliance is not None

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_eld_logs_generated(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)

        assert len(result.daily_logs) >= 1

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_each_daily_log_1440(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)

        for log in result.daily_logs:
            assert log.duty_totals.total == MINUTES_PER_DAY, \
                f"Day {log.day_index} totals {log.duty_totals.total}, expected 1440"

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_daily_log_date_matches_trip_start(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)

        from datetime import date
        today = date.today()
        assert result.daily_logs[0].date == today

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_events_present_in_log(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)

        all_eld_events = [e for log in result.daily_logs for e in log.events]
        assert len(all_eld_events) > 0

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_duty_totals_correct(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)

        for log in result.daily_logs:
            d = log.duty_totals.as_dict()
            assert sum(d.values()) == MINUTES_PER_DAY


# ---------------------------------------------------------------------------
# B. Midnight-crossing trip
# ---------------------------------------------------------------------------

class TestIntegrationMidnightCrossing:
    """Test B — Midnight-crossing trip splits ELD events correctly."""

    def _run_midnight_trip(self):
        """Use the HOS engine directly (no geocoding/routing mock needed)."""
        start_dt  = datetime(2026, 9, 2, 22, 0, 0, tzinfo=UTC)
        req       = make_test_request(300, 400, 0.0, trip_start_dt=start_dt)
        result    = plan_trip(req)
        logs      = build_daily_logs(result.events, start_dt)
        return result, logs, start_dt

    def test_produces_multiple_daily_logs(self):
        _, logs, _ = self._run_midnight_trip()
        assert len(logs) >= 2

    def test_each_log_correct_date(self):
        _, logs, start_dt = self._run_midnight_trip()
        from datetime import timedelta
        for log in logs:
            expected_date = (start_dt + timedelta(days=log.day_index)).date()
            assert log.date == expected_date

    def test_each_log_1440(self):
        _, logs, _ = self._run_midnight_trip()
        for log in logs:
            assert log.duty_totals.total == MINUTES_PER_DAY

    def test_midnight_split_event_durations(self):
        result, logs, start_dt = self._run_midnight_trip()
        # The driving event starting at 22:00 should appear on day 0
        day0_events = [e for e in logs[0].events if not e.is_rendering_only]
        assert any(e.status == EventType.DRIVING for e in day0_events)

    def test_no_events_duplicated(self):
        result, logs, _ = self._run_midnight_trip()
        # Count real (non-fill) ELD events across all days
        real_eld_ids = [
            e.origin_event_id
            for log in logs
            for e in log.events
            if not e.is_rendering_only
        ]
        # Each canonical event id may appear at most 2 times (split at midnight)
        from collections import Counter
        counts = Counter(real_eld_ids)
        for event_id, count in counts.items():
            assert count <= 2, f"Event {event_id} appears {count} times (max 2 for midnight split)"

    def test_canonical_events_unmodified_after_eld(self):
        """Test D — canonical immutability under midnight split."""
        start_dt  = datetime(2026, 9, 2, 22, 0, 0, tzinfo=UTC)
        req       = make_test_request(300, 400, 0.0, trip_start_dt=start_dt)
        canonical = plan_trip(req)
        snapshot_before = [(e.id, e.start_time, e.end_time, e.duration_minutes)
                           for e in canonical.events]

        _ = build_daily_logs(canonical.events, start_dt)

        snapshot_after = [(e.id, e.start_time, e.end_time, e.duration_minutes)
                          for e in canonical.events]
        assert snapshot_before == snapshot_after


# ---------------------------------------------------------------------------
# C. Multi-day trip
# ---------------------------------------------------------------------------

class TestIntegrationMultiDay:
    """Test C — Multi-day trip: every day has a DailyLog, all 1440 minutes."""

    def _run_multiday(self):
        req    = make_test_request(660, 800, 0.0)
        result = plan_trip(req)
        logs   = build_daily_logs(result.events, result.events[0].start_time)
        return result, logs

    def test_every_day_has_daily_log(self):
        result, logs = self._run_multiday()
        max_day = max(e.day_index for e in result.events)
        assert len(logs) == max_day + 1

    def test_every_day_1440(self):
        _, logs = self._run_multiday()
        for log in logs:
            assert log.duty_totals.total == MINUTES_PER_DAY

    def test_no_canonical_events_lost(self):
        result, logs = self._run_multiday()
        canonical_ids = {e.id for e in result.events}
        eld_origin_ids = {
            e.origin_event_id
            for log in logs
            for e in log.events
            if not e.is_rendering_only
        }
        # Every canonical event must appear at least once in ELD logs
        assert canonical_ids == eld_origin_ids

    def test_day_fill_not_in_canonical(self):
        result, logs = self._run_multiday()
        day_fill_in_canonical = any(e.reason == Reason.DAY_FILL for e in result.events)
        assert day_fill_in_canonical is False

    def test_daily_log_dates_sequential(self):
        from datetime import timedelta
        _, logs = self._run_multiday()
        for i, log in enumerate(logs):
            if i == 0:
                continue
            diff = (log.date - logs[i - 1].date).days
            assert diff == 1


# ---------------------------------------------------------------------------
# D. Canonical event immutability (standalone)
# ---------------------------------------------------------------------------

class TestIntegrationCanonicalImmutability:
    """Test D — Captured canonical events must be unchanged after full pipeline."""

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_canonical_unchanged_after_full_pipeline(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)

        # Snapshot canonical events
        snapshot = [
            (e.id, e.start_time, e.end_time, e.duration_minutes, e.is_rendering_only)
            for e in result.events
        ]

        # Re-run ELD on the same canonical list
        build_daily_logs(result.events, datetime.fromisoformat(result.trip_start_time))

        # Verify they didn't change
        after = [
            (e.id, e.start_time, e.end_time, e.duration_minutes, e.is_rendering_only)
            for e in result.events
        ]
        assert snapshot == after

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_no_rendering_only_in_canonical_events(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)

        assert all(not e.is_rendering_only for e in result.events)

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_no_day_fill_reason_in_canonical(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)

        assert all(e.reason != Reason.DAY_FILL for e in result.events)


# ---------------------------------------------------------------------------
# E. Remarks in integrated result
# ---------------------------------------------------------------------------

class TestIntegrationRemarks:
    """Test E — Remarks are accessible in the integrated result."""

    def _get_remarks(self):
        req    = make_test_request(100, 100, 0.0)
        result = plan_trip(req)
        logs   = build_daily_logs(result.events, result.events[0].start_time)
        return [r for log in logs for r in log.remarks]

    def test_pickup_remark_present(self):
        remarks = self._get_remarks()
        assert "Pickup" in [r.label for r in remarks]

    def test_dropoff_remark_present(self):
        remarks = self._get_remarks()
        assert "Dropoff" in [r.label for r in remarks]

    def test_remarks_have_location(self):
        remarks = self._get_remarks()
        for r in remarks:
            assert isinstance(r.location_label, str)

    def test_remarks_minute_in_range(self):
        remarks = self._get_remarks()
        for r in remarks:
            assert 0 <= r.minute_of_day <= MINUTES_PER_DAY

    def test_fuel_remark_on_long_trip(self):
        req    = make_test_request(400, 600, 0.0)
        result = plan_trip(req)
        logs   = build_daily_logs(result.events, result.events[0].start_time)
        remarks = [r for log in logs for r in log.remarks]
        assert "Fuel" in [r.label for r in remarks]


# ---------------------------------------------------------------------------
# F. Mileage in integrated result
# ---------------------------------------------------------------------------

class TestIntegrationMileage:
    """Test F — Daily mileage in ELD matches canonical driving events."""

    def test_total_eld_miles_match_canonical(self):
        req    = make_test_request(200, 300, 0.0)
        result = plan_trip(req)
        logs   = build_daily_logs(result.events, result.events[0].start_time)

        canonical_miles = sum(
            e.mileage_end - e.mileage_start
            for e in result.events
            if e.type == EventType.DRIVING
        )
        eld_miles = sum(log.total_miles for log in logs)
        assert eld_miles == pytest.approx(canonical_miles, abs=0.1)

    def test_day_fill_zero_mileage(self):
        req    = make_test_request(100, 100, 0.0)
        result = plan_trip(req)
        logs   = build_daily_logs(result.events, result.events[0].start_time)

        for log in logs:
            for e in log.events:
                if e.is_rendering_only:
                    assert e.mileage_start == 0.0
                    assert e.mileage_end   == 0.0


# ---------------------------------------------------------------------------
# G. Serializer output shape (SPEC §26)
# ---------------------------------------------------------------------------

class TestIntegrationSerializerShape:
    """Verify the serialized response matches the SPEC §26 contract."""

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_response_has_all_top_level_keys(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)
        data   = TripPlanResultSerializer(result).data

        for key in ("trip_start_time", "route", "events", "daily_logs",
                    "stops", "summary", "compliance", "warnings", "errors"):
            assert key in data, f"Missing top-level key: {key}"

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_daily_logs_have_totals_minutes(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)
        data   = TripPlanResultSerializer(result).data

        for log in data["daily_logs"]:
            assert "totals_minutes" in log
            totals = log["totals_minutes"]
            assert sum(totals.values()) == MINUTES_PER_DAY

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_canonical_events_not_rendering_only(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)
        data   = TripPlanResultSerializer(result).data

        for event in data["events"]:
            assert event["is_rendering_only"] is False

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_route_has_two_legs(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)
        data   = TripPlanResultSerializer(result).data

        assert data["route"] is not None
        assert len(data["route"]["legs"]) == 2

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_summary_present(self, mock_throttle, mock_get):
        result = plan_trip_full("Chicago, IL", "Indianapolis, IN", "Denver, CO", 0.0)
        data   = TripPlanResultSerializer(result).data

        for key in ("total_distance_miles", "total_driving_hours",
                    "total_trip_days", "fuel_stop_count", "rest_stop_count"):
            assert key in data["summary"]


# ---------------------------------------------------------------------------
# H. DRF API endpoint (using DRF test client)
# ---------------------------------------------------------------------------

class TestIntegrationAPIEndpoint:
    """Test the actual Django view at /api/plan-trip/ with mocked external calls."""

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_post_returns_200(self, mock_throttle, mock_get):
        client = APIClient()
        resp   = client.post(
            "/api/plan-trip/",
            {
                "current_location":         "Chicago, IL",
                "pickup_location":          "Indianapolis, IN",
                "dropoff_location":         "Denver, CO",
                "current_cycle_used_hours": 0.0,
            },
            format="json",
        )
        assert resp.status_code == 200

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_response_contains_daily_logs(self, mock_throttle, mock_get):
        client = APIClient()
        resp   = client.post(
            "/api/plan-trip/",
            {
                "current_location":         "Chicago, IL",
                "pickup_location":          "Indianapolis, IN",
                "dropoff_location":         "Denver, CO",
                "current_cycle_used_hours": 0.0,
            },
            format="json",
        )
        data = resp.json()
        assert "daily_logs" in data
        assert len(data["daily_logs"]) >= 1

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_response_daily_logs_total_1440(self, mock_throttle, mock_get):
        client = APIClient()
        resp   = client.post(
            "/api/plan-trip/",
            {
                "current_location":         "Chicago, IL",
                "pickup_location":          "Indianapolis, IN",
                "dropoff_location":         "Denver, CO",
                "current_cycle_used_hours": 0.0,
            },
            format="json",
        )
        data = resp.json()
        for log in data["daily_logs"]:
            total = sum(log["totals_minutes"].values())
            assert total == MINUTES_PER_DAY, f"Day {log['day_index']} total={total}"

    def test_missing_location_returns_400(self):
        client = APIClient()
        resp   = client.post(
            "/api/plan-trip/",
            {
                "current_location":         "",
                "pickup_location":          "Indianapolis, IN",
                "dropoff_location":         "Denver, CO",
                "current_cycle_used_hours": 0.0,
            },
            format="json",
        )
        assert resp.status_code == 400

    def test_invalid_cycle_returns_400(self):
        client = APIClient()
        resp   = client.post(
            "/api/plan-trip/",
            {
                "current_location":         "Chicago, IL",
                "pickup_location":          "Indianapolis, IN",
                "dropoff_location":         "Denver, CO",
                "current_cycle_used_hours": 70.0,  # >= 70 → invalid
            },
            format="json",
        )
        assert resp.status_code == 400

    @patch("requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_geocoding_failure_returns_200_with_errors(self, mock_throttle, mock_get):
        """Geocoding failure → structured error in response, not a 500."""
        mock_get.side_effect = requests_lib.Timeout
        client = APIClient()
        resp   = client.post(
            "/api/plan-trip/",
            {
                "current_location":         "Chicago, IL",
                "pickup_location":          "Indianapolis, IN",
                "dropoff_location":         "Denver, CO",
                "current_cycle_used_hours": 0.0,
            },
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data.get("errors", [])) > 0
        assert data["errors"][0]["code"] == "GEOCODING_TIMEOUT"

    @patch("requests.get", side_effect=_mock_requests_get)
    @patch("trip_planner.services.geocoding._throttle")
    def test_canonical_events_not_rendering_only_in_api_response(
        self, mock_throttle, mock_get
    ):
        client = APIClient()
        resp   = client.post(
            "/api/plan-trip/",
            {
                "current_location":         "Chicago, IL",
                "pickup_location":          "Indianapolis, IN",
                "dropoff_location":         "Denver, CO",
                "current_cycle_used_hours": 0.0,
            },
            format="json",
        )
        data = resp.json()
        for event in data.get("events", []):
            assert event["is_rendering_only"] is False


# ---------------------------------------------------------------------------
# I. End-to-end realistic flow (pipeline smoke test)
# ---------------------------------------------------------------------------

class TestIntegrationEndToEnd:
    """
    Realistic end-to-end flow through the full application pipeline.
    Uses make_test_request (synthetic geometry) to avoid HTTP mocks here.
    """

    def test_full_pipeline_short_trip(self):
        """Full HOS + ELD pipeline on a short single-day trip."""
        req    = make_test_request(100, 100, 0.0)
        result = plan_trip(req)

        # canonical events present
        assert len(result.events) >= 4  # start, pickup, drive, dropoff at minimum
        assert not any(e.is_rendering_only for e in result.events)

        # ELD generation
        logs = build_daily_logs(result.events, result.events[0].start_time)
        assert len(logs) >= 1
        for log in logs:
            assert log.duty_totals.total == MINUTES_PER_DAY

        # Remarks
        all_remarks = [r for log in logs for r in log.remarks]
        assert any(r.label == "Pickup"  for r in all_remarks)
        assert any(r.label == "Dropoff" for r in all_remarks)

        # Day_fill only in ELD, never in canonical
        assert not any(e.reason == Reason.DAY_FILL for e in result.events)

        # Serialization (ensure no crash)
        from trip_planner.services.trip_service import TripPlanResult
        plan = TripPlanResult(
            events     = result.events,
            daily_logs = logs,
            compliance = result.compliance,
            warnings   = result.warnings,
            errors     = result.errors,
        )
        serialized = TripPlanResultSerializer(plan).data
        assert serialized is not None
        assert isinstance(serialized["events"], list)
        assert isinstance(serialized["daily_logs"], list)

    def test_full_pipeline_multiday_trip(self):
        """Full HOS + ELD pipeline on a multi-day trip that triggers a reset."""
        req    = make_test_request(660, 500, 0.0)
        result = plan_trip(req)

        assert any(e.reason == Reason.RESET_10H for e in result.events)

        logs = build_daily_logs(result.events, result.events[0].start_time)
        assert len(logs) >= 2

        for log in logs:
            assert log.duty_totals.total == MINUTES_PER_DAY

        # day_fill only in ELD
        day_fills_in_canonical = [e for e in result.events if e.reason == Reason.DAY_FILL]
        assert len(day_fills_in_canonical) == 0

        day_fills_in_eld = [
            e for log in logs
            for e in log.events
            if e.reason == Reason.DAY_FILL
        ]
        assert len(day_fills_in_eld) >= 1  # trailing/leading fills present

    def test_full_pipeline_cycle_heavy(self):
        """Trip with high cycle usage near the 70h limit."""
        req    = make_test_request(100, 100, 60.0)  # 60h already used
        result = plan_trip(req)

        logs = build_daily_logs(result.events, result.events[0].start_time)
        for log in logs:
            assert log.duty_totals.total == MINUTES_PER_DAY

        # Either COMPLIANT (warning) or BLOCKED — both are valid with 60h used
        assert result.compliance["status"] in ("COMPLIANT", "WARNING", "BLOCKED")


class TestHealthCheckEndpoint:
    """Test health check GET /api/health/ endpoint."""

    def test_health_check_returns_200_ok(self):
        from rest_framework.test import APIClient
        client = APIClient()
        resp = client.get("/api/health/")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

