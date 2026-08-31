"""
serializers.py — DRF serializers for the trip planning API
===========================================================

SPEC §26 — API response shape.

Serializes:
  - TripPlanResult  → JSON response dict
  - DailyLog        → daily_logs[] array entry
  - ELDEvent        → events within each daily log
  - TripEvent       → canonical events[]
  - RouteLeg        → route.legs[]

All serializers are read-only output serializers (the API returns data,
never accepts nested structured objects in the request).

Request deserialization uses a simple inline approach in PlanTripView.
"""

from __future__ import annotations

from datetime import date, datetime

from rest_framework import serializers

from trip_planner.services.eld import DailyLog, ELDEvent
from trip_planner.services.hos_engine import (
    ClocksSnapshot,
    Location,
    RouteGeometryPoint,
    RouteLeg,
    TripEvent,
)
from trip_planner.services.trip_service import TripPlanResult


# ---------------------------------------------------------------------------
# Leaf serializers
# ---------------------------------------------------------------------------

class LocationSerializer(serializers.Serializer):
    lat    = serializers.FloatField()
    lon    = serializers.FloatField()
    label  = serializers.CharField(allow_blank=True)
    source = serializers.CharField()


class ClocksSerializer(serializers.Serializer):
    driving_min     = serializers.IntegerField()
    window_min      = serializers.IntegerField()
    since_break_min = serializers.IntegerField()
    cycle_used_min  = serializers.IntegerField()


class GeometryPointSerializer(serializers.Serializer):
    lat                       = serializers.FloatField()
    lon                       = serializers.FloatField()
    cumulative_distance_miles = serializers.FloatField()


# ---------------------------------------------------------------------------
# Canonical TripEvent serializer (SPEC §15)
# ---------------------------------------------------------------------------

class TripEventSerializer(serializers.Serializer):
    id               = serializers.CharField()
    type             = serializers.CharField()
    reason           = serializers.CharField()
    start_time       = serializers.DateTimeField()
    end_time         = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField()
    day_index        = serializers.IntegerField()
    location         = LocationSerializer()
    mileage_start    = serializers.FloatField()
    mileage_end      = serializers.FloatField()
    clocks_after     = ClocksSerializer()
    explanation      = serializers.CharField()
    map_marker_type  = serializers.CharField()
    is_rendering_only = serializers.BooleanField()

    def to_representation(self, instance: TripEvent) -> dict:
        return {
            "id":               instance.id,
            "type":             instance.type,
            "reason":           instance.reason,
            "start_time":       instance.start_time.isoformat() if instance.start_time else None,
            "end_time":         instance.end_time.isoformat()   if instance.end_time   else None,
            "duration_minutes": instance.duration_minutes,
            "day_index":        instance.day_index,
            "location": {
                "lat":    instance.location.lat,
                "lon":    instance.location.lon,
                "label":  instance.location.label,
                "source": instance.location.source,
            } if instance.location else None,
            "mileage_start":    instance.mileage_start,
            "mileage_end":      instance.mileage_end,
            "clocks_after": {
                "driving_min":     instance.clocks_after.driving_min,
                "window_min":      instance.clocks_after.window_min,
                "since_break_min": instance.clocks_after.since_break_min,
                "cycle_used_min":  instance.clocks_after.cycle_used_min,
            } if instance.clocks_after else None,
            "explanation":      instance.explanation,
            "map_marker_type":  instance.map_marker_type,
            "is_rendering_only": instance.is_rendering_only,
        }


# ---------------------------------------------------------------------------
# ELDEvent serializer
# ---------------------------------------------------------------------------

class ELDEventSerializer(serializers.Serializer):

    def to_representation(self, instance: ELDEvent) -> dict:
        return {
            "origin_event_id":      instance.origin_event_id,
            "status":               instance.status,
            "reason":               instance.reason,
            "start_minute_of_day":  instance.start_minute_of_day,
            "end_minute_of_day":    instance.end_minute_of_day,
            "duration_minutes":     instance.duration_minutes,
            "explanation":          instance.explanation,
            "location": {
                "lat":    instance.location.lat,
                "lon":    instance.location.lon,
                "label":  instance.location.label,
                "source": instance.location.source,
            } if instance.location else None,
            "mileage_start":        instance.mileage_start,
            "mileage_end":          instance.mileage_end,
            "is_rendering_only":    instance.is_rendering_only,
            "remark":               instance.remark,
            "start_time":           instance.start_time.isoformat() if instance.start_time else None,
            "end_time":             instance.end_time.isoformat()   if instance.end_time   else None,
        }


# ---------------------------------------------------------------------------
# DailyLog serializer (SPEC §26 daily_logs[])
# ---------------------------------------------------------------------------

class DailyLogSerializer(serializers.Serializer):

    def to_representation(self, instance: DailyLog) -> dict:
        events_data = [ELDEventSerializer(e).data for e in instance.events]
        remarks_data = [
            {
                "minute_of_day":   r.minute_of_day,
                "label":           r.label,
                "location_label":  r.location_label,
                "origin_event_id": r.origin_event_id,
            }
            for r in instance.remarks
        ]
        return {
            "day_index":     instance.day_index,
            "date":          instance.date.isoformat() if instance.date else None,
            "events":        events_data,
            "totals_minutes": instance.duty_totals.as_dict(),
            "remarks":       remarks_data,
            "total_miles":   instance.total_miles,
        }


# ---------------------------------------------------------------------------
# Route leg serializer
# ---------------------------------------------------------------------------

class RouteLegSerializer(serializers.Serializer):

    def to_representation(self, instance: RouteLeg) -> dict:
        return {
            "from":             instance.from_label,
            "to":               instance.to_label,
            "distance_miles":   instance.distance_miles,
            "duration_minutes": instance.duration_minutes,
            "geometry": [
                {
                    "lat": pt.lat,
                    "lon": pt.lon,
                    "cumulative_distance_miles": pt.cumulative_distance_miles,
                }
                for pt in instance.geometry
            ],
        }


# ---------------------------------------------------------------------------
# Top-level TripPlanResult serializer (SPEC §26)
# ---------------------------------------------------------------------------

class TripPlanResultSerializer(serializers.Serializer):

    def to_representation(self, instance: TripPlanResult) -> dict:
        canonical_events = [
            TripEventSerializer(e).data for e in instance.events
        ]
        daily_logs_data = [
            DailyLogSerializer(log).data for log in instance.daily_logs
        ]
        stops_data = [
            TripEventSerializer(e).data for e in instance.stops
        ]

        return {
            "trip_start_time": instance.trip_start_time,
            "route":           instance.route,
            "events":          canonical_events,
            "daily_logs":      daily_logs_data,
            "stops":           stops_data,
            "summary":         instance.summary,
            "compliance":      instance.compliance,
            "warnings":        instance.warnings,
            "errors":          instance.errors,
        }
