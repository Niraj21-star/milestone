"""
Root URL configuration for Milepost backend.

At this foundation stage (SPEC §40 step 1), only the admin-free URL root
is wired.  The /api/ namespace will be added when the trip_planner endpoint
is implemented (SPEC §40 step 6).
"""

from django.urls import path, include

urlpatterns = [
    path("api/", include("trip_planner.urls")),
]
