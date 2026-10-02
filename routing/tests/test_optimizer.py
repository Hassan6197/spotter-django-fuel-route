import random
from unittest import TestCase

from routing.fuel_optimizer import InfeasibleRoute, Station, plan_fuel_stops


def st(mile, price):
    return Station(mile=mile, price=price, data={"id": f"{mile}"})


class PlanFuelStopsTests(TestCase):
    def test_trip_within_range_needs_no_stops(self):
        plan = plan_fuel_stops([st(100, 3.0)], total_miles=300)
        self.assertEqual(plan.purchases, [])
        self.assertEqual(plan.total_cost, 0)

    def test_exactly_one_tank_needs_no_stops(self):
        plan = plan_fuel_stops([st(250, 3.0)], total_miles=500)
        self.assertEqual(plan.purchases, [])

    def test_buys_only_what_is_needed_to_finish(self):
        # Arrive at mile 400 with 100 miles left, 200 to go: buy 100 miles = 10 gal.
        plan = plan_fuel_stops([st(400, 3.0)], total_miles=600)
        self.assertEqual(len(plan.purchases), 1)
        self.assertAlmostEqual(plan.purchases[0].gallons, 10.0)
        self.assertAlmostEqual(plan.total_cost, 30.0)

    def test_skips_expensive_station_when_cheaper_one_is_in_range(self):
        plan = plan_fuel_stops([st(200, 5.0), st(450, 2.0)], total_miles=900)
        self.assertEqual([p.station.mile for p in plan.purchases], [450])
        self.assertAlmostEqual(plan.total_cost, 40 * 2.0)

    def test_buys_minimum_at_expensive_station_before_cheaper_one(self):
        plan = plan_fuel_stops([st(300, 4.0), st(400, 3.0)], total_miles=800)
        self.assertEqual([p.station.mile for p in plan.purchases], [400])
        self.assertAlmostEqual(plan.total_cost, 30 * 3.0)

    def test_fills_tank_at_cheap_station_before_expensive_one(self):
        plan = plan_fuel_stops([st(300, 2.0), st(700, 4.0)], total_miles=1100)
        self.assertEqual([p.station.mile for p in plan.purchases], [300, 700])
        self.assertAlmostEqual(plan.purchases[0].gallons, 30.0)
        self.assertAlmostEqual(plan.purchases[1].gallons, 30.0)
        self.assertAlmostEqual(plan.total_cost, 30 * 2.0 + 30 * 4.0)

    def test_gap_larger_than_range_is_infeasible(self):
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops([st(100, 3.0)], total_miles=1000)

    def test_no_stations_on_long_route_is_infeasible(self):
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops([], total_miles=501)

    def test_never_runs_dry(self):
        rng = random.Random(7)
        stations = [st(m, round(rng.uniform(2.8, 4.2), 3)) for m in range(60, 3000, 60)]
        plan = plan_fuel_stops(stations, total_miles=3000, range_miles=500, mpg=10)
        fuel = 500.0
        pos = 0.0
        for p in plan.purchases:
            fuel -= p.station.mile - pos
            self.assertGreaterEqual(fuel, -1e-6)
            fuel += p.gallons * 10
            self.assertLessEqual(fuel, 500 + 1e-6)
            pos = p.station.mile
        self.assertGreaterEqual(fuel - (3000 - pos), -1e-6)

    def test_mpg_scales_gallons(self):
        plan = plan_fuel_stops([st(400, 3.0)], total_miles=600, mpg=20)
        self.assertAlmostEqual(plan.purchases[0].gallons, 5.0)

    def test_matches_exhaustive_dp_on_random_instances(self):
        """Compare the greedy plan to an exact DP over 10-mile fuel units."""
        rng = random.Random(1234)
        for _ in range(200):
            range_units = rng.randint(5, 12)
            total_units = rng.randint(range_units + 1, 60)
            units = sorted(rng.sample(range(1, total_units), rng.randint(3, min(20, total_units - 1))))
            stations = [st(u * 10, round(rng.uniform(2.0, 5.0), 2)) for u in units]
            expected = self._dp_cost(stations, total_units, range_units)
            if expected is None:
                with self.assertRaises(InfeasibleRoute):
                    plan_fuel_stops(stations, total_units * 10, range_units * 10, 10)
            else:
                plan = plan_fuel_stops(stations, total_units * 10, range_units * 10, 10)
                self.assertAlmostEqual(plan.total_cost, expected, places=6)

    @staticmethod
    def _dp_cost(stations, total_units, range_units):
        nodes = [(0, None)] + [(int(s.mile / 10), s.price) for s in stations] + [(total_units, None)]
        inf = float("inf")
        cost = [inf] * (range_units + 1)
        cost[range_units] = 0.0
        for i, (pos, price) in enumerate(nodes[:-1]):
            if price is not None:
                for f in range(1, range_units + 1):
                    cost[f] = min(cost[f], cost[f - 1] + price)
            gap = nodes[i + 1][0] - pos
            nxt = [inf] * (range_units + 1)
            for f in range(gap, range_units + 1):
                nxt[f - gap] = cost[f]
            cost = nxt
        best = min(cost)
        return None if best == inf else best
