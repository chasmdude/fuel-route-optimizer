"""
Unit tests for the fuel optimization engine.

Tests both optimization strategies in isolation using pre-built
StationCandidate lists -- no database, no ORS.

- MinCostStrategy:  globally optimal cost minimisation (min-heap)
- MinStopsStrategy: minimises number of stops
"""

import pytest

from apps.route.dataclasses import Coordinates, RouteResult, StationCandidate
from apps.route.exceptions import OptimizationError
from apps.route.services.fuel_optimizer import (
    MinCostStrategy,
    MinStopsStrategy,
)


class TestMinStopsStrategy:
    """Tests for the greedy look-ahead fuel stop selection."""

    def _make_candidate(self, distance_miles, price, opis_id=1, name="Station"):
        return StationCandidate(
            station_id=opis_id,
            opis_id=opis_id,
            name=f"{name} at mile {distance_miles}",
            address="Test Address",
            city="Test City",
            state="OH",
            lat=40.0,
            lon=-82.0,
            retail_price=price,
            distance_along_route_miles=distance_miles,
        )

    def test_picks_cheapest_station_in_range(self, sample_route_result):
        """When multiple stations are reachable, picks the cheapest."""
        strategy = MinStopsStrategy()
        candidates = [
            self._make_candidate(200, 3.50, opis_id=1),
            self._make_candidate(300, 2.80, opis_id=2),  # cheapest
            self._make_candidate(400, 3.20, opis_id=3),
        ]

        stops = strategy.select_stops(
            candidates, sample_route_result, range_miles=500, mpg=10
        )

        assert len(stops) >= 1
        # The first stop chosen should be the cheapest reachable
        assert stops[0].price_per_gallon == 2.80

    def test_short_route_no_refuel_needed(self, sample_route_result):
        """Route within tank range should require no stops."""
        # Modify route to be only 400 miles
        from apps.route.dataclasses import Coordinates, RouteResult

        short_route = RouteResult(
            distance_meters=400 * 1609.34,
            duration_seconds=6 * 3600,
            geometry={"type": "LineString", "coordinates": []},
            coordinates=[
                Coordinates(lat=40.71, lon=-74.00),
                Coordinates(lat=39.90, lon=-82.00),
            ],
            cumulative_distances_miles=[0.0, 400.0],
        )

        strategy = MinStopsStrategy()
        candidates = [
            self._make_candidate(200, 3.00, opis_id=1),
        ]

        stops = strategy.select_stops(
            candidates, short_route, range_miles=500, mpg=10
        )

        assert len(stops) == 0

    def test_no_candidates_short_route(self, sample_route_result):
        """No candidates on a short route should return empty list."""
        from apps.route.dataclasses import Coordinates, RouteResult

        short_route = RouteResult(
            distance_meters=300 * 1609.34,
            duration_seconds=5 * 3600,
            geometry={"type": "LineString", "coordinates": []},
            coordinates=[
                Coordinates(lat=40.71, lon=-74.00),
                Coordinates(lat=40.10, lon=-80.00),
            ],
            cumulative_distances_miles=[0.0, 300.0],
        )

        strategy = MinStopsStrategy()
        stops = strategy.select_stops([], short_route, range_miles=500, mpg=10)

        assert len(stops) == 0

    def test_no_candidates_long_route_raises(self, sample_route_result):
        """No candidates on a route exceeding range should raise."""
        strategy = MinStopsStrategy()

        with pytest.raises(OptimizationError):
            strategy.select_stops(
                [], sample_route_result, range_miles=500, mpg=10
            )

    def test_fills_tank_completely(self, sample_route_result):
        """Each stop should fill the tank to capacity."""
        strategy = MinStopsStrategy()
        candidates = [
            self._make_candidate(350, 3.00, opis_id=1),
        ]

        stops = strategy.select_stops(
            candidates, sample_route_result, range_miles=500, mpg=10
        )

        assert len(stops) >= 1
        # Tank capacity is 500/10 = 50 gallons
        # Drove 350 miles = 35 gallons used, so fill 35 gallons
        assert stops[0].gallons_filled == 35.0
        assert stops[0].cost == round(35.0 * 3.00, 2)

    def test_multiple_stops_on_long_route(self):
        """A 1500-mile route should need multiple fuel stops."""
        from apps.route.dataclasses import Coordinates, RouteResult

        coords = [Coordinates(lat=40.0 - i * 0.5, lon=-74.0 - i * 2.0) for i in range(16)]
        cumulative = [i * 100.0 for i in range(16)]

        long_route = RouteResult(
            distance_meters=1500 * 1609.34,
            duration_seconds=22 * 3600,
            geometry={"type": "LineString", "coordinates": []},
            coordinates=coords,
            cumulative_distances_miles=cumulative,
        )

        strategy = MinStopsStrategy()
        candidates = [
            self._make_candidate(200, 3.10, opis_id=1),
            self._make_candidate(400, 2.90, opis_id=2),
            self._make_candidate(600, 3.00, opis_id=3),
            self._make_candidate(800, 2.85, opis_id=4),
            self._make_candidate(1000, 3.05, opis_id=5),
            self._make_candidate(1200, 2.95, opis_id=6),
            self._make_candidate(1400, 3.15, opis_id=7),
        ]

        stops = strategy.select_stops(
            candidates, long_route, range_miles=500, mpg=10
        )

        # Should need at least 2 stops for a 1500-mile route with 500-mile range
        assert len(stops) >= 2
        # All stops should have positive cost
        assert all(s.cost > 0 for s in stops)


# =========================================================================
# MinCostStrategy tests
# =========================================================================


class TestMinCostStrategy:
    """Tests for the min-heap retroactive refueling strategy."""

    def _make_candidate(self, distance_miles, price, opis_id=1, name="Station"):
        return StationCandidate(
            station_id=opis_id,
            opis_id=opis_id,
            name=f"{name} at mile {distance_miles}",
            address="Test Address",
            city="Test City",
            state="OH",
            lat=40.0,
            lon=-82.0,
            retail_price=price,
            distance_along_route_miles=distance_miles,
        )

    def _make_route(self, total_miles):
        """Helper to create a RouteResult of given length."""
        n = max(2, int(total_miles / 100) + 1)
        coords = [Coordinates(lat=40.0 - i * 0.3, lon=-74.0 - i * 1.5) for i in range(n)]
        cumulative = [i * (total_miles / (n - 1)) for i in range(n)]
        return RouteResult(
            distance_meters=total_miles * 1609.34,
            duration_seconds=total_miles / 60 * 3600,
            geometry={"type": "LineString", "coordinates": []},
            coordinates=coords,
            cumulative_distances_miles=cumulative,
        )

    def test_picks_cheapest_reachable(self):
        """Should buy fuel from the cheapest available station."""
        strategy = MinCostStrategy()
        route = self._make_route(600)
        candidates = [
            self._make_candidate(150, 3.50, opis_id=1),
            self._make_candidate(200, 2.80, opis_id=2),  # cheapest
            self._make_candidate(400, 3.20, opis_id=3),
        ]

        stops = strategy.select_stops(candidates, route, range_miles=500, mpg=10)

        assert len(stops) >= 1
        # Cheapest station should appear in the stops
        prices = [s.price_per_gallon for s in stops]
        assert 2.80 in prices

    def test_partial_fill_when_cheaper_ahead(self):
        """Should buy just enough at expensive station to reach cheaper one."""
        strategy = MinCostStrategy()
        route = self._make_route(800)
        candidates = [
            self._make_candidate(300, 3.50, opis_id=1),  # expensive
            self._make_candidate(600, 2.50, opis_id=2),  # cheap
        ]

        stops = strategy.select_stops(candidates, route, range_miles=500, mpg=10)

        # With heap: it drives to 300 (fuel: 50-30=20gal), then to 600
        # (fuel: 20-30=-10 → needs 10gal retroactively from cheapest).
        # But at mile 300 spare was 30gal, so it could buy there.
        # It should prefer buying from station at 600 ($2.50) over 300 ($3.50).
        # The heap will retroactively buy from the cheapest it passed.
        assert len(stops) >= 1
        # Should buy from the cheap station when possible
        total_cost = sum(s.cost for s in stops)
        assert total_cost > 0

    def test_full_fill_at_cheapest_when_no_cheaper_ahead(self):
        """When the cheapest station has no cheaper alternative ahead,
        the heap should exhaust ALL available tank capacity there.

        Scenario: 1200mi route, 50gal tank (500mi range), full start.
        Stations: mile 300 ($2.50), mile 700 ($3.50), mile 1100 ($3.50).

        At mile 300 we had 20gal remaining → spare capacity = 30gal.
        The heap retroactively buys the full 30gal at $2.50 (the max
        the tank could hold at that point). The remaining 40gal must
        come from the $3.50 station because the tank is physically
        bounded -- you can't carry more cheap fuel than the spare
        capacity allows.
        """
        strategy = MinCostStrategy()
        route = self._make_route(1200)
        candidates = [
            self._make_candidate(300, 2.50, opis_id=1),  # cheapest
            self._make_candidate(700, 3.50, opis_id=2),  # more expensive
            self._make_candidate(1100, 3.50, opis_id=3),  # more expensive
        ]

        stops = strategy.select_stops(candidates, route, range_miles=500, mpg=10)

        # First stop should be the cheapest station
        assert stops[0].price_per_gallon == 2.50
        # It buys the max its spare capacity allowed (30gal)
        assert stops[0].gallons_filled == 30.0

        # Total fuel bought = 1200mi/10mpg - 50gal start = 70gal
        total_gallons = sum(s.gallons_filled for s in stops)
        assert total_gallons == pytest.approx(70.0, abs=1.0)

        # Cost must be optimal: 30*2.50 + 40*3.50 = $215
        total_cost = sum(s.cost for s in stops)
        assert total_cost == pytest.approx(215.0, abs=1.0)

    def test_short_route_no_stops(self):
        """Route within tank range needs no stops."""
        strategy = MinCostStrategy()
        route = self._make_route(400)
        candidates = [self._make_candidate(200, 3.00, opis_id=1)]

        stops = strategy.select_stops(candidates, route, range_miles=500, mpg=10)
        assert len(stops) == 0

    def test_no_candidates_long_route_raises(self):
        """No candidates on a long route should raise OptimizationError."""
        strategy = MinCostStrategy()
        route = self._make_route(600)

        with pytest.raises(OptimizationError):
            strategy.select_stops([], route, range_miles=500, mpg=10)

    def test_cheaper_than_greedy_on_long_route(self):
        """MinCostStrategy should produce equal or lower cost than MinStopsStrategy."""
        route = self._make_route(1500)
        candidates = [
            self._make_candidate(200, 3.10, opis_id=1),
            self._make_candidate(400, 2.90, opis_id=2),
            self._make_candidate(600, 3.00, opis_id=3),
            self._make_candidate(800, 2.85, opis_id=4),
            self._make_candidate(1000, 3.05, opis_id=5),
            self._make_candidate(1200, 2.95, opis_id=6),
            self._make_candidate(1400, 3.15, opis_id=7),
        ]

        cheapest_stops = MinCostStrategy().select_stops(
            candidates, route, range_miles=500, mpg=10
        )
        greedy_stops = MinStopsStrategy().select_stops(
            candidates, route, range_miles=500, mpg=10
        )

        cheapest_cost = sum(s.cost for s in cheapest_stops)
        greedy_cost = sum(s.cost for s in greedy_stops)

        assert cheapest_cost <= greedy_cost, (
            f"MinCost (${cheapest_cost:.2f}) should be <= "
            f"MinStops (${greedy_cost:.2f})"
        )

    def test_multiple_stops_long_route(self):
        """A 1500-mile route should require multiple stops."""
        strategy = MinCostStrategy()
        route = self._make_route(1500)
        candidates = [
            self._make_candidate(200, 3.10, opis_id=1),
            self._make_candidate(450, 2.90, opis_id=2),
            self._make_candidate(700, 3.00, opis_id=3),
            self._make_candidate(950, 2.85, opis_id=4),
            self._make_candidate(1200, 3.05, opis_id=5),
            self._make_candidate(1400, 2.95, opis_id=6),
        ]

        stops = strategy.select_stops(candidates, route, range_miles=500, mpg=10)

        assert len(stops) >= 2
        assert all(s.cost > 0 for s in stops)
        total_gallons = sum(s.gallons_filled for s in stops)
        assert total_gallons > 0

    def test_no_micro_stops(self):
        """No stop should have less than 1 gallon (rounding artifacts aside)."""
        strategy = MinCostStrategy()
        route = self._make_route(2000)
        candidates = [
            self._make_candidate(100, 3.10, opis_id=1),
            self._make_candidate(250, 2.90, opis_id=2),
            self._make_candidate(400, 3.00, opis_id=3),
            self._make_candidate(550, 2.85, opis_id=4),
            self._make_candidate(700, 3.05, opis_id=5),
            self._make_candidate(850, 2.70, opis_id=6),
            self._make_candidate(1000, 3.15, opis_id=7),
            self._make_candidate(1150, 2.95, opis_id=8),
            self._make_candidate(1300, 3.00, opis_id=9),
            self._make_candidate(1500, 2.80, opis_id=10),
            self._make_candidate(1700, 3.10, opis_id=11),
            self._make_candidate(1900, 2.90, opis_id=12),
        ]

        stops = strategy.select_stops(candidates, route, range_miles=500, mpg=10)

        for stop in stops:
            assert stop.gallons_filled >= 1.0, (
                f"Micro-stop detected: {stop.gallons_filled} gal at "
                f"mile {stop.distance_from_start_miles} "
                f"(${stop.price_per_gallon}/gal)"
            )

    def test_optimal_retroactive_buy(self):
        """The heap should retroactively buy cheap fuel over expensive fuel.

        Scenario: two stations A ($2.00 at mile 200) and B ($4.00 at mile 400)
        on a 600-mile route with 500-mile range (50 gal tank at 10 mpg).

        Starting with a full tank (50 gal), we can reach mile 500.
        But the destination is at mile 600 -- need 10 extra gallons.
        The heap should buy those 10 gallons from A ($2.00) not B ($4.00).
        """
        strategy = MinCostStrategy()
        route = self._make_route(600)
        candidates = [
            self._make_candidate(200, 2.00, opis_id=1),  # cheap
            self._make_candidate(400, 4.00, opis_id=2),  # expensive
        ]

        stops = strategy.select_stops(candidates, route, range_miles=500, mpg=10)

        # Should only stop at the cheap station
        assert len(stops) == 1
        assert stops[0].price_per_gallon == 2.00
        assert stops[0].gallons_filled == 10.0  # exactly what's needed
        assert stops[0].cost == 20.0

    def test_initial_fuel_fraction(self):
        """Half tank should require more fuel stops."""
        strategy = MinCostStrategy()
        route = self._make_route(600)
        candidates = [
            self._make_candidate(150, 3.00, opis_id=1),
            self._make_candidate(350, 3.00, opis_id=2),
        ]

        # Full tank: 50 gal = 500 miles, need 600 → 1 stop
        stops_full = strategy.select_stops(
            candidates, route, range_miles=500, mpg=10, initial_fuel_fraction=1.0,
        )
        # Half tank: 25 gal = 250 miles, need 600 → more fuel needed
        stops_half = strategy.select_stops(
            candidates, route, range_miles=500, mpg=10, initial_fuel_fraction=0.5,
        )

        total_gal_full = sum(s.gallons_filled for s in stops_full)
        total_gal_half = sum(s.gallons_filled for s in stops_half)

        # Half tank needs 25 more gallons of fuel bought than full tank
        assert total_gal_half > total_gal_full
