from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from routing.geometry import haversine_miles
from routing.routing_client import Route, RoutingError, Unroutable

CHI = (41.8781, -87.6298)
DEN = (39.7392, -104.9903)


def straight_route(a, b, points=400):
    coords = [(a[0] + (b[0] - a[0]) * i / points, a[1] + (b[1] - a[1]) * i / points)
              for i in range(points + 1)]
    miles = sum(haversine_miles(*p, *q) for p, q in zip(coords, coords[1:]))
    return Route(coords=coords, distance_miles=miles, duration_seconds=miles / 60 * 3600, provider="test")


def stops_along(a, b, count=40):
    out = []
    for i in range(1, count):
        f = i / count
        out.append({
            "id": str(i), "name": f"STOP {i}", "address": "I-80, EXIT 1", "city": "Testville",
            "state": "NE", "price": 3.0 + (i % 7) * 0.1,
            "latitude": a[0] + (b[0] - a[0]) * f, "longitude": a[1] + (b[1] - a[1]) * f,
        })
    return out


class RouteApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.route = straight_route(CHI, DEN)

    def call(self, params, method="get", stops=None, route=None, side_effect=None):
        stops = stops_along(CHI, DEN) if stops is None else stops
        with mock.patch("routing.views.get_route", return_value=route or self.route,
                        side_effect=side_effect) as gr, \
                mock.patch("routing.planner.load_stops", return_value=tuple(stops)):
            resp = getattr(self.client, method)("/api/route/", params, format="json")
        return resp, gr

    def test_success_with_one_routing_call(self):
        resp, gr = self.call({"start": "Chicago, IL", "finish": "Denver, CO"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(gr.call_count, 1)
        body = resp.json()
        self.assertGreaterEqual(len(body["fuel_stops"]), 1)
        self.assertGreater(body["total_fuel_cost"], 0)
        self.assertAlmostEqual(body["total_distance_miles"], self.route.distance_miles, delta=0.1)
        self.assertEqual(body["assumptions"]["mpg"], 10)
        self.assertEqual(body["assumptions"]["vehicle_range_miles"], 500)
        self.assertEqual(body["map"]["geojson"]["features"][0]["geometry"]["type"], "LineString")
        self.assertEqual(
            round(sum(s["cost"] for s in body["fuel_stops"]), 2), body["total_fuel_cost"], "cost adds up"
        )

    def test_stops_are_ordered_and_within_range(self):
        body = self.call({"start": "Chicago, IL", "finish": "Denver, CO"})[0].json()
        miles = [s["route_mile"] for s in body["fuel_stops"]]
        self.assertEqual(miles, sorted(miles))
        points = [0.0] + miles + [body["total_distance_miles"]]
        for a, b in zip(points, points[1:]):
            self.assertLessEqual(b - a, 500.5)

    def test_post_body(self):
        resp, _ = self.call({"start": "41.88,-87.63", "finish": "39.74,-104.99"}, method="post")
        self.assertEqual(resp.status_code, 200)

    def test_custom_range_and_mpg(self):
        body = self.call({"start": "Chicago, IL", "finish": "Denver, CO",
                          "vehicle_range": 300, "mpg": 20})[0].json()
        self.assertEqual(body["assumptions"]["mpg"], 20)
        self.assertGreater(len(body["fuel_stops"]), 2)

    def test_missing_parameters(self):
        resp, gr = self.call({"start": "Chicago, IL"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "invalid_request")
        gr.assert_not_called()

    def test_non_usa_fails_fast_without_routing(self):
        resp, gr = self.call({"start": "51.5074,-0.1278", "finish": "Denver, CO"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "invalid_location")
        gr.assert_not_called()

    def test_unroutable(self):
        resp, _ = self.call({"start": "Chicago, IL", "finish": "Denver, CO"},
                            side_effect=Unroutable("No drivable route between those locations"))
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "unroutable")

    def test_provider_down(self):
        resp, _ = self.call({"start": "Chicago, IL", "finish": "Denver, CO"},
                            side_effect=RoutingError("down"))
        self.assertEqual(resp.status_code, 502)

    def test_no_stops_on_long_route_is_reported(self):
        resp, _ = self.call({"start": "Chicago, IL", "finish": "Denver, CO"}, stops=[])
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "no_feasible_fuel_plan")
