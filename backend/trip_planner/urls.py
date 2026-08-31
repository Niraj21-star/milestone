"""
URL routing for the trip_planner app.

GET  /api/health/     — health check
POST /api/plan-trip/  — plan a trip (SPEC §26)
"""

from django.urls import path

from trip_planner.views import HealthCheckView, PlanTripView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("plan-trip/", PlanTripView.as_view(), name="plan-trip"),
]
