"""
Station repository -- encapsulates all spatial database queries.

Separates PostGIS query logic from business logic so the optimizer
doesn't need to know about Django ORM or SQL. Also makes it easy
to swap the data source (e.g., Elasticsearch geo queries) later.
"""

import logging

from django.contrib.gis.geos import LineString, Point
from django.contrib.gis.measure import D

from apps.route.dataclasses import Coordinates, StationCandidate
from apps.route.models import FuelStation
from apps.route.services.route_decoder import _haversine_miles

logger = logging.getLogger(__name__)


class StationRepository:
    """
    Repository for querying fuel stations along a route corridor.
    """

    def find_along_corridor(
        self,
        route_coords: list[Coordinates],
        cumulative_distances: list[float],
        buffer_miles: float = 25.0,
    ) -> list[StationCandidate]:
        """
        Find all fuel stations within `buffer_miles` of the route.

        Builds a LineString from route coordinates and uses PostGIS
        ST_DWithin for an indexed spatial query. Each station is then
        projected onto the route to determine its distance along the
        route (for the optimizer to reason about ordering).

        Args:
            route_coords: Ordered list of route coordinate points.
            cumulative_distances: Cumulative miles at each route point.
            buffer_miles: Search radius from the route centerline.

        Returns:
            List of StationCandidate objects sorted by distance along route.
        """
        if not route_coords:
            return []

        # Build a LineString from route coordinates (lon, lat order for PostGIS)
        line_points = [(c.lon, c.lat) for c in route_coords]
        route_line = LineString(line_points, srid=4326)

        # Spatial query: all stations within buffer_miles of the route
        stations = FuelStation.objects.filter(
            location__dwithin=(route_line, D(mi=buffer_miles)),
        ).values(
            "id", "opis_id", "name", "address", "city", "state",
            "retail_price", "location",
        )

        logger.info(f"Found {len(stations)} stations within {buffer_miles}mi corridor")

        # Project each station onto the route to get distance along route
        candidates = []
        for s in stations:
            point = s["location"]
            station_coord = Coordinates(lat=point.y, lon=point.x)

            distance_along = self._project_onto_route(
                station_coord, route_coords, cumulative_distances,
            )

            candidates.append(
                StationCandidate(
                    station_id=s["id"],
                    opis_id=s["opis_id"],
                    name=s["name"],
                    address=s["address"],
                    city=s["city"],
                    state=s["state"],
                    lat=point.y,
                    lon=point.x,
                    retail_price=float(s["retail_price"]),
                    distance_along_route_miles=distance_along,
                )
            )

        # Sort by distance along route
        candidates.sort(key=lambda c: c.distance_along_route_miles)
        return candidates

    @staticmethod
    def _project_onto_route(
        station: Coordinates,
        route_coords: list[Coordinates],
        cumulative_distances: list[float],
    ) -> float:
        """
        Find the approximate distance along the route for a station.

        Finds the nearest route coordinate point and returns its
        cumulative distance. This is an O(n) scan over sampled route
        points -- acceptable since we do it once per corridor query,
        not per request.

        For very long routes (10K+ points), we could optimize with
        a spatial index or binary search, but for typical US routes
        (2K-5K points) this is fast enough (~1ms).
        """
        # Sample route points to avoid O(n*m) for many stations
        # Use every 10th point for routes > 200 points
        step = max(1, len(route_coords) // 200)
        sampled_indices = list(range(0, len(route_coords), step))
        if sampled_indices[-1] != len(route_coords) - 1:
            sampled_indices.append(len(route_coords) - 1)

        min_dist = float("inf")
        best_idx = 0

        for idx in sampled_indices:
            d = _haversine_miles(station, route_coords[idx])
            if d < min_dist:
                min_dist = d
                best_idx = idx

        return cumulative_distances[best_idx]
