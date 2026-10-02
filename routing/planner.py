"""Glue: route + stop catalog + optimizer -> response payload. No HTTP handling here."""
from __future__ import annotations

import functools
import json
from pathlib import Path

from django.conf import settings

from .fuel_optimizer import InfeasibleRoute, Station, plan_fuel_stops
from .geometry import RouteIndex
from .routing_client import Route


@functools.lru_cache(maxsize=1)
def load_stops() -> tuple[dict, ...]:
    path = Path(settings.BASE_DIR) / "routing" / "data" / "fuel_stops.json"
    if not path.exists():
        raise FileNotFoundError(
            "routing/data/fuel_stops.json is missing. Run: python manage.py geocode_fuel_stops"
        )
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def simplify(coords, max_points: int):
    """Evenly decimate for the map payload, always keeping both endpoints."""
    if len(coords) <= max_points:
        return coords
    step = len(coords) / (max_points - 1)
    out = [coords[int(i * step)] for i in range(max_points - 1)]
    out.append(coords[-1])
    return out


def candidate_stations(index: RouteIndex, stops, corridor_miles: float) -> list[Station]:
    stations = []
    for stop in stops:
        proj = index.project(stop["latitude"], stop["longitude"], corridor_miles)
        if proj is None:
            continue
        stations.append(
            Station(
                mile=proj.route_mile,
                price=stop["price"],
                data={**stop, "miles_off_route": proj.distance_miles},
            )
        )
    return stations


def build_plan(
    route: Route,
    range_miles: float,
    mpg: float,
    corridor_miles: float,
    full_geometry: bool = False,
    stops=None,
) -> dict:
    stops = load_stops() if stops is None else stops
    index = RouteIndex(route.coords, total_miles=route.distance_miles)
    stations = candidate_stations(index, stops, corridor_miles)
    plan = plan_fuel_stops(stations, index.total_miles, range_miles, mpg)

    fuel_stops = []
    for p in plan.purchases:
        d = p.station.data
        fuel_stops.append({
            "name": d["name"],
            "address": d["address"],
            "city": d["city"],
            "state": d["state"],
            "price_per_gallon": round(p.station.price, 3),
            "gallons": round(p.gallons, 2),
            "cost": round(p.cost, 2),
            "route_mile": round(p.station.mile, 1),
            "miles_off_route": round(d["miles_off_route"], 1),
            "location": {
                "latitude": d["latitude"],
                "longitude": d["longitude"],
                "precision": "city_centroid",
            },
        })

    line = route.coords if full_geometry else simplify(route.coords, settings.MAP_MAX_POINTS)
    line_geojson = [[lon, lat] for lat, lon in line]
    features = [{
        "type": "Feature",
        "properties": {"kind": "route"},
        "geometry": {"type": "LineString", "coordinates": line_geojson},
    }]
    for i, s in enumerate(fuel_stops, 1):
        features.append({
            "type": "Feature",
            "properties": {"kind": "fuel_stop", "order": i, "name": s["name"],
                           "price_per_gallon": s["price_per_gallon"], "cost": s["cost"]},
            "geometry": {"type": "Point",
                         "coordinates": [s["location"]["longitude"], s["location"]["latitude"]]},
        })

    lats = [c[0] for c in route.coords]
    lons = [c[1] for c in route.coords]
    return {
        "total_distance_miles": round(route.distance_miles, 1),
        "total_duration_hours": round(route.duration_seconds / 3600, 2),
        "total_fuel_cost": round(plan.total_cost, 2),
        "fuel_stops": fuel_stops,
        "map": {
            "geojson": {"type": "FeatureCollection", "features": features},
            "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]],
            "viewer_hint": "Open /?start=...&finish=... for a Leaflet map of this response.",
        },
        "assumptions": {
            "vehicle_range_miles": range_miles,
            "mpg": mpg,
            "starting_tank": "full, not billed; total_fuel_cost covers fuel bought at the listed stops",
            "stop_location_precision": "City centroid (CSV has no coordinates); stops are matched "
                                       f"to the route within {corridor_miles:g} miles",
            "candidate_stops_on_corridor": len(stations),
        },
        "routing": {"provider": route.provider, "cached": route.cached},
    }


__all__ = ["build_plan", "load_stops", "InfeasibleRoute"]
