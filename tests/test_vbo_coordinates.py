import unittest

from apexai.server.vbo_parser import _coordinate


class VboCoordinateTests(unittest.TestCase):
    def test_vbox_minutes_normalize_to_wgs84_decimal_degrees(self):
        self.assertAlmostEqual(_coordinate(2289.604620, is_longitude=False), 38.160077)
        self.assertAlmostEqual(_coordinate(7347.301854, is_longitude=True), -122.4550309)

    def test_decimal_degrees_pass_through_unchanged(self):
        self.assertEqual(_coordinate(38.160077, is_longitude=False), 38.160077)
        self.assertEqual(_coordinate(-122.4550309, is_longitude=True), -122.4550309)
