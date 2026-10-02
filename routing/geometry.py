"""
Fast, dependency-free geometry for matching stops to a route polyline.

The route is densified so no segment is longer than MAX_SEGMENT_MILES, then
indexed in a coarse lat/lon grid. Each stop only inspects route vertices in
nearby grid cells, so cost scales with stops, not stops x route points.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_MILES = 3958.8
MILES_PER_DEG_LAT = 69.0
MAX_SEGMENT_MILES = 1.5
GRID_DEG = 0.25


def haversine_miles(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _flat_miles(lat, lon, ref_lat, ref_lon):
    x = (lon - ref_lon) * math.cos(math.radians(ref_lat)) * MILES_PER_DEG_LAT
    y = (lat - ref_lat) * MILES_PER_DEG_LAT
    return x, y


@dataclass(frozen=True)
class Projection:
    distance_miles: float
    route_mile: float


class RouteIndex:
    def __init__(self, coords: list[tuple[float, float]], total_miles: float | None = None):
        """coords: (lat, lon) pairs. total_miles rescales to the router's own distance."""
        if len(coords) < 2:
            raise ValueError("A route needs at least two points")
        dense = [coords[0]]
        for (la1, lo1), (la2, lo2) in zip(coords, coords[1:]):
            seg = haversine_miles(la1, lo1, la2, lo2)
            pieces = max(1, math.ceil(seg / MAX_SEGMENT_MILES))
            for k in range(1, pieces + 1):
                f = k / pieces
                dense.append((la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f))
        self.points = dense

        cum = [0.0]
        for a, b in zip(dense, dense[1:]):
            cum.append(cum[-1] + haversine_miles(a[0], a[1], b[0], b[1]))
        scale = (total_miles / cum[-1]) if total_miles and cum[-1] > 0 else 1.0
        self.cum = [c * scale for c in cum]
        self.total_miles = self.cum[-1]

        self.grid: dict[tuple[int, int], list[int]] = {}
        for i, (la, lo) in enumerate(dense):
            self.grid.setdefault(self._cell(la, lo), []).append(i)

    @staticmethod
    def _cell(lat, lon):
        return (math.floor(lat / GRID_DEG), math.floor(lon / GRID_DEG))

    def project(self, lat: float, lon: float, max_miles: float) -> Projection | None:
        """Nearest point on the route within max_miles, or None."""
        reach_y = math.ceil(max_miles / (MILES_PER_DEG_LAT * GRID_DEG))
        miles_per_lon_cell = MILES_PER_DEG_LAT * GRID_DEG * max(math.cos(math.radians(lat)), 0.1)
        reach_x = math.ceil(max_miles / miles_per_lon_cell)
        cy, cx = self._cell(lat, lon)
        best_i, best_d = None, float("inf")
        for dx in range(-reach_x, reach_x + 1):
            for dy in range(-reach_y, reach_y + 1):
                for i in self.grid.get((cy + dy, cx + dx), ()):
                    px, py = self.points[i]
                    x, y = _flat_miles(px, py, lat, lon)
                    d = math.hypot(x, y)
                    if d < best_d:
                        best_i, best_d = i, d
        if best_i is None or best_d > max_miles:
            return None
        return Projection(distance_miles=best_d, route_mile=self.cum[best_i])
