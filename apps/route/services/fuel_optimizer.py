"""
Fuel stop optimization engine.

Uses the Strategy pattern so the optimization algorithm can be
swapped without touching the orchestration logic.

Two strategies are available:

- **MinCostStrategy** (default): Globally optimal cost minimisation
  using the retroactive refueling algorithm (min-heap / priority queue).
  O(n log n) time, provably optimal for bounded-tank gas station problem.
- **MinStopsStrategy**: Minimises the number of stops by preferring
  stations in the far half of the reachable window, filling to full
  each time.
"""

import heapq
import logging
from typing import Protocol

from apps.route.dataclasses import (
    FuelPlan,
    RouteResult,
    SelectedStop,
    StationCandidate,
)
from apps.route.exceptions import OptimizationError
from apps.route.repositories import StationRepository

logger = logging.getLogger(__name__)


class OptimizationStrategy(Protocol):
    """
    Protocol for fuel stop selection algorithms.

    Implement this to add new optimization strategies (e.g., DP-based,
    LP-based, or multi-objective). The FuelOptimizer will call
    select_stops() without knowing the concrete implementation.
    """

    def select_stops(
        self,
        candidates: list[StationCandidate],
        route: RouteResult,
        range_miles: int,
        mpg: int,
        initial_fuel_fraction: float = 1.0,
    ) -> list[SelectedStop]: ...


# ---------------------------------------------------------------------------
# Strategy 1: MinCostStrategy (default) -- minimises total fuel cost
# ---------------------------------------------------------------------------


class MinCostStrategy:
    """
    Globally optimal cost-minimising fuel optimization using the
    *retroactive refueling* algorithm (min-heap / priority queue).

    Complexity: O(n log n)  where n = number of candidate stations.

    Algorithm:
    1. Sort stations by distance along route.
    2. Append a virtual sentinel at the destination (price=0).
    3. Walk through waypoints in order, consuming fuel per segment.
    4. At each waypoint, record how much spare tank capacity existed
       when we *passed* the previous station (push to a min-heap
       keyed by price).
    5. Whenever fuel drops below zero (we can't reach the next
       waypoint), pop the cheapest entry from the heap and
       "retroactively" buy fuel there -- just enough to stay
       non-negative, or the full available capacity, whichever is
       smaller.
    6. Collect all stations where we actually bought fuel.

    Key insight: we never buy expensive fuel when cheaper fuel was
    available at a station we already passed with spare tank space.
    This is the provably optimal solution for the bounded-tank
    minimum-cost gas station problem.
    """

    def select_stops(
        self,
        candidates: list[StationCandidate],
        route: RouteResult,
        range_miles: int,
        mpg: int,
        initial_fuel_fraction: float = 1.0,
    ) -> list[SelectedStop]:
        total_distance = route.total_miles
        tank_cap = range_miles / mpg  # gallons

        # ---- Edge cases ----
        if not candidates:
            if total_distance <= range_miles * initial_fuel_fraction:
                return []
            raise OptimizationError(
                detail="No fuel stations found along the route corridor."
            )

        # Filter & sort candidates by position on route
        valid = sorted(
            [c for c in candidates if 0 < c.distance_along_route_miles < total_distance],
            key=lambda c: c.distance_along_route_miles,
        )

        if not valid and total_distance <= range_miles * initial_fuel_fraction:
            return []
        if not valid:
            raise OptimizationError(
                detail="Route exceeds vehicle range but no fuel stations found."
            )

        # ---- Build waypoints: origin + stations + destination sentinel ----
        # Each waypoint: (distance_miles, station_or_None)
        waypoints: list[tuple[float, StationCandidate | None]] = []
        for s in valid:
            waypoints.append((s.distance_along_route_miles, s))
        # Sentinel at destination -- price 0, never actually "selected"
        waypoints.append((total_distance, None))

        fuel = tank_cap * initial_fuel_fraction  # gallons in tank at origin
        pos = 0.0  # current position (miles)

        # Min-heap entries: (price, available_gallons, station_index_in_valid)
        heap: list[tuple[float, float, int]] = []
        # Track how much fuel we retroactively buy at each station index
        purchases: dict[int, float] = {}

        for wp_idx, (wp_dist, wp_station) in enumerate(waypoints):
            # Consume fuel to reach this waypoint
            segment_miles = wp_dist - pos
            fuel -= segment_miles / mpg

            # Before consuming, push the *previous* station's spare capacity
            # onto the heap (if there was a previous station waypoint).
            if wp_idx > 0:
                prev_dist, prev_station = waypoints[wp_idx - 1]
                if prev_station is not None:
                    # Fuel level when we were AT the previous station
                    fuel_at_prev = fuel + segment_miles / mpg
                    spare = tank_cap - fuel_at_prev
                    if spare > 1e-9:
                        heapq.heappush(
                            heap,
                            (prev_station.retail_price, spare, wp_idx - 1),
                        )

            # If fuel is negative, retroactively buy from cheapest passed
            while fuel < -1e-9 and heap:
                price, available, st_idx = heapq.heappop(heap)
                # Buy just enough, or all available capacity
                need = -fuel
                buy = min(available, need)
                purchases[st_idx] = purchases.get(st_idx, 0.0) + buy
                fuel += buy
                # If we didn't use all available, push remainder back
                leftover = available - buy
                if leftover > 1e-9:
                    heapq.heappush(heap, (price, leftover, st_idx))

            # Still negative after exhausting heap → infeasible gap
            if fuel < -1e-9:
                raise OptimizationError(
                    detail=(
                        f"Cannot reach mile {wp_dist:.0f} from mile "
                        f"{pos:.0f}. Gap exceeds vehicle range."
                    )
                )

            pos = wp_dist

        # ---- Convert purchases to SelectedStop list ----
        selected: list[SelectedStop] = []
        for st_idx in sorted(purchases.keys()):
            _, station = waypoints[st_idx]
            if station is None:
                continue  # sentinel, shouldn't happen
            gallons = purchases[st_idx]
            if gallons < 0.01:
                continue  # skip negligible rounding artifacts
            cost = gallons * station.retail_price
            selected.append(
                SelectedStop(
                    name=station.name,
                    address=station.address,
                    city=station.city,
                    state=station.state,
                    lat=station.lat,
                    lon=station.lon,
                    price_per_gallon=station.retail_price,
                    gallons_filled=round(gallons, 2),
                    cost=round(cost, 2),
                    distance_from_start_miles=round(
                        station.distance_along_route_miles, 1
                    ),
                )
            )

        return selected


# ---------------------------------------------------------------------------
# Strategy 2: MinStopsStrategy -- minimises number of stops
# ---------------------------------------------------------------------------


class MinStopsStrategy:
    """
    Greedy look-ahead fuel optimization that minimises the number of
    stops by preferring stations in the far half of the reachable
    range and always filling up completely.

    Algorithm:
    1. Start with a full tank at the origin.
    2. When the destination is unreachable, find all reachable stations.
    3. Prefer the cheapest station in the far half of reachable range
       (to cover more distance per stop); fall back to cheapest overall.
    4. Fill the tank completely at each stop.

    Trade-off: fewer stops but potentially higher total cost because
    cheaper nearby stations are skipped in favour of distance.
    """

    def select_stops(
        self,
        candidates: list[StationCandidate],
        route: RouteResult,
        range_miles: int,
        mpg: int,
        initial_fuel_fraction: float = 1.0,
    ) -> list[SelectedStop]:
        if not candidates:
            if route.total_miles <= range_miles * initial_fuel_fraction:
                return []
            raise OptimizationError(
                detail="No fuel stations found along the route corridor."
            )

        total_distance = route.total_miles
        tank_capacity_gallons = range_miles / mpg
        fuel_remaining_gallons = tank_capacity_gallons * initial_fuel_fraction
        current_position_miles = 0.0
        selected: list[SelectedStop] = []

        valid_candidates = sorted(
            [c for c in candidates if 0 < c.distance_along_route_miles < total_distance],
            key=lambda c: c.distance_along_route_miles,
        )

        if not valid_candidates and total_distance <= range_miles * initial_fuel_fraction:
            return []
        if not valid_candidates:
            raise OptimizationError(
                detail="Route exceeds vehicle range but no fuel stations found."
            )

        i = 0
        while current_position_miles < total_distance:
            miles_remaining_in_tank = fuel_remaining_gallons * mpg
            can_reach_miles = current_position_miles + miles_remaining_in_tank

            if can_reach_miles >= total_distance:
                break

            reachable = []
            for j in range(i, len(valid_candidates)):
                station = valid_candidates[j]
                if station.distance_along_route_miles <= current_position_miles:
                    continue
                if station.distance_along_route_miles > can_reach_miles:
                    break
                reachable.append((j, station))

            if not reachable:
                raise OptimizationError(
                    detail=(
                        f"No reachable fuel station between mile "
                        f"{current_position_miles:.0f} and "
                        f"{can_reach_miles:.0f}. Gap exceeds vehicle range."
                    )
                )

            # Prefer cheapest in far half of range to maximise distance
            midpoint = current_position_miles + miles_remaining_in_tank / 2
            far_reachable = [
                (j, s) for j, s in reachable
                if s.distance_along_route_miles >= midpoint
            ]
            search_pool = far_reachable if far_reachable else reachable
            best_idx, best_station = min(
                search_pool, key=lambda x: x[1].retail_price
            )

            distance_to_station = (
                best_station.distance_along_route_miles - current_position_miles
            )
            fuel_used = distance_to_station / mpg
            fuel_remaining_gallons -= fuel_used

            gallons_to_fill = tank_capacity_gallons - fuel_remaining_gallons
            cost = gallons_to_fill * best_station.retail_price

            selected.append(
                SelectedStop(
                    name=best_station.name,
                    address=best_station.address,
                    city=best_station.city,
                    state=best_station.state,
                    lat=best_station.lat,
                    lon=best_station.lon,
                    price_per_gallon=best_station.retail_price,
                    gallons_filled=round(gallons_to_fill, 2),
                    cost=round(cost, 2),
                    distance_from_start_miles=round(
                        best_station.distance_along_route_miles, 1
                    ),
                )
            )

            current_position_miles = best_station.distance_along_route_miles
            fuel_remaining_gallons = tank_capacity_gallons
            i = best_idx + 1

        return selected


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class FuelOptimizer:
    """
    Orchestrates fuel stop optimization for a route.

    Delegates station lookup to StationRepository and algorithm
    selection to an OptimizationStrategy. The view only talks to
    this class.

    Default strategy is MinCostStrategy (minimises total dollar cost).
    Pass MinStopsStrategy() to minimise number of stops instead.
    """

    def __init__(
        self,
        station_repo: StationRepository,
        strategy: OptimizationStrategy | None = None,
    ):
        self.station_repo = station_repo
        self.strategy = strategy or MinCostStrategy()

    def optimize(
        self,
        route: RouteResult,
        *,
        range_miles: int,
        mpg: int,
        corridor_buffer_miles: float,
        initial_fuel_fraction: float = 1.0,
    ) -> FuelPlan:
        """
        Find optimal fuel stops for the given route.

        Args:
            route: Decoded route with coordinates and cumulative distances.
            range_miles: Vehicle max range per tank.
            mpg: Vehicle fuel efficiency (miles per gallon).
            corridor_buffer_miles: How far from route to search for stations.
            initial_fuel_fraction: Starting fuel as a fraction of tank
                capacity (1.0 = full, 0.5 = half tank, etc.).

        Returns:
            FuelPlan with selected stops and cost totals.
        """
        # 1. Find candidate stations along the route corridor
        candidates = self.station_repo.find_along_corridor(
            route_coords=route.coordinates,
            cumulative_distances=route.cumulative_distances_miles,
            buffer_miles=corridor_buffer_miles,
        )

        logger.info(
            f"Optimizing route: {route.total_miles:.0f}mi, "
            f"{len(candidates)} candidate stations"
        )

        # 2. Run the optimization strategy
        stops = self.strategy.select_stops(
            candidates, route, range_miles, mpg, initial_fuel_fraction,
        )

        # 3. Build the fuel plan
        total_cost = sum(s.cost for s in stops)
        total_gallons = sum(s.gallons_filled for s in stops)

        plan = FuelPlan(
            stops=stops,
            total_cost=round(total_cost, 2),
            total_gallons=round(total_gallons, 2),
        )

        logger.info(
            f"Fuel plan: {plan.number_of_stops} stops, "
            f"${plan.total_cost:.2f} total, "
            f"{plan.total_gallons:.1f} gallons"
        )

        return plan
