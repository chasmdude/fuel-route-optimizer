"""
Shared test fixtures for the route app.
"""

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache as django_cache

from apps.route.dataclasses import Coordinates, RouteResult
from apps.route.models import FuelStation


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear Django cache before each test to prevent stale ORS data."""
    django_cache.clear()
    yield
    django_cache.clear()


@pytest.fixture
def sample_coordinates():
    """New York, NY coordinates."""
    return Coordinates(lat=40.7128, lon=-74.0060)


@pytest.fixture
def sample_end_coordinates():
    """Los Angeles, CA coordinates."""
    return Coordinates(lat=34.0522, lon=-118.2437)


@pytest.fixture
def sample_route_result():
    """
    A simple 600-mile route with 6 evenly spaced coordinate points.
    Each point is ~100 miles apart along a roughly east-west line.
    """
    coords = [
        Coordinates(lat=40.71, lon=-74.00),   # NYC area
        Coordinates(lat=40.50, lon=-76.00),   # ~100mi west
        Coordinates(lat=40.30, lon=-78.00),   # ~200mi
        Coordinates(lat=40.10, lon=-80.00),   # ~300mi
        Coordinates(lat=39.90, lon=-82.00),   # ~400mi
        Coordinates(lat=39.70, lon=-84.00),   # ~500mi
        Coordinates(lat=39.50, lon=-86.00),   # ~600mi
    ]
    cumulative = [0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0]

    return RouteResult(
        distance_meters=600 * 1609.34,  # ~600 miles in meters
        duration_seconds=9 * 3600,       # ~9 hours
        geometry={
            "type": "LineString",
            "coordinates": [[c.lon, c.lat] for c in coords],
        },
        coordinates=coords,
        cumulative_distances_miles=cumulative,
    )


@pytest.fixture
def create_fuel_station(db):
    """Factory fixture to create FuelStation instances."""
    def _create(
        opis_id,
        name="Test Station",
        city="Test City",
        state="OH",
        retail_price=3.00,
        lat=40.0,
        lon=-82.0,
        address="Test Address",
    ):
        return FuelStation.objects.create(
            opis_id=opis_id,
            name=name,
            address=address,
            city=city,
            state=state,
            retail_price=retail_price,
            location=Point(lon, lat, srid=4326),
        )
    return _create


@pytest.fixture
def sample_ors_geocode_response():
    """Mock ORS geocode response for New York, NY."""
    return {
        "features": [
            {
                "geometry": {
                    "coordinates": [-74.0060, 40.7128],
                    "type": "Point",
                },
                "properties": {
                    "label": "New York, NY, USA",
                },
            }
        ],
    }


@pytest.fixture
def sample_ors_directions_response():
    """Mock ORS directions GeoJSON response."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-74.006, 40.7128],
                        [-76.0, 40.5],
                        [-78.0, 40.3],
                        [-80.0, 40.1],
                        [-82.0, 39.9],
                        [-84.0, 39.7],
                    ],
                },
                "properties": {
                    "summary": {
                        "distance": 800000,   # ~500 miles in meters
                        "duration": 28800,     # 8 hours
                    },
                    "segments": [],
                },
            }
        ],
    }
