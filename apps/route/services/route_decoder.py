"""
Route geometry decoder.

Converts the raw ORS GeoJSON response into a RouteResult domain
object with cumulative mile distances at each coordinate point.
"""

import math

from apps.route.dataclasses import Coordinates, RouteResult


def decode_route(ors_geojson: dict) -> RouteResult:
    """
    Decode the *first* route from an ORS GeoJSON directions response.

    This is a convenience wrapper around :func:`decode_all_routes`
    for callers that only need a single route.

    Args:
        ors_geojson: Raw GeoJSON FeatureCollection from ORS directions API.

    Returns:
        RouteResult for the first (default/optimal) route.
    """
    return decode_all_routes(ors_geojson)[0]


def decode_all_routes(ors_geojson: dict) -> list[RouteResult]:
    """
    Decode **all** routes from an ORS GeoJSON directions response.

    When ``alternative_routes`` was requested, the FeatureCollection
    may contain multiple Features -- one per route. This function
    decodes each into a RouteResult so the caller can evaluate them
    all and pick the cheapest.

    Args:
        ors_geojson: Raw GeoJSON FeatureCollection from ORS directions API.

    Returns:
        List of RouteResult objects (at least one).
    """
    features = ors_geojson.get("features", [])
    if not features:
        raise ValueError("ORS response contains no route features.")

    routes: list[RouteResult] = []
    for feature in features:
        routes.append(_decode_feature(feature))
    return routes


def _decode_feature(feature: dict) -> RouteResult:
    """Decode a single GeoJSON Feature into a RouteResult."""
    geometry = feature["geometry"]
    properties = feature["properties"]
    summary = properties["summary"]

    # ORS coordinates are [lon, lat]
    raw_coords = geometry["coordinates"]
    coordinates = [Coordinates(lat=c[1], lon=c[0]) for c in raw_coords]

    # Calculate cumulative distances in miles
    cumulative = [0.0]
    for i in range(1, len(coordinates)):
        dist = _haversine_miles(coordinates[i - 1], coordinates[i])
        cumulative.append(cumulative[-1] + dist)

    return RouteResult(
        distance_meters=summary["distance"],
        duration_seconds=summary["duration"],
        geometry=geometry,
        coordinates=coordinates,
        cumulative_distances_miles=cumulative,
    )


def _haversine_miles(a: Coordinates, b: Coordinates) -> float:
    """
    Calculate the great-circle distance between two points in miles.

    Uses the Haversine formula. Accurate enough for our purposes
    (finding which route segment a fuel station is near).
    """
    R = 3958.8  # Earth radius in miles

    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(h))
