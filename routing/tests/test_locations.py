from unittest import mock

from django.test import SimpleTestCase

from routing.locations import LocationError, in_usa, resolve_location


class LocationTests(SimpleTestCase):
    def test_coordinates_need_no_network(self):
        with mock.patch("routing.locations.requests.get") as get:
            lat, lon, method = resolve_location("41.88, -87.63")
        get.assert_not_called()
        self.assertEqual(method, "coordinates")
        self.assertEqual((lat, lon), (41.88, -87.63))

    def test_city_state_uses_offline_index(self):
        with mock.patch("routing.locations.requests.get") as get:
            lat, lon, method = resolve_location("Chicago, IL")
            full_name = resolve_location("Denver, Colorado")
        get.assert_not_called()
        self.assertEqual(method, "place_index")
        self.assertAlmostEqual(lat, 41.84, delta=0.2)
        self.assertAlmostEqual(full_name[0], 39.76, delta=0.2)

    def test_outside_usa_is_rejected(self):
        with self.assertRaisesMessage(LocationError, "outside the USA"):
            resolve_location("51.5074,-0.1278", "start")

    def test_empty_is_rejected(self):
        with self.assertRaises(LocationError):
            resolve_location("   ", "start")

    def test_street_address_falls_back_to_nominatim(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = [{"lat": "36.17", "lon": "-115.14"}]
        with mock.patch("routing.locations.requests.get", return_value=resp) as get:
            lat, lon, method = resolve_location("1 Fremont St Las Vegas")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(method, "nominatim")

    def test_nominatim_no_result(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = []
        with mock.patch("routing.locations.requests.get", return_value=resp):
            with self.assertRaisesMessage(LocationError, "Could not find"):
                resolve_location("zzzz nowhere")

    def test_in_usa_boxes(self):
        self.assertTrue(in_usa(21.3, -157.8))
        self.assertTrue(in_usa(61.2, -149.9))
        self.assertFalse(in_usa(19.43, -99.13))  # Mexico City
        self.assertFalse(in_usa(55.0, -105.0))  # central Canada
