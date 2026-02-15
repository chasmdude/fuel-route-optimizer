"""
Integration tests for the route API endpoint.

Mocks external ORS calls and seeds real fuel stations in the
test database to verify the full request/response cycle.
"""

import pytest
import responses
from django.test import override_settings
from rest_framework.test import APIClient

from apps.route.dataclasses import Coordinates


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestRouteView:
    """Integration tests for POST /api/v1/route/."""

    def test_missing_fields_returns_400(self, api_client):
        """Missing start or finish should return 400."""
        response = api_client.post(
            "/api/v1/route/",
            data={"start": "New York, NY"},
            format="json",
        )
        assert response.status_code == 400

    def test_empty_body_returns_400(self, api_client):
        """Empty request body should return 400."""
        response = api_client.post(
            "/api/v1/route/",
            data={},
            format="json",
        )
        assert response.status_code == 400

    @responses.activate
    @override_settings(ORS_API_KEY="test-key", ORS_BASE_URL="https://api.ors.test")
    def test_geocoding_failure_returns_structured_error(self, api_client):
        """When ORS geocoding fails, should return structured 400."""
        responses.add(
            responses.GET,
            "https://api.ors.test/geocode/search",
            json={"features": []},
            status=200,
        )

        response = api_client.post(
            "/api/v1/route/",
            data={"start": "Faketown, XX", "finish": "Nowhere, YY"},
            format="json",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == "GEOCODING_FAILED"
        assert "Faketown, XX" in data["error"]["message"]

    @responses.activate
    @override_settings(
        ORS_API_KEY="test-key",
        ORS_BASE_URL="https://api.ors.test",
        VEHICLE_RANGE_MILES=500,
        VEHICLE_MPG=10,
        CORRIDOR_BUFFER_MILES=50.0,
    )
    def test_full_request_returns_expected_shape(
        self,
        api_client,
        create_fuel_station,
        sample_ors_geocode_response,
        sample_ors_directions_response,
    ):
        """Full end-to-end: mock ORS, seed stations, verify response shape."""
        # Mock geocode for start
        responses.add(
            responses.GET,
            "https://api.ors.test/geocode/search",
            json=sample_ors_geocode_response,
            status=200,
        )
        # Mock geocode for finish
        responses.add(
            responses.GET,
            "https://api.ors.test/geocode/search",
            json={
                "features": [{
                    "geometry": {"coordinates": [-84.0, 39.7], "type": "Point"},
                    "properties": {"label": "Destination"},
                }]
            },
            status=200,
        )
        # Mock directions
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json=sample_ors_directions_response,
            status=200,
        )

        # Seed stations along the mocked route
        create_fuel_station(
            opis_id=1001, name="Cheap Station",
            lat=40.3, lon=-78.0, retail_price=2.89,
        )
        create_fuel_station(
            opis_id=1002, name="Pricey Station",
            lat=40.1, lon=-80.0, retail_price=3.50,
        )

        response = api_client.post(
            "/api/v1/route/",
            data={"start": "New York, NY", "finish": "Columbus, OH"},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "route" in data
        assert "fuel_stops" in data
        assert "summary" in data

        route = data["route"]
        assert "distance_miles" in route
        assert "duration_hours" in route
        assert "map_url" in route
        assert "geometry" in route
        assert route["map_url"].startswith("https://maps.openrouteservice.org")

        summary = data["summary"]
        assert summary["mpg"] == 10
        assert summary["vehicle_range_miles"] == 500
        assert summary["total_fuel_cost"] >= 0
        assert summary["total_gallons"] >= 0
        assert summary["routes_evaluated"] >= 1

    @responses.activate
    @override_settings(
        ORS_API_KEY="test-key",
        ORS_BASE_URL="https://api.ors.test",
        VEHICLE_RANGE_MILES=500,
        VEHICLE_MPG=10,
        CORRIDOR_BUFFER_MILES=50.0,
        INITIAL_FUEL_FRACTION=1.0,
    )
    def test_evaluates_multiple_alternative_routes(
        self,
        api_client,
        create_fuel_station,
        sample_ors_geocode_response,
    ):
        """When ORS returns multiple route alternatives, the view should
        evaluate all of them and pick the cheapest fuel cost."""
        # Mock geocode for start
        responses.add(
            responses.GET,
            "https://api.ors.test/geocode/search",
            json=sample_ors_geocode_response,
            status=200,
        )
        # Mock geocode for finish
        responses.add(
            responses.GET,
            "https://api.ors.test/geocode/search",
            json={
                "features": [{
                    "geometry": {"coordinates": [-84.0, 39.7], "type": "Point"},
                    "properties": {"label": "Destination"},
                }]
            },
            status=200,
        )

        # Build a multi-route ORS response with 3 alternatives.
        # Route 1: main corridor (40.x, -74 to -84)
        # Route 2: slightly north corridor (41.x) -- different stations reachable
        # Route 3: slightly south corridor (39.x) -- different stations reachable
        def _make_feature(lats, distance_m):
            lons = [-74.006, -76.0, -78.0, -80.0, -82.0, -84.0]
            return {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for lon, lat in zip(lons, lats)],
                },
                "properties": {
                    "summary": {"distance": distance_m, "duration": 28800},
                    "segments": [],
                },
            }

        multi_route_response = {
            "type": "FeatureCollection",
            "features": [
                _make_feature(
                    [40.7128, 40.5, 40.3, 40.1, 39.9, 39.7],
                    800000,
                ),
                _make_feature(
                    [40.7128, 41.0, 41.2, 41.0, 40.5, 39.7],
                    850000,  # slightly longer
                ),
                _make_feature(
                    [40.7128, 40.0, 39.5, 39.3, 39.5, 39.7],
                    820000,
                ),
            ],
        }

        # Mock directions returning 3 alternatives
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json=multi_route_response,
            status=200,
        )

        # Seed stations reachable from route 1 corridor (~40.x lat)
        create_fuel_station(
            opis_id=2001, name="Route1 Station",
            lat=40.3, lon=-78.0, retail_price=3.50,
        )
        # Seed a cheaper station on route 3 corridor (~39.x lat)
        create_fuel_station(
            opis_id=2002, name="Route3 Cheap Station",
            lat=39.4, lon=-78.0, retail_price=2.50,
        )

        response = api_client.post(
            "/api/v1/route/",
            data={"start": "New York, NY", "finish": "Columbus, OH"},
            format="json",
        )

        assert response.status_code == 200
        data = response.json()

        # Must have evaluated all 3 routes
        assert data["summary"]["routes_evaluated"] == 3
