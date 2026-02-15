"""
Domain value objects for the route optimization service.

These are plain Python dataclasses -- no Django ORM dependency.
They represent the data flowing between services and keep the
service layer decoupled from the database layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Coordinates:
    """A geographic point (WGS84)."""

    lat: float
    lon: float

    def as_ors_pair(self) -> list[float]:
        """ORS expects [lon, lat] order."""
        return [self.lon, self.lat]


@dataclass(frozen=True)
class RouteResult:
    """
    Decoded driving route from ORS.

    Attributes:
        distance_meters: Total route distance in meters.
        duration_seconds: Total route duration in seconds.
        geometry: Raw GeoJSON geometry dict (LineString).
        coordinates: Ordered list of route points.
        cumulative_distances_miles: Cumulative distance in miles at each
            coordinate index. First element is always 0.0.
    """

    distance_meters: float
    duration_seconds: float
    geometry: dict
    coordinates: list[Coordinates]
    cumulative_distances_miles: list[float]

    @property
    def distance_miles(self) -> float:
        return self.distance_meters * 0.000621371

    @property
    def duration_hours(self) -> float:
        return self.duration_seconds / 3600.0

    @property
    def total_miles(self) -> float:
        """Total route length from cumulative distances."""
        if self.cumulative_distances_miles:
            return self.cumulative_distances_miles[-1]
        return self.distance_miles


@dataclass(frozen=True)
class StationCandidate:
    """
    A fuel station projected onto the route for optimization.

    Attributes:
        station_id: Database PK of the FuelStation.
        opis_id: OPIS Truckstop ID.
        name: Station name.
        address: Station address.
        city: City name.
        state: Two-letter state code.
        lat: Latitude.
        lon: Longitude.
        retail_price: Price per gallon (USD).
        distance_along_route_miles: How far along the route this station is.
    """

    station_id: int
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    lat: float
    lon: float
    retail_price: float
    distance_along_route_miles: float


@dataclass(frozen=True)
class SelectedStop:
    """A fuel stop chosen by the optimizer."""

    name: str
    address: str
    city: str
    state: str
    lat: float
    lon: float
    price_per_gallon: float
    gallons_filled: float
    cost: float
    distance_from_start_miles: float


@dataclass
class FuelPlan:
    """Complete fuel plan for a route."""

    stops: list[SelectedStop] = field(default_factory=list)
    total_cost: float = 0.0
    total_gallons: float = 0.0

    @property
    def number_of_stops(self) -> int:
        return len(self.stops)
