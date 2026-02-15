"""
OpenRouteService HTTP client.

Single class that handles both geocoding and directions.
All responses are cached in Redis to avoid burning API quota
on repeated queries (2,000 directions/day on free tier).
"""

import hashlib
import json
import logging

import requests
from django.conf import settings
from django.core.cache import cache

from apps.route.dataclasses import Coordinates
from apps.route.exceptions import GeocodingError, RoutingError

logger = logging.getLogger(__name__)

# Cache TTLs
GEOCODE_CACHE_TTL = 60 * 60 * 24  # 24 hours -- city names don't move
DIRECTIONS_CACHE_TTL = 60 * 60     # 1 hour -- routes are stable


class ORSClient:
    """
    HTTP client for the OpenRouteService API.

    Provides geocoding (location string -> coordinates) and
    directions (start/end coordinates -> route geometry).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or settings.ORS_API_KEY
        self.base_url = (base_url or settings.ORS_BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": self.api_key,
        })

    def geocode(self, location: str) -> Coordinates:
        """
        Resolve a location string (e.g., "New York, NY") to coordinates.

        Uses ORS Pelias geocode search endpoint. Results are cached.
        Raises GeocodingError if the location cannot be resolved.
        """
        cache_key = f"ors:geocode:{self._hash(location.lower().strip())}"
        cached = cache.get(cache_key)
        if cached:
            logger.debug(f"Geocode cache hit: {location}")
            return Coordinates(**cached)

        url = f"{self.base_url}/geocode/search"
        params = {
            "api_key": self.api_key,
            "text": location,
            "boundary.country": "US",
            "size": 1,
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise GeocodingError(location, detail=str(e))

        data = response.json()
        features = data.get("features", [])
        if not features:
            raise GeocodingError(location, detail="No results found.")

        coords = features[0]["geometry"]["coordinates"]
        # ORS returns [lon, lat]
        result = Coordinates(lat=coords[1], lon=coords[0])

        cache.set(cache_key, {"lat": result.lat, "lon": result.lon}, GEOCODE_CACHE_TTL)
        logger.info(f"Geocoded '{location}' -> ({result.lat}, {result.lon})")
        return result

    def get_directions(
        self,
        start: Coordinates,
        end: Coordinates,
        alternative_routes: dict | None = None,
    ) -> dict:
        """
        Fetch driving directions between two points.

        Makes a single POST to ORS directions endpoint requesting
        GeoJSON response with full geometry. Results are cached.

        When ``alternative_routes`` is requested but ORS rejects it
        (e.g., the free tier limits alternatives to routes < 100 km,
        or target_count exceeds the server max of 3), the client
        automatically retries *without* alternatives so the request
        still succeeds. This costs one extra API call in that edge
        case, but keeps the caller unaware of the limitation.

        Args:
            start: Origin coordinates.
            end: Destination coordinates.
            alternative_routes: Optional dict requesting alternative
                routes from ORS, e.g.
                ``{"target_count": 3, "share_factor": 0.6,
                   "weight_factor": 1.4}``.
                ORS returns as many distinct routes as it can find.
                All routes are returned in the same single API call.

                NOTE: The 2 geocode calls that precede this are only
                needed when the caller provides text locations. If
                coordinates are supplied directly, this is the *only*
                ORS call required.

        Returns:
            Raw GeoJSON FeatureCollection dict from ORS. When
            alternative_routes is set and ORS supports it, ``features``
            may contain multiple route Features.

        Raises:
            RoutingError on failure.
        """
        # Cache key includes alt flag so alt/non-alt don't collide
        alt_tag = "alt" if alternative_routes else "single"
        cache_key = (
            f"ors:directions:{alt_tag}:"
            f"{self._hash(f'{start.lat},{start.lon}:{end.lat},{end.lon}')}"
        )
        cached = cache.get(cache_key)
        if cached:
            logger.debug("Directions cache hit")
            return cached

        url = f"{self.base_url}/v2/directions/driving-car/geojson"
        body: dict = {
            "coordinates": [
                start.as_ors_pair(),
                end.as_ors_pair(),
            ],
        }

        if alternative_routes:
            body["alternative_routes"] = alternative_routes

        headers = {
            "Accept": "application/json, application/geo+json",
            "Content-Type": "application/json",
        }

        try:
            response = self.session.post(url, json=body, headers=headers, timeout=30)
            response.raise_for_status()
        except requests.HTTPError as exc:
            # ORS rejects alternative_routes for routes longer than ~100 km
            # (error 2004) or if target_count exceeds the server max (error
            # 2003). Retry without alternatives so the caller still gets a
            # single-route result.
            if alternative_routes:
                ors_detail = ""
                try:
                    ors_detail = response.json().get("error", {}).get("message", "")
                except Exception:
                    ors_detail = response.text[:200]

                logger.warning(
                    "ORS rejected alternative_routes "
                    f"(HTTP {response.status_code}: {ors_detail}). "
                    "Retrying without alternatives."
                )
                body.pop("alternative_routes", None)
                try:
                    response = self.session.post(
                        url, json=body, headers=headers, timeout=30,
                    )
                    response.raise_for_status()
                except requests.RequestException as e:
                    raise RoutingError(detail=str(e))
            else:
                raise RoutingError(detail=f"ORS HTTP {response.status_code}")
        except requests.RequestException as e:
            raise RoutingError(detail=str(e))

        data = response.json()

        if "error" in data:
            raise RoutingError(detail=data.get("error", {}).get("message", str(data)))

        features = data.get("features", [])
        if not features:
            raise RoutingError(detail="No route found between the given locations.")

        cache.set(cache_key, data, DIRECTIONS_CACHE_TTL)
        logger.info(
            f"Route fetched: {start.lat},{start.lon} -> {end.lat},{end.lon} "
            f"({len(features)} route(s))"
        )
        return data

    @staticmethod
    def _hash(value: str) -> str:
        """Create a short, stable hash for cache keys."""
        return hashlib.md5(value.encode()).hexdigest()[:12]
