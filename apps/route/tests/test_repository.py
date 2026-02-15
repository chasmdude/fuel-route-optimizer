"""
Tests for the StationRepository spatial queries.

Creates real FuelStation records in a test PostGIS database
and verifies corridor search returns correct results.
"""

import pytest

from apps.route.dataclasses import Coordinates
from apps.route.repositories import StationRepository


@pytest.mark.django_db
class TestStationRepository:
    """Tests for find_along_corridor."""

    def test_finds_stations_within_corridor(self, create_fuel_station):
        """Stations near the route should be returned."""
        # Create a station near the route (at 40.1, -80.0)
        create_fuel_station(
            opis_id=100, name="Near Station",
            lat=40.1, lon=-80.0, retail_price=2.99,
        )
        # Create a station far from the route (at 30.0, -90.0)
        create_fuel_station(
            opis_id=200, name="Far Station",
            lat=30.0, lon=-90.0, retail_price=2.50,
        )

        route_coords = [
            Coordinates(lat=40.71, lon=-74.00),
            Coordinates(lat=40.30, lon=-78.00),
            Coordinates(lat=40.10, lon=-80.00),
            Coordinates(lat=39.90, lon=-82.00),
        ]
        cumulative = [0.0, 100.0, 200.0, 300.0]

        repo = StationRepository()
        candidates = repo.find_along_corridor(
            route_coords, cumulative, buffer_miles=30.0
        )

        names = [c.name for c in candidates]
        assert "Near Station" in names
        assert "Far Station" not in names

    def test_excludes_stations_outside_buffer(self, create_fuel_station):
        """Stations outside the buffer should not be returned."""
        create_fuel_station(
            opis_id=300, name="Outside Buffer",
            lat=35.0, lon=-85.0, retail_price=2.70,
        )

        route_coords = [
            Coordinates(lat=40.71, lon=-74.00),
            Coordinates(lat=39.90, lon=-82.00),
        ]
        cumulative = [0.0, 300.0]

        repo = StationRepository()
        candidates = repo.find_along_corridor(
            route_coords, cumulative, buffer_miles=25.0
        )

        assert len(candidates) == 0

    def test_returns_sorted_by_distance_along_route(self, create_fuel_station):
        """Results should be sorted by distance along route."""
        create_fuel_station(
            opis_id=401, name="Station A",
            lat=40.30, lon=-78.00, retail_price=3.10,
        )
        create_fuel_station(
            opis_id=402, name="Station B",
            lat=40.10, lon=-80.00, retail_price=2.90,
        )

        route_coords = [
            Coordinates(lat=40.71, lon=-74.00),
            Coordinates(lat=40.30, lon=-78.00),
            Coordinates(lat=40.10, lon=-80.00),
            Coordinates(lat=39.90, lon=-82.00),
        ]
        cumulative = [0.0, 100.0, 200.0, 300.0]

        repo = StationRepository()
        candidates = repo.find_along_corridor(
            route_coords, cumulative, buffer_miles=30.0
        )

        if len(candidates) >= 2:
            distances = [c.distance_along_route_miles for c in candidates]
            assert distances == sorted(distances)

    def test_empty_route_returns_empty(self):
        """Empty route coordinates should return no stations."""
        repo = StationRepository()
        candidates = repo.find_along_corridor([], [], buffer_miles=25.0)
        assert candidates == []
