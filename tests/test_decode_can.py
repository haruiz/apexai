import os
import sys
import unittest

# Allow importing from scripts directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.decode_can import CANableTelemetryDecoder, parse_slcan_line


class TestDecodeCan(unittest.TestCase):
    def test_parse_slcan_line(self):
        line = "1779411083639,t45080000070000001403"
        parsed = parse_slcan_line(line)
        self.assertIsNotNone(parsed)
        ts, can_id, data = parsed
        self.assertEqual(ts, 1779411083639.0)
        self.assertEqual(can_id, 0x450)
        self.assertEqual(data, bytes.fromhex("0000070000001403"))

    def test_parse_slcan_line_invalid(self):
        # Empty line
        self.assertIsNone(parse_slcan_line(""))
        # Malformed line
        self.assertIsNone(parse_slcan_line("123,x123"))
        # Invalid payload length
        self.assertIsNone(parse_slcan_line("123,t450800"))

    def test_decode_0x450(self):
        decoder = CANableTelemetryDecoder()
        # rpm: bytes 0-1 = 1BE0 = 7136
        # gear: bytes 2-3 = 0005 = 5
        # speed: bytes 4-5 = 03E8 = 1000 * 0.1 = 100.0 mph
        # waterTemp: bytes 6-7 = 02D2 = 722 * 0.1 = 72.2 F
        data = bytes.fromhex("E01B0500E803D202")  # LE representation
        state = decoder.decode_frame(0x450, data)
        self.assertIsNotNone(state)
        self.assertEqual(state["rpm"], 7136.0)
        self.assertEqual(state["gear"], 5)
        self.assertAlmostEqual(state["speed_mph"], 100.0)
        self.assertAlmostEqual(state["ecu_speed_mph"], 100.0)
        self.assertAlmostEqual(state["water_temp_f"], 72.2)

    def test_decode_0x451(self):
        decoder = CANableTelemetryDecoder()
        # FL speed: bytes 0-1 = 01F9 = 505 * 0.1 = 50.5 mph
        # FR speed: bytes 2-3 = 01FA = 506 * 0.1 = 50.6 mph
        # RL speed: bytes 4-5 = 01FB = 507 * 0.1 = 50.7 mph
        # RR speed: bytes 6-7 = 01FC = 508 * 0.1 = 50.8 mph
        data = bytes.fromhex("F901FA01FB01FC01")
        state = decoder.decode_frame(0x451, data)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state["wheel_speed_fl_mph"], 50.5)
        self.assertAlmostEqual(state["wheel_speed_fr_mph"], 50.6)
        self.assertAlmostEqual(state["wheel_speed_rl_mph"], 50.7)
        self.assertAlmostEqual(state["wheel_speed_rr_mph"], 50.8)

    def test_decode_0x452(self):
        decoder = CANableTelemetryDecoder()
        # engine_oil_temp_f: bytes 0-1 = 0839 = 2105 * 0.1 = 210.5 F
        # throttle_percent: bytes 4-5 = 2166 = 8550 * 0.01 = 85.5%
        data = bytes.fromhex("3908000066210000")
        state = decoder.decode_frame(0x452, data)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state["engine_oil_temp_f"], 210.5)
        self.assertAlmostEqual(state["throttle_percent"], 85.5)

    def test_decode_0x453(self):
        decoder = CANableTelemetryDecoder()
        # fuel_level_gallons: bytes 0-1 = 04E2 = 1250 * 0.01 = 12.5 gal
        # brake_switch_applied: bytes 6-7 = 0001 = True (applied)
        data = bytes.fromhex("E204000000000100")
        state = decoder.decode_frame(0x453, data)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state["fuel_level_gallons"], 12.5)
        self.assertTrue(state["brake_switch_applied"])

    def test_decode_0x455_signed(self):
        decoder = CANableTelemetryDecoder()
        # inline_accel_g: bytes 0-1 = FF9E = -98 * 0.01 = -0.98 g
        # lateral_accel_g: bytes 2-3 = 002D = 45 * 0.01 = 0.45 g
        # vertical_accel_g: bytes 4-5 = FFF6 = -10 * 0.01 = -0.10 g
        data = bytes.fromhex("9EFF2D00F6FF0000")
        state = decoder.decode_frame(0x455, data)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state["inline_accel_g"], -0.98)
        self.assertAlmostEqual(state["lateral_accel_g"], 0.45)
        self.assertAlmostEqual(state["vertical_accel_g"], -0.10)

    def test_decode_0x456_signed(self):
        decoder = CANableTelemetryDecoder()
        # roll_rate_dps: bytes 0-1 = 009A = 154 * 0.1 = 15.4 dps
        # pitch_rate_dps: bytes 2-3 = FF1A = -230 * 0.1 = -23.0 dps
        # yaw_rate_dps: bytes 4-5 = FF83 = -125 * 0.1 = -12.5 dps
        data = bytes.fromhex("9A001AFF83FF0000")
        state = decoder.decode_frame(0x456, data)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state["roll_rate_dps"], 15.4)
        self.assertAlmostEqual(state["pitch_rate_dps"], -23.0)
        self.assertAlmostEqual(state["yaw_rate_dps"], -12.5)

    def test_decode_0x457(self):
        decoder = CANableTelemetryDecoder()
        # oil_pressure_psi: bytes 0-1 = 028F = 655 * 0.1 = 65.5 psi
        # gps_speed_mph: bytes 2-3 = 0338 = 824 * 0.1 = 82.4 mph
        # fuel_pressure_psi: bytes 4-5 = 0246 = 582 * 0.1 = 58.2 psi
        # brake_pressure_psi: bytes 6-7 = 008C = 140 * 1.0 = 140.0 psi
        data = bytes.fromhex("8F02380346028C00")
        state = decoder.decode_frame(0x457, data)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state["oil_pressure_psi"], 65.5)
        self.assertAlmostEqual(state["gps_speed_mph"], 82.4)
        self.assertAlmostEqual(state["fuel_pressure_psi"], 58.2)
        self.assertAlmostEqual(state["brake_pressure_psi"], 140.0)

    def test_decode_0x459_gps(self):
        decoder = CANableTelemetryDecoder()
        # lat: bytes 0-3 = 0x16209707 = 371234567 * 0.0000001 = 37.1234567 deg
        # lon: bytes 4-7 = 0xB6FFAEE0 = -1224757536 * 0.0000001 = -122.4757536 deg
        data = bytes.fromhex("07972016E0AEFFB6")
        state = decoder.decode_frame(0x459, data)
        self.assertIsNotNone(state)
        self.assertAlmostEqual(state["latitude"], 37.1234567)
        self.assertAlmostEqual(state["longitude"], -122.4757536)


if __name__ == "__main__":
    unittest.main()
