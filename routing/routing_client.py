"""
One driving-route call per request.

Default provider: the public OSRM demo server (free, no key). If
ORS_API_KEY is set and ROUTING_PROVIDER=ors, OpenRouteService is used instead.
Results are cached so repeating a request makes zero provider calls.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

METERS_PER_MILE = 1609.344


class RoutingError(Exception):
    """Provider failed (network, rate limit, bad response)."""


class Unroutable(RoutingError):
    """Provider answered, but no driving route exists between the points."""


@dataclass(frozen=True)
class Route:
    coords: list[tuple[float, float]]  # (lat, lon)
    distance_miles: float
    duration_seconds: float
    provider: str
    cached: bool = False


def _cache_key(provider, a, b):
    return "route:%s:%.4f,%.4f:%.4f,%.4f" % ((provider,) + a + b)


def get_route(start: tuple[float, float], finish: tuple[float, float]) -> Route:
    provider = settings.ROUTING_PROVIDER
    key = _cache_key(provider, start, finish)
    hit = cache.get(key)
    if hit is not None:
        return Route(**{**hit.__dict__, "cached": True})

    if provider == "ors":
        route = _ors(start, finish)
    elif provider == "osrm":
        route = _osrm(start, finish)
    else:
        raise RoutingError(f"Unknown ROUTING_PROVIDER '{provider}'")
    cache.set(key, route, settings.ROUTE_CACHE_SECONDS)
    return route


def _osrm(start, finish) -> Route:
    url = (
        f"{settings.OSRM_URL.rstrip('/')}/route/v1/driving/"
        f"{start[1]},{start[0]};{finish[1]},{finish[0]}"
    )
    try:
        resp = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
            timeout=settings.HTTP_TIMEOUT_SECONDS,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise RoutingError(f"Routing service unavailable: {exc}") from exc

    code = data.get("code")
    if code in ("NoRoute", "NoSegment"):
        raise Unroutable("No drivable route between those locations")
    if resp.status_code != 200 or code != "Ok" or not data.get("routes"):
        raise RoutingError(f"Routing service error: {code or resp.status_code}")

    r = data["routes"][0]
    return Route(
        coords=[(lat, lon) for lon, lat in r["geometry"]["coordinates"]],
        distance_miles=r["distance"] / METERS_PER_MILE,
        duration_seconds=r["duration"],
        provider="osrm",
    )


def _ors(start, finish) -> Route:
    if not settings.ORS_API_KEY:
        raise RoutingError("ROUTING_PROVIDER=ors requires ORS_API_KEY")
    try:
        resp = requests.post(
            "https://api.openrouteservice.org/v2/directions/driving-car/geojson",
            json={"coordinates": [[start[1], start[0]], [finish[1], finish[0]]]},
            headers={"Authorization": settings.ORS_API_KEY},
            timeout=settings.HTTP_TIMEOUT_SECONDS,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise RoutingError(f"Routing service unavailable: {exc}") from exc

    if resp.status_code == 404 or (resp.status_code == 400 and "error" in data):
        raise Unroutable("No drivable route between those locations")
    if resp.status_code != 200 or not data.get("features"):
        raise RoutingError(f"Routing service error: HTTP {resp.status_code}")

    feat = data["features"][0]
    summary = feat["properties"]["summary"]
    return Route(
        coords=[(lat, lon) for lon, lat in feat["geometry"]["coordinates"]],
        distance_miles=summary["distance"] / METERS_PER_MILE,
        duration_seconds=summary["duration"],
        provider="ors",
    )
