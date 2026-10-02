from django.conf import settings
from django.shortcuts import render
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .locations import LocationError, resolve_location
from .planner import InfeasibleRoute, build_plan
from .routing_client import RoutingError, Unroutable, get_route
from .serializers import RouteRequestSerializer


def error(message, code, http):
    return Response({"error": {"code": code, "message": message}}, status=http)


class PlanRouteView(APIView):
    """GET or POST /api/route/ with start and finish."""

    def get(self, request):
        return self._handle(request.query_params)

    def post(self, request):
        return self._handle(request.data)

    def _handle(self, payload):
        ser = RouteRequestSerializer(data=payload)
        if not ser.is_valid():
            return Response(
                {"error": {"code": "invalid_request", "message": "Invalid parameters",
                           "details": ser.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        p = ser.validated_data
        try:
            s_lat, s_lon, _ = resolve_location(p["start"], "start")
            f_lat, f_lon, _ = resolve_location(p["finish"], "finish")
        except LocationError as exc:
            return error(str(exc), "invalid_location", status.HTTP_400_BAD_REQUEST)

        try:
            route = get_route((s_lat, s_lon), (f_lat, f_lon))
        except Unroutable as exc:
            return error(str(exc), "unroutable", status.HTTP_422_UNPROCESSABLE_ENTITY)
        except RoutingError as exc:
            return error(str(exc), "routing_unavailable", status.HTTP_502_BAD_GATEWAY)

        try:
            result = build_plan(
                route, p["vehicle_range"], p["mpg"], settings.FUEL_CORRIDOR_MILES,
                full_geometry=p["full_geometry"],
            )
        except InfeasibleRoute as exc:
            return error(str(exc), "no_feasible_fuel_plan", status.HTTP_422_UNPROCESSABLE_ENTITY)

        result["start"] = {"query": p["start"], "latitude": s_lat, "longitude": s_lon}
        result["finish"] = {"query": p["finish"], "latitude": f_lat, "longitude": f_lon}
        return Response(result)


def map_page(request):
    return render(request, "routing/map.html", {
        "tile_url": settings.MAP_TILE_URL,
        "tile_attribution": settings.MAP_TILE_ATTRIBUTION,
    })
