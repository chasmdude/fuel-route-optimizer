"""
Unit tests for the ORS client.

Uses the `responses` library to mock HTTP calls -- no real
ORS API calls are made during testing.
"""

import pytest
import responses

from apps.route.dataclasses import Coordinates
from apps.route.exceptions import GeocodingError, RoutingError
from apps.route.services.ors_client import ORSClient


@pytest.fixture
def ors_client():
    return ORSClient(api_key="test-key", base_url="https://api.ors.test")


class TestORSClientGeocode:
    """Tests for the geocode method."""

    @responses.activate
    def test_geocode_returns_coordinates(self, ors_client, sample_ors_geocode_response):
        responses.add(
            responses.GET,
            "https://api.ors.test/geocode/search",
            json=sample_ors_geocode_response,
            status=200,
        )

        result = ors_client.geocode("New York, NY")

        assert isinstance(result, Coordinates)
        assert result.lat == pytest.approx(40.7128)
        assert result.lon == pytest.approx(-74.0060)

    @responses.activate
    def test_geocode_empty_results_raises(self, ors_client):
        responses.add(
            responses.GET,
            "https://api.ors.test/geocode/search",
            json={"features": []},
            status=200,
        )

        with pytest.raises(GeocodingError) as exc_info:
            ors_client.geocode("Faketown, XX")

        assert "Faketown, XX" in str(exc_info.value)

    @responses.activate
    def test_geocode_http_error_raises(self, ors_client):
        responses.add(
            responses.GET,
            "https://api.ors.test/geocode/search",
            json={"error": "rate limit"},
            status=429,
        )

        with pytest.raises(GeocodingError):
            ors_client.geocode("New York, NY")


class TestORSClientDirections:
    """Tests for the get_directions method."""

    @responses.activate
    def test_get_directions_returns_geojson(
        self, ors_client, sample_ors_directions_response
    ):
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json=sample_ors_directions_response,
            status=200,
        )

        start = Coordinates(lat=40.7128, lon=-74.0060)
        end = Coordinates(lat=34.0522, lon=-118.2437)
        result = ors_client.get_directions(start, end)

        assert result["type"] == "FeatureCollection"
        assert len(result["features"]) > 0
        assert result["features"][0]["geometry"]["type"] == "LineString"

    @responses.activate
    def test_get_directions_no_route_raises(self, ors_client):
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json={"features": []},
            status=200,
        )

        start = Coordinates(lat=40.7128, lon=-74.0060)
        end = Coordinates(lat=34.0522, lon=-118.2437)

        with pytest.raises(RoutingError):
            ors_client.get_directions(start, end)

    @responses.activate
    def test_get_directions_http_error_raises(self, ors_client):
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json={"error": "server error"},
            status=500,
        )

        start = Coordinates(lat=40.7128, lon=-74.0060)
        end = Coordinates(lat=34.0522, lon=-118.2437)

        with pytest.raises(RoutingError):
            ors_client.get_directions(start, end)

    @responses.activate
    def test_get_directions_with_alternative_routes(
        self, ors_client, sample_ors_directions_response,
    ):
        """alternative_routes param should be included in POST body."""
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json=sample_ors_directions_response,
            status=200,
        )

        start = Coordinates(lat=40.7128, lon=-74.0060)
        end = Coordinates(lat=34.0522, lon=-118.2437)
        alt_params = {"target_count": 3, "share_factor": 0.6, "weight_factor": 1.4}

        result = ors_client.get_directions(start, end, alternative_routes=alt_params)

        assert result["type"] == "FeatureCollection"
        # Verify the POST body included alternative_routes
        import json
        sent_body = json.loads(responses.calls[0].request.body)
        assert "alternative_routes" in sent_body
        assert sent_body["alternative_routes"]["target_count"] == 3

    @responses.activate
    def test_alt_routes_fallback_on_ors_rejection(
        self, ors_client, sample_ors_directions_response,
    ):
        """When ORS rejects alternative_routes (e.g., distance limit),
        the client should retry without alternatives and succeed."""
        # First call: 400 (ORS rejects alternatives)
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json={
                "error": {
                    "code": 2004,
                    "message": (
                        "The approximated route distance must not be greater "
                        "than 100000.0 meters for use with the alternative "
                        "Routes algorithm."
                    ),
                }
            },
            status=400,
        )
        # Second call: 200 (without alternatives)
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json=sample_ors_directions_response,
            status=200,
        )

        start = Coordinates(lat=40.7128, lon=-74.0060)
        end = Coordinates(lat=34.0522, lon=-118.2437)
        alt_params = {"target_count": 3, "share_factor": 0.6, "weight_factor": 1.4}

        result = ors_client.get_directions(start, end, alternative_routes=alt_params)

        # Should succeed via fallback
        assert result["type"] == "FeatureCollection"
        # Two API calls made (first rejected, second succeeded)
        assert len(responses.calls) == 2
        # Second call should NOT have alternative_routes in body
        import json
        retry_body = json.loads(responses.calls[1].request.body)
        assert "alternative_routes" not in retry_body

    @responses.activate
    def test_alt_and_single_cache_keys_differ(
        self, ors_client, sample_ors_directions_response,
    ):
        """Alt-routes and single-route should use different cache keys."""
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json=sample_ors_directions_response,
            status=200,
        )
        responses.add(
            responses.POST,
            "https://api.ors.test/v2/directions/driving-car/geojson",
            json=sample_ors_directions_response,
            status=200,
        )

        start = Coordinates(lat=40.7128, lon=-74.0060)
        end = Coordinates(lat=34.0522, lon=-118.2437)

        # First call: no alternatives
        ors_client.get_directions(start, end)
        # Second call: with alternatives (should NOT be cached from first)
        ors_client.get_directions(start, end, alternative_routes={"target_count": 3})

        # Both calls should have hit the API (different cache keys)
        assert len(responses.calls) == 2
