"""
Tests for the route geometry decoder.
"""

import pytest

from apps.route.services.route_decoder import decode_route, decode_all_routes, _haversine_miles
from apps.route.dataclasses import Coordinates


class TestDecodeRoute:
    """Tests for decode_route function."""

    def test_decodes_ors_geojson(self, sample_ors_directions_response):
        result = decode_route(sample_ors_directions_response)

        assert result.distance_meters == 800000
        assert result.duration_seconds == 28800
        assert len(result.coordinates) == 6
        assert result.coordinates[0].lat == pytest.approx(40.7128)
        assert result.coordinates[0].lon == pytest.approx(-74.006)
        assert len(result.cumulative_distances_miles) == 6
        assert result.cumulative_distances_miles[0] == 0.0
        # Each subsequent distance should be greater
        for i in range(1, len(result.cumulative_distances_miles)):
            assert result.cumulative_distances_miles[i] > result.cumulative_distances_miles[i - 1]

    def test_distance_miles_property(self, sample_ors_directions_response):
        result = decode_route(sample_ors_directions_response)
        # 800000 meters ~= 497 miles
        assert 490 < result.distance_miles < 510

    def test_duration_hours_property(self, sample_ors_directions_response):
        result = decode_route(sample_ors_directions_response)
        assert result.duration_hours == pytest.approx(8.0)


class TestDecodeAllRoutes:
    """Tests for decode_all_routes handling multiple features."""

    def test_single_feature(self, sample_ors_directions_response):
        """Single-feature response should return list with one RouteResult."""
        routes = decode_all_routes(sample_ors_directions_response)
        assert len(routes) == 1
        assert routes[0].distance_meters == 800000

    def test_multiple_features(self, sample_ors_directions_response):
        """Multiple features should each decode into a RouteResult."""
        # Create a second feature (shorter alternative route)
        alt_feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [-74.006, 40.7128],
                    [-78.0, 40.3],
                    [-84.0, 39.7],
                ],
            },
            "properties": {
                "summary": {
                    "distance": 700000,
                    "duration": 25200,
                },
                "segments": [],
            },
        }
        multi_response = {
            "type": "FeatureCollection",
            "features": [
                sample_ors_directions_response["features"][0],
                alt_feature,
            ],
        }

        routes = decode_all_routes(multi_response)

        assert len(routes) == 2
        assert routes[0].distance_meters == 800000
        assert routes[1].distance_meters == 700000
        # Each should have its own coordinates
        assert len(routes[0].coordinates) == 6
        assert len(routes[1].coordinates) == 3

    def test_empty_features_raises(self):
        """Empty features list should raise ValueError."""
        with pytest.raises(ValueError, match="no route features"):
            decode_all_routes({"features": []})

    def test_decode_route_backward_compat(self, sample_ors_directions_response):
        """decode_route() should still return first route only."""
        single = decode_route(sample_ors_directions_response)
        multi = decode_all_routes(sample_ors_directions_response)
        assert single.distance_meters == multi[0].distance_meters


class TestHaversine:
    """Tests for the Haversine distance function."""

    def test_known_distance(self):
        """NYC to LA is roughly 2,450 miles."""
        nyc = Coordinates(lat=40.7128, lon=-74.0060)
        la = Coordinates(lat=34.0522, lon=-118.2437)
        dist = _haversine_miles(nyc, la)
        assert 2400 < dist < 2500

    def test_same_point_is_zero(self):
        point = Coordinates(lat=40.0, lon=-80.0)
        assert _haversine_miles(point, point) == pytest.approx(0.0)
