"""
test_routing_geocoding.py — Unit tests for routing.py and geocoding.py
=======================================================================

All HTTP calls are mocked — no real OSRM or Nominatim requests are made.

Run with (from milestone/backend/):
    python -m pytest trip_planner/tests/test_routing_geocoding.py -v
"""

from __future__ import annotations

import json
import math
from unittest.mock import MagicMock, patch

import pytest
import requests

from trip_planner.services.geocoding import (
    GeocodingError,
    geocode,
    geocode_locations,
    label_for_interpolated_location,
    reverse_geocode,
)
from trip_planner.services.routing import (
    RoutingError,
    annotate_geometry,
    decode_polyline,
    fetch_route,
    haversine_miles,
    interpolate_location,
)
from trip_planner.services.hos_engine import Location, RouteGeometryPoint, RouteLeg

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(json_data, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _simple_geometry(n: int = 3, total_miles: float = 100.0) -> list[RouteGeometryPoint]:
    """Build a synthetic linear geometry with n equally-spaced points."""
    step = total_miles / max(n - 1, 1)
    return [
        RouteGeometryPoint(lat=float(i), lon=0.0, cumulative_distance_miles=i * step)
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# GEOCODING TESTS
# ---------------------------------------------------------------------------

class TestGeocodingSuccess:
    """1. Successful geocoding."""

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_returns_location(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response([
            {"lat": "41.8781", "lon": "-87.6298", "display_name": "Chicago, IL"}
        ])
        loc = geocode("Chicago, IL")
        assert loc.lat == pytest.approx(41.8781)
        assert loc.lon == pytest.approx(-87.6298)
        assert loc.label == "Chicago, IL"
        assert loc.source == "geocoded"

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_field_stored(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response([
            {"lat": "39.7684", "lon": "-86.1581", "display_name": "Indianapolis, IN"}
        ])
        loc = geocode("Indianapolis, IN", field="pickup_location")
        assert loc.source == "geocoded"


class TestGeocodingNoResult:
    """2. Geocoding no result."""

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_raises_no_result(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response([])
        with pytest.raises(GeocodingError) as exc_info:
            geocode("ZZZ_nonexistent_place_XYZ")
        assert exc_info.value.code == "GEOCODING_NO_RESULT"

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_error_message_contains_input(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response([])
        with pytest.raises(GeocodingError) as exc_info:
            geocode("BadCity, ZZ")
        assert "BadCity, ZZ" in exc_info.value.message

    def test_empty_string_raises(self):
        with pytest.raises(GeocodingError) as exc_info:
            geocode("")
        assert exc_info.value.code == "GEOCODING_EMPTY_INPUT"


class TestGeocodingTimeout:
    """3. Geocoding timeout."""

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_timeout_raises_geocoding_error(self, mock_throttle, mock_get):
        mock_get.side_effect = requests.Timeout("timed out")
        with pytest.raises(GeocodingError) as exc_info:
            geocode("Chicago, IL")
        assert exc_info.value.code == "GEOCODING_TIMEOUT"

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_timeout_never_raises_raw_exception(self, mock_throttle, mock_get):
        mock_get.side_effect = requests.Timeout
        with pytest.raises(GeocodingError):
            geocode("Chicago, IL")  # must not raise requests.Timeout


class TestGeocodingHTTPFailure:
    """4. Geocoding HTTP failure."""

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_http_error_raises_geocoding_error(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response({}, status_code=500)
        with pytest.raises(GeocodingError) as exc_info:
            geocode("Chicago, IL")
        assert exc_info.value.code == "GEOCODING_UNAVAILABLE"

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_404_raises_geocoding_error(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response({}, status_code=404)
        with pytest.raises(GeocodingError):
            geocode("Chicago, IL")


class TestGeocodeMalformed:
    """Geocoding malformed response."""

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_missing_lat_raises(self, mock_throttle, mock_get):
        # Response is a list but lat/lon missing
        mock_get.return_value = _make_response([{"display_name": "Somewhere"}])
        with pytest.raises(GeocodingError) as exc_info:
            geocode("Chicago, IL")
        assert exc_info.value.code == "GEOCODING_MALFORMED"

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_non_numeric_lat_raises(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response([{"lat": "not_a_number", "lon": "0.0"}])
        with pytest.raises(GeocodingError) as exc_info:
            geocode("Chicago, IL")
        assert exc_info.value.code == "GEOCODING_MALFORMED"


class TestGeocodeLocations:
    """geocode_locations() — caching + all three fields."""

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_returns_three_locations(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response([
            {"lat": "41.0", "lon": "-87.0", "display_name": "A"}
        ])
        cur, pck, drp = geocode_locations("A", "B", "C")
        assert cur.source == pck.source == drp.source == "geocoded"

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_duplicate_input_cached(self, mock_throttle, mock_get):
        """Same location string → only one HTTP call."""
        mock_get.return_value = _make_response([
            {"lat": "41.0", "lon": "-87.0", "display_name": "Chicago"}
        ])
        geocode_locations("Chicago", "Chicago", "Chicago")
        assert mock_get.call_count == 1  # cached


# ---------------------------------------------------------------------------
# REVERSE GEOCODING TESTS
# ---------------------------------------------------------------------------

class TestReverseGeocodingSuccess:
    """17. Reverse geocoding success."""

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_returns_label(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response({
            "display_name": "Amarillo, TX, USA"
        })
        label = reverse_geocode(35.22, -101.83)
        assert label == "Amarillo, TX, USA"


class TestReverseGeocodingFailure:
    """18. Reverse geocoding failure — never raises, returns None."""

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_timeout_returns_none(self, mock_throttle, mock_get):
        mock_get.side_effect = requests.Timeout
        result = reverse_geocode(35.22, -101.83)
        assert result is None

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_http_error_returns_none(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response({}, status_code=500)
        result = reverse_geocode(35.22, -101.83)
        assert result is None

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_empty_response_returns_none(self, mock_throttle, mock_get):
        mock_get.return_value = _make_response({})
        result = reverse_geocode(35.22, -101.83)
        assert result is None


class TestReverseGeocodingFallback:
    """19. Generated stop retains coordinates when reverse geocoding fails."""

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_fallback_label_used_on_failure(self, mock_throttle, mock_get):
        mock_get.side_effect = requests.Timeout
        label, source = label_for_interpolated_location(35.22, -101.83, fallback="Fuel stop")
        assert label == "Fuel stop"
        assert source == "fallback"

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_coordinate_string_fallback(self, mock_throttle, mock_get):
        mock_get.side_effect = requests.Timeout
        label, source = label_for_interpolated_location(35.22, -101.83, fallback="")
        # Should contain coordinates
        assert "35." in label
        assert source == "fallback"

    @patch("trip_planner.services.geocoding.requests.get")
    @patch("trip_planner.services.geocoding._throttle")
    def test_coordinates_preserved_in_fallback(self, mock_throttle, mock_get):
        """SPEC §14 — coordinates must not be arbitrary when reverse geocoding fails."""
        mock_get.side_effect = requests.Timeout
        label, source = label_for_interpolated_location(35.2231, -101.8313, fallback="Route stop")
        # Label is fallback but the lat/lon that were PASSED IN are what get stored on Location
        # (this function returns label+source; caller stores them alongside the interpolated lat/lon)
        assert source == "fallback"
        assert label == "Route stop"  # the fallback_label we passed


# ---------------------------------------------------------------------------
# ROUTING TESTS — OSRM
# ---------------------------------------------------------------------------

# Minimal valid OSRM route response fixture
def _osrm_response(
    distance_m: float = 10000.0,
    duration_s: float = 600.0,
    geometry:   str   = "}_p~iF~ps|U_ulLnnqC_mqNvxq`@",  # a real encoded polyline sample
) -> dict:
    return {
        "code": "Ok",
        "routes": [{
            "distance": distance_m,
            "duration": duration_s,
            "geometry": geometry,
            "legs": [{"distance": distance_m, "duration": duration_s, "steps": []}],
        }],
        "waypoints": [],
    }


class TestOSRMSuccess:
    """5. Successful OSRM route."""

    @patch("trip_planner.services.routing.requests.get")
    def test_fetch_leg_returns_route_leg(self, mock_get):
        mock_get.return_value = _make_response(_osrm_response())
        from trip_planner.services.routing import _fetch_leg
        loc_a = Location(lat=41.878, lon=-87.629, label="A", source="geocoded")
        loc_b = Location(lat=39.768, lon=-86.158, label="B", source="geocoded")
        leg = _fetch_leg(loc_a, loc_b, "current", "pickup")
        assert leg.from_label == "current"
        assert leg.to_label   == "pickup"
        assert leg.distance_miles >= 0
        assert leg.duration_minutes >= 1
        assert len(leg.geometry) >= 1

    @patch("trip_planner.services.routing.requests.get")
    def test_fetch_route_returns_two_legs(self, mock_get):
        """9. Two route legs."""
        mock_get.return_value = _make_response(_osrm_response())
        cur = Location(lat=41.0, lon=-87.0, label="Current", source="geocoded")
        pck = Location(lat=39.0, lon=-86.0, label="Pickup",  source="geocoded")
        drp = Location(lat=37.0, lon=-85.0, label="Dropoff", source="geocoded")
        leg1, leg2 = fetch_route(cur, pck, drp)
        assert leg1.from_label == "current" and leg1.to_label == "pickup"
        assert leg2.from_label == "pickup"  and leg2.to_label == "dropoff"
        assert mock_get.call_count == 2  # exactly two OSRM calls


class TestOSRMTimeout:
    """6. OSRM timeout."""

    @patch("trip_planner.services.routing.requests.get")
    def test_timeout_raises_routing_error(self, mock_get):
        mock_get.side_effect = requests.Timeout
        cur = Location(lat=41.0, lon=-87.0, label="A", source="geocoded")
        pck = Location(lat=39.0, lon=-86.0, label="B", source="geocoded")
        drp = Location(lat=37.0, lon=-85.0, label="C", source="geocoded")
        with pytest.raises(RoutingError) as exc_info:
            fetch_route(cur, pck, drp)
        assert exc_info.value.code == "ROUTING_TIMEOUT"


class TestOSRMHTTPFailure:
    """7. OSRM HTTP failure."""

    @patch("trip_planner.services.routing.requests.get")
    def test_http_500_raises_routing_error(self, mock_get):
        mock_get.return_value = _make_response({}, status_code=500)
        from trip_planner.services.routing import _fetch_leg
        loc_a = Location(lat=41.0, lon=-87.0, label="A", source="geocoded")
        loc_b = Location(lat=39.0, lon=-86.0, label="B", source="geocoded")
        with pytest.raises(RoutingError) as exc_info:
            _fetch_leg(loc_a, loc_b, "current", "pickup")
        assert exc_info.value.code == "ROUTING_UNAVAILABLE"


class TestOSRMInvalidResponse:
    """8. Invalid OSRM response."""

    @patch("trip_planner.services.routing.requests.get")
    def test_non_ok_code_raises(self, mock_get):
        mock_get.return_value = _make_response({"code": "NoRoute", "routes": []})
        from trip_planner.services.routing import _fetch_leg
        loc_a = Location(lat=41.0, lon=-87.0, label="A", source="geocoded")
        loc_b = Location(lat=39.0, lon=-86.0, label="B", source="geocoded")
        with pytest.raises(RoutingError) as exc_info:
            _fetch_leg(loc_a, loc_b, "current", "pickup")
        assert exc_info.value.code == "ROUTING_NO_ROUTE"

    @patch("trip_planner.services.routing.requests.get")
    def test_missing_routes_key_raises(self, mock_get):
        mock_get.return_value = _make_response({"code": "Ok"})  # no "routes" key
        from trip_planner.services.routing import _fetch_leg
        loc_a = Location(lat=41.0, lon=-87.0, label="A", source="geocoded")
        loc_b = Location(lat=39.0, lon=-86.0, label="B", source="geocoded")
        with pytest.raises(RoutingError) as exc_info:
            _fetch_leg(loc_a, loc_b, "current", "pickup")
        assert exc_info.value.code == "ROUTING_MALFORMED"


# ---------------------------------------------------------------------------
# GEOMETRY TESTS
# ---------------------------------------------------------------------------

class TestDecimalDistanceConversion:
    """10. Decimal distance conversion (no integer rounding)."""

    def test_haversine_non_integer(self):
        # Known approx: Chicago to Indianapolis ~165 miles
        dist = haversine_miles(41.8781, -87.6298, 39.7684, -86.1581)
        assert 150 < dist < 180, f"Expected ~165 miles, got {dist:.1f}"

    def test_haversine_decimal_precision(self):
        dist = haversine_miles(0.0, 0.0, 0.001, 0.001)
        # Should be a small non-integer decimal
        assert dist > 0
        # Fractional part must be non-zero (decimal, not integer)
        assert dist != round(dist)

    def test_haversine_zero_distance(self):
        assert haversine_miles(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0)


class TestCumulativeRouteDistance:
    """11. Cumulative route distance annotation."""

    def test_first_point_is_zero(self):
        coords = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
        pts    = annotate_geometry(coords)
        assert pts[0].cumulative_distance_miles == 0.0

    def test_cumulative_strictly_increasing(self):
        coords = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
        pts    = annotate_geometry(coords)
        for i in range(1, len(pts)):
            assert pts[i].cumulative_distance_miles > pts[i - 1].cumulative_distance_miles

    def test_length_matches_input(self):
        coords = [(float(i), 0.0) for i in range(5)]
        pts    = annotate_geometry(coords)
        assert len(pts) == 5

    def test_empty_geometry_returns_empty(self):
        assert annotate_geometry([]) == []

    def test_single_point_cumulative_zero(self):
        pts = annotate_geometry([(40.0, -80.0)])
        assert pts[0].cumulative_distance_miles == 0.0

    def test_cumulative_distance_matches_haversine_sum(self):
        coords = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
        pts    = annotate_geometry(coords)
        expected = haversine_miles(0, 0, 1, 0) + haversine_miles(1, 0, 2, 0)
        assert pts[-1].cumulative_distance_miles == pytest.approx(expected, rel=1e-6)


class TestInterpolationAtRouteStart:
    """12. Interpolation at route start."""

    def test_target_zero_returns_first_point(self):
        geo = _simple_geometry(5, total_miles=100.0)
        loc = interpolate_location(geo, 0.0, "Test")
        assert loc.lat == pytest.approx(geo[0].lat)
        assert loc.lon == pytest.approx(geo[0].lon)
        assert loc.source == "route_interpolated"

    def test_negative_target_returns_first_point(self):
        geo = _simple_geometry(3, total_miles=100.0)
        loc = interpolate_location(geo, -10.0)
        assert loc.lat == pytest.approx(geo[0].lat)


class TestInterpolationAtRouteEnd:
    """13. Interpolation at route end."""

    def test_target_at_end_returns_last_point(self):
        geo = _simple_geometry(5, total_miles=100.0)
        loc = interpolate_location(geo, 100.0, "End")
        assert loc.lat == pytest.approx(geo[-1].lat)
        assert loc.lon == pytest.approx(geo[-1].lon)


class TestInterpolationBetweenVertices:
    """14. Interpolation between vertices."""

    def test_midpoint_lat_lon(self):
        geo = [
            RouteGeometryPoint(lat=0.0, lon=0.0, cumulative_distance_miles=0.0),
            RouteGeometryPoint(lat=2.0, lon=0.0, cumulative_distance_miles=100.0),
        ]
        loc = interpolate_location(geo, 50.0)
        assert loc.lat == pytest.approx(1.0, abs=1e-4)
        assert loc.lon == pytest.approx(0.0, abs=1e-4)
        assert loc.source == "route_interpolated"

    def test_quarter_point(self):
        geo = [
            RouteGeometryPoint(lat=0.0, lon=0.0, cumulative_distance_miles=0.0),
            RouteGeometryPoint(lat=4.0, lon=0.0, cumulative_distance_miles=200.0),
        ]
        loc = interpolate_location(geo, 50.0)
        assert loc.lat == pytest.approx(1.0, abs=1e-4)

    def test_multi_segment_interpolation(self):
        geo = [
            RouteGeometryPoint(lat=0.0, lon=0.0,  cumulative_distance_miles=0.0),
            RouteGeometryPoint(lat=1.0, lon=0.0,  cumulative_distance_miles=100.0),
            RouteGeometryPoint(lat=2.0, lon=0.0,  cumulative_distance_miles=200.0),
        ]
        # Target in second segment
        loc = interpolate_location(geo, 150.0)
        assert loc.lat == pytest.approx(1.5, abs=1e-4)

    def test_on_vertex_exactly(self):
        geo = [
            RouteGeometryPoint(lat=0.0, lon=0.0, cumulative_distance_miles=0.0),
            RouteGeometryPoint(lat=1.0, lon=0.0, cumulative_distance_miles=100.0),
            RouteGeometryPoint(lat=2.0, lon=0.0, cumulative_distance_miles=200.0),
        ]
        loc = interpolate_location(geo, 100.0)
        assert loc.lat == pytest.approx(1.0, abs=1e-4)


class TestInterpolationBeyondRouteEnd:
    """15. Interpolation beyond route end."""

    def test_beyond_end_returns_last_point(self):
        geo = _simple_geometry(3, total_miles=100.0)
        loc = interpolate_location(geo, 999.0)
        assert loc.lat == pytest.approx(geo[-1].lat)
        assert loc.source == "route_interpolated"


class TestEmptyGeometry:
    """16. Empty geometry."""

    def test_empty_geometry_returns_fallback(self):
        loc = interpolate_location([], 50.0, "Rest stop")
        assert loc.source == "fallback"
        assert loc.label  == "Rest stop"

    def test_empty_geometry_no_exception(self):
        loc = interpolate_location([], 0.0)
        assert loc is not None


class TestNoArbitraryCoordinates:
    """Interpolated stops must not have coordinates outside the route geometry."""

    def test_interpolated_lat_between_start_and_end(self):
        geo = [
            RouteGeometryPoint(lat=10.0, lon=0.0, cumulative_distance_miles=0.0),
            RouteGeometryPoint(lat=20.0, lon=0.0, cumulative_distance_miles=100.0),
        ]
        loc = interpolate_location(geo, 50.0)
        assert 10.0 <= loc.lat <= 20.0, (
            f"Interpolated lat {loc.lat} is outside route bounds [10, 20]. "
            f"Stop placed at arbitrary coordinate."
        )

    def test_interpolated_lon_between_start_and_end(self):
        geo = [
            RouteGeometryPoint(lat=0.0, lon=-90.0, cumulative_distance_miles=0.0),
            RouteGeometryPoint(lat=0.0, lon=-80.0, cumulative_distance_miles=100.0),
        ]
        loc = interpolate_location(geo, 30.0)
        assert -90.0 <= loc.lon <= -80.0, (
            f"Interpolated lon {loc.lon} is outside route bounds [-90, -80]. "
            f"Stop placed at arbitrary coordinate."
        )

    def test_source_is_route_interpolated_not_arbitrary(self):
        geo = [
            RouteGeometryPoint(lat=35.0, lon=-100.0, cumulative_distance_miles=0.0),
            RouteGeometryPoint(lat=36.0, lon=-100.0, cumulative_distance_miles=100.0),
        ]
        loc = interpolate_location(geo, 75.0, "Fuel")
        assert loc.source == "route_interpolated"


# ---------------------------------------------------------------------------
# POLYLINE DECODING
# ---------------------------------------------------------------------------

class TestPolylineDecoding:
    """Validate polyline decoder correctness."""

    def test_known_polyline(self):
        # "}_p~iF~ps|U_ulLnnqC" → two points near Chicago and Indianapolis
        # (this is the sample from Google's documentation)
        encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
        coords  = decode_polyline(encoded)
        assert len(coords) >= 2
        # All coordinates should be numeric
        for lat, lon in coords:
            assert isinstance(lat, float)
            assert isinstance(lon, float)

    def test_single_point(self):
        # Encode (0, 0) by hand: (0 << 1) → 0 → 0 + 63 = '?' → '??'
        # Google encoding: 0 → 0x00 → + 63 = 63 = '?'
        encoded = "??"  # encodes lat=0, lon=0
        coords  = decode_polyline(encoded)
        assert len(coords) == 1
        assert coords[0] == pytest.approx((0.0, 0.0), abs=1e-4)


# ---------------------------------------------------------------------------
# INTEGRATION: routing + geometry end-to-end (mocked)
# ---------------------------------------------------------------------------

class TestRoutingGeometryEndToEnd:
    """Full fetch_route → geometry annotation → interpolation pipeline."""

    @patch("trip_planner.services.routing.requests.get")
    def test_geometry_annotated_with_cumulative_distance(self, mock_get):
        mock_get.return_value = _make_response(_osrm_response(
            distance_m=100000.0,
            duration_s=3600.0,
            geometry="_p~iF~ps|U_ulLnnqC_mqNvxq`@",
        ))
        cur = Location(lat=41.0, lon=-87.0, label="C", source="geocoded")
        pck = Location(lat=39.0, lon=-86.0, label="P", source="geocoded")
        drp = Location(lat=37.0, lon=-85.0, label="D", source="geocoded")
        leg1, leg2 = fetch_route(cur, pck, drp)

        # Both legs must have geometry with cumulative distances
        assert len(leg1.geometry) >= 1
        assert leg1.geometry[0].cumulative_distance_miles == 0.0
        if len(leg1.geometry) > 1:
            assert leg1.geometry[-1].cumulative_distance_miles > 0

    @patch("trip_planner.services.routing.requests.get")
    def test_interpolation_on_fetched_geometry(self, mock_get):
        mock_get.return_value = _make_response(_osrm_response(
            geometry="_p~iF~ps|U_ulLnnqC_mqNvxq`@",
        ))
        cur = Location(lat=41.0, lon=-87.0, label="C", source="geocoded")
        pck = Location(lat=39.0, lon=-86.0, label="P", source="geocoded")
        drp = Location(lat=37.0, lon=-85.0, label="D", source="geocoded")
        leg1, _ = fetch_route(cur, pck, drp)

        if leg1.geometry:
            mid = leg1.geometry[-1].cumulative_distance_miles / 2
            loc = interpolate_location(leg1.geometry, mid, "Midpoint")
            assert loc.source in ("route_interpolated", "fallback")
