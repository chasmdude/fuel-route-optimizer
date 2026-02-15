"""
Tests for the map URL builder.
"""

from apps.route.dataclasses import Coordinates, SelectedStop
from apps.route.services.map_url_builder import MapURLBuilder


class TestMapURLBuilder:
    """Tests for MapURLBuilder.build_url."""

    def test_basic_url_structure(self):
        builder = MapURLBuilder()
        start = Coordinates(lat=40.7128, lon=-74.006)
        end = Coordinates(lat=34.0522, lon=-118.2437)

        url = builder.build_url(start, end)

        assert url.startswith("https://maps.openrouteservice.org/directions")
        assert "40.7128" in url
        assert "-74.006" in url
        assert "34.0522" in url
        assert "-118.2437" in url
        assert "k2=mi" in url

    def test_includes_fuel_stop_waypoints(self):
        builder = MapURLBuilder()
        start = Coordinates(lat=40.7128, lon=-74.006)
        end = Coordinates(lat=34.0522, lon=-118.2437)
        stops = [
            SelectedStop(
                name="Test", address="", city="", state="PA",
                lat=41.02, lon=-78.43,
                price_per_gallon=2.89, gallons_filled=50,
                cost=144.5, distance_from_start_miles=280,
            ),
        ]

        url = builder.build_url(start, end, stops=stops)

        # Waypoint should appear between start and end in the 'a' param
        assert "41.02,-78.43" in url

    def test_no_stops_only_start_end(self):
        builder = MapURLBuilder()
        start = Coordinates(lat=40.0, lon=-74.0)
        end = Coordinates(lat=34.0, lon=-118.0)

        url = builder.build_url(start, end, stops=[])
        # Should contain exactly start and end
        assert "40.0,-74.0" in url
        assert "34.0,-118.0" in url
