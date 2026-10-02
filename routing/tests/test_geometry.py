from django.test import SimpleTestCase

from routing.geometry import RouteIndex, haversine_miles


class GeometryTests(SimpleTestCase):
    def setUp(self):
        # Due-east line along 40N, roughly 530 miles.
        self.coords = [(40.0, -100.0 + i) for i in range(0, 10)]
        self.index = RouteIndex(self.coords)

    def test_haversine_known_distance(self):
        self.assertAlmostEqual(haversine_miles(40.7128, -74.0060, 34.0522, -118.2437), 2445, delta=15)

    def test_densify_keeps_total_length(self):
        direct = sum(haversine_miles(*a, *b) for a, b in zip(self.coords, self.coords[1:]))
        self.assertAlmostEqual(self.index.total_miles, direct, delta=1)

    def test_rescales_to_router_distance(self):
        scaled = RouteIndex(self.coords, total_miles=600.0)
        self.assertAlmostEqual(scaled.total_miles, 600.0, places=6)

    def test_projects_nearby_stop(self):
        proj = self.index.project(40.05, -96.0, max_miles=10)
        self.assertIsNotNone(proj)
        self.assertLess(proj.distance_miles, 5)
        self.assertAlmostEqual(proj.route_mile, 4 * 52.97, delta=5)

    def test_rejects_distant_stop(self):
        self.assertIsNone(self.index.project(41.0, -96.0, max_miles=10))

    def test_needs_two_points(self):
        with self.assertRaises(ValueError):
            RouteIndex([(40.0, -100.0)])
