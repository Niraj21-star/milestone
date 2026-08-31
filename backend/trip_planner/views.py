"""
views.py — Django REST Framework views for the trip planning API
================================================================

SPEC §26/§27.  This view is intentionally thin:
  - deserialize & validate request JSON
  - call trip_service.plan_trip_full()
  - serialize and return the response

No HOS, ELD, routing, or geocoding logic lives here.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.views import exception_handler as drf_exception_handler

from trip_planner.serializers import TripPlanResultSerializer
from trip_planner.services.trip_service import plan_trip_full

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom DRF exception handler (SPEC §13 — never expose raw 500s)
# ---------------------------------------------------------------------------

def custom_exception_handler(exc, context):
    """
    Wrap unhandled exceptions in the structured error format (SPEC §13).
    Raw 500s must never be returned to the client.
    """
    response = drf_exception_handler(exc, context)
    if response is not None:
        # DRF already produced a structured response — return as-is
        return response

    # Unhandled server error → wrap it
    log.error("Unhandled server error", exc_info=exc)
    return Response(
        {
            "errors": [{"code": "SERVER_ERROR", "message": "An unexpected server error occurred."}],
            "events": [],
            "daily_logs": [],
            "stops": [],
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# ---------------------------------------------------------------------------
# POST /api/plan-trip/
# ---------------------------------------------------------------------------

class PlanTripView(APIView):
    """
    POST /api/plan-trip/

    Request body (SPEC §26):
    {
        "current_location":        "Chicago, IL",
        "pickup_location":         "Indianapolis, IN",
        "dropoff_location":        "Denver, CO",
        "current_cycle_used_hours": 12.5
    }

    Response: TripPlanResult serialized per SPEC §26.
    """

    def post(self, request: Request) -> Response:
        # ---------------------------------------------------------------
        # 1. Deserialize & validate request fields
        # ---------------------------------------------------------------
        data = request.data

        current_location    = data.get("current_location", "")
        pickup_location     = data.get("pickup_location", "")
        dropoff_location    = data.get("dropoff_location", "")
        cycle_hours_raw     = data.get("current_cycle_used_hours", 0)

        # Type-coerce cycle hours
        try:
            current_cycle_used_hours = float(cycle_hours_raw)
        except (TypeError, ValueError):
            return Response(
                {
                    "errors": [{
                        "code":    "INVALID_CYCLE",
                        "field":   "current_cycle_used_hours",
                        "message": "current_cycle_used_hours must be a number.",
                    }],
                    "events":     [],
                    "daily_logs": [],
                    "stops":      [],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ---------------------------------------------------------------
        # 2. Orchestrate the trip plan
        # ---------------------------------------------------------------
        trip_result = plan_trip_full(
            current_location_str     = str(current_location),
            pickup_location_str      = str(pickup_location),
            dropoff_location_str     = str(dropoff_location),
            current_cycle_used_hours = current_cycle_used_hours,
        )

        # ---------------------------------------------------------------
        # 3. Serialize and return
        # ---------------------------------------------------------------
        serializer    = TripPlanResultSerializer(trip_result)
        response_data = serializer.data

        # Return 400 on validation-only errors (empty inputs / bad cycle)
        # Return 200 even on BLOCKED/partial trips — the error is in errors[]
        has_input_error = any(
            e.get("code") in (
                "MISSING_FIELD", "INVALID_CYCLE", "CYCLE_EXHAUSTED",
                "GEOCODING_EMPTY_INPUT",
            )
            for e in (trip_result.errors or [])
        )
        http_status = (
            status.HTTP_400_BAD_REQUEST
            if has_input_error and not trip_result.events
            else status.HTTP_200_OK
        )

        return Response(response_data, status=http_status)


class HealthCheckView(APIView):
    """Simple health check endpoint for deployment monitoring (Render/Kubernetes)."""
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"}, status=status.HTTP_200_OK)

