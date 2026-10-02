"""
Pure fuel-planning logic. No Django, no network.

Problem: a vehicle with a fixed range drives a route of known length. Stations
sit at known mile markers with known prices. Pick purchases that minimize cost.

This is the classic "gas station problem", solved exactly by a greedy rule:

  At a station, look at every station reachable on a full tank.
  - If one is cheaper than here, buy only enough to reach the first such one.
  - Otherwise, if the destination is reachable on a full tank, buy only
    enough to finish.
  - Otherwise fill the tank and go to the cheapest reachable station.

The destination is modeled as a station priced at zero, which folds the second
rule into the first. Buying the minimum before a cheaper station and the
maximum before a pricier one is what makes the greedy plan optimal.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field


class InfeasibleRoute(Exception):
    """Raised when two consecutive usable stations are farther apart than the range."""


@dataclass(frozen=True)
class Station:
    mile: float
    price: float
    data: dict = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True)
class Purchase:
    station: Station
    gallons: float
    cost: float
    arrival_fuel_gallons: float


@dataclass(frozen=True)
class FuelPlan:
    purchases: list[Purchase]
    total_cost: float
    total_gallons_purchased: float


EPS = 1e-9


def plan_fuel_stops(
    stations: list[Station],
    total_miles: float,
    range_miles: float = 500.0,
    mpg: float = 10.0,
    starting_fuel_miles: float | None = None,
) -> FuelPlan:
    """
    Return the cheapest set of purchases for the trip.

    The vehicle starts with `starting_fuel_miles` of fuel (default: a full tank).
    That initial fuel is not billed; only fuel bought at stations is costed.
    """
    if range_miles <= 0 or mpg <= 0:
        raise ValueError("range_miles and mpg must be positive")

    fuel = range_miles if starting_fuel_miles is None else min(starting_fuel_miles, range_miles)
    usable = sorted(
        (s for s in stations if 0 < s.mile < total_miles),
        key=lambda s: (s.mile, s.price),
    )
    miles = [s.mile for s in usable]
    destination = Station(mile=total_miles, price=0.0, data={"destination": True})

    pos = 0.0
    here: Station | None = None
    purchases: list[Purchase] = []
    total_cost = 0.0
    total_gallons = 0.0

    while total_miles - pos > fuel + EPS:
        reach = range_miles if here is not None else fuel
        lo = bisect.bisect_right(miles, pos + EPS)
        hi = bisect.bisect_right(miles, pos + reach + EPS)
        ahead = usable[lo:hi]
        if total_miles - pos <= reach + EPS:
            ahead.append(destination)
        if not ahead:
            raise InfeasibleRoute(
                f"No fuel station within {range_miles:.0f} miles after mile {pos:.1f}"
            )

        if here is None:
            target = ahead[0]
            buy_miles = 0.0
        else:
            cheaper = next((s for s in ahead if s.price < here.price - EPS), None)
            if cheaper is not None:
                target = cheaper
                buy_miles = max(0.0, (cheaper.mile - pos) - fuel)
            else:
                target = min(ahead, key=lambda s: (s.price, -s.mile))
                buy_miles = range_miles - fuel

        if buy_miles > EPS:
            gallons = buy_miles / mpg
            cost = gallons * here.price
            purchases.append(Purchase(here, gallons, cost, fuel / mpg))
            total_cost += cost
            total_gallons += gallons
            fuel += buy_miles

        fuel -= target.mile - pos
        pos = target.mile
        here = target if target is not destination else None
        if target is destination:
            break

    return FuelPlan(purchases, total_cost, total_gallons)
