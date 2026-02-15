"""
API views for route optimization.

The view is intentionally thin -- it validates input, orchestrates
service calls, and serializes the output. All business logic lives
in the service layer.

API call breakdown (3 total, 2 removable):
  1. Geocode start  -- removable if caller passes coordinates directly
  2. Geocode end    -- removable if caller passes coordinates directly
  3. Directions     -- the only *required* ORS call; includes up to 3
                       alternative routes in the same single request
"""

import logging

from django.conf import settings
from django.db import connection
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.route.exceptions import GeocodingError, OptimizationError, RoutingError
from apps.route.repositories import StationRepository
from apps.route.serializers import RouteRequestSerializer, RouteResponseSerializer
from apps.route.services.fuel_optimizer import FuelOptimizer
from apps.route.services.map_url_builder import MapURLBuilder
from apps.route.services.ors_client import ORSClient
from apps.route.services.route_decoder import decode_all_routes

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """
    GET /api/v1/health/

    Simple liveness/readiness probe. Verifies the database connection
    is alive. Returns 200 if healthy, 503 if not.
    """

    def get(self, request: Request) -> Response:
        try:
            connection.ensure_connection()
            return Response({"status": "ok"}, status=status.HTTP_200_OK)
        except Exception:
            return Response(
                {"status": "error", "detail": "Database unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


# ORS alternative routes configuration.
# target_count: ORS free tier caps this at 3 (returns up to 3 distinct routes).
# share_factor: how much routes may overlap (0.6 = up to 60% shared).
# weight_factor: how much longer alternatives may be vs optimal (1.4 = 40%).
# NOTE: ORS also enforces a ~100 km route-length limit for alternatives;
# for longer routes the client falls back to a single route automatically.
ALTERNATIVE_ROUTES_PARAMS = {
    "target_count": 3,
    "share_factor": 0.6,
    "weight_factor": 1.4,
}


class RouteView(APIView):
    """
    POST /api/v1/route/

    Accepts start and finish locations, returns the optimal driving
    route with cost-effective fuel stops, a clickable map URL, and
    total fuel cost summary.

    Evaluates up to 3 alternative routes from ORS (in a single API
    call) and picks the one with the lowest total fuel cost.
    """

    def post(self, request: Request) -> Response:
        # 1. Validate input
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        start_location = serializer.validated_data["start"]
        finish_location = serializer.validated_data["finish"]

        try:
            # 2. Geocode locations (2 ORS calls -- removable if caller
            #    supplies coordinates directly in a future API version)
            ors = ORSClient()
            start_coords = ors.geocode(start_location)
            end_coords = ors.geocode(finish_location)

            # 3. Get driving directions with alternatives (1 ORS call)
            directions_geojson = ors.get_directions(
                start_coords,
                end_coords,
                alternative_routes=ALTERNATIVE_ROUTES_PARAMS,
            )

            # 4. Decode ALL route alternatives
            all_routes = decode_all_routes(directions_geojson)
            routes_evaluated = len(all_routes)

            logger.info(
                f"ORS returned {routes_evaluated} route alternative(s)"
            )

            # 5. Evaluate each route: find stations, run optimizer, track cost
            optimizer = FuelOptimizer(
                station_repo=StationRepository(),
            )

            best_route = None
            best_plan = None
            best_cost = float("inf")
            errors: list[str] = []

            for idx, route in enumerate(all_routes):
                try:
                    fuel_plan = optimizer.optimize(
                        route=route,
                        range_miles=settings.VEHICLE_RANGE_MILES,
                        mpg=settings.VEHICLE_MPG,
                        corridor_buffer_miles=settings.CORRIDOR_BUFFER_MILES,
                        initial_fuel_fraction=settings.INITIAL_FUEL_FRACTION,
                    )

                    logger.info(
                        f"Route {idx + 1}/{routes_evaluated}: "
                        f"{route.total_miles:.0f}mi, "
                        f"{fuel_plan.number_of_stops} stops, "
                        f"${fuel_plan.total_cost:.2f}"
                    )

                    if fuel_plan.total_cost < best_cost:
                        best_cost = fuel_plan.total_cost
                        best_route = route
                        best_plan = fuel_plan

                except OptimizationError as e:
                    # This route has a gap too wide -- skip it, try others
                    errors.append(
                        f"Route {idx + 1}: {e}"
                    )
                    logger.warning(
                        f"Route {idx + 1}/{routes_evaluated} skipped: {e}"
                    )

            # If no route succeeded, re-raise the last error
            if best_route is None or best_plan is None:
                raise OptimizationError(
                    detail=(
                        f"All {routes_evaluated} route(s) failed optimization. "
                        f"Errors: {'; '.join(errors)}"
                    )
                )

            route = best_route
            fuel_plan = best_plan

            # 6. Build map URL
            map_builder = MapURLBuilder()
            map_url = map_builder.build_url(
                start=start_coords,
                end=end_coords,
                stops=fuel_plan.stops,
            )

            # 7. Build response
            response_data = {
                "route": {
                    "distance_miles": round(route.distance_miles, 1),
                    "duration_hours": round(route.duration_hours, 1),
                    "map_url": map_url,
                    "geometry": route.geometry,
                },
                "fuel_stops": [
                    {
                        "name": stop.name,
                        "address": stop.address,
                        "city": stop.city,
                        "state": stop.state,
                        "latitude": stop.lat,
                        "longitude": stop.lon,
                        "price_per_gallon": stop.price_per_gallon,
                        "gallons_filled": stop.gallons_filled,
                        "cost": stop.cost,
                        "distance_from_start_miles": stop.distance_from_start_miles,
                    }
                    for stop in fuel_plan.stops
                ],
                "summary": {
                    "total_fuel_cost": fuel_plan.total_cost,
                    "total_gallons": fuel_plan.total_gallons,
                    "number_of_stops": fuel_plan.number_of_stops,
                    "routes_evaluated": routes_evaluated,
                    "mpg": settings.VEHICLE_MPG,
                    "vehicle_range_miles": settings.VEHICLE_RANGE_MILES,
                },
            }

            # 8. Validate response shape (catches bugs in serialization)
            out = RouteResponseSerializer(data=response_data)
            out.is_valid(raise_exception=True)

            return Response(out.validated_data, status=status.HTTP_200_OK)

        except GeocodingError as e:
            return Response(
                {
                    "error": {
                        "code": "GEOCODING_FAILED",
                        "message": str(e),
                        "details": {"location": e.location},
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except RoutingError as e:
            return Response(
                {
                    "error": {
                        "code": "ROUTING_FAILED",
                        "message": str(e),
                        "details": {"detail": e.detail} if e.detail else {},
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except OptimizationError as e:
            return Response(
                {
                    "error": {
                        "code": "OPTIMIZATION_FAILED",
                        "message": str(e),
                        "details": {"detail": e.detail} if e.detail else {},
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception:
            logger.exception("Unexpected error in RouteView")
            return Response(
                {
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred.",
                        "details": {},
                    }
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
