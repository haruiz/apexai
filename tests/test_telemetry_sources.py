from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apexai.server.broadcaster import Broadcaster
from apexai.server.config import ServerConfig
from apexai.server.main import _build_source
from apexai.server.telemetry_sources import (
    CanDecodedTelemetrySource,
    CanRawChunkTelemetrySource,
    decode_can_raw_frame_file_to_csv,
    parse_can_raw_chunk_file,
)
from apexai.server.vbo_parser import parse_vbo_line


class TelemetrySourceTests(unittest.TestCase):
    def test_vbo_coordinate_parser_supports_pure_minutes_and_ddmm(self) -> None:
        pure_minutes = parse_vbo_line(
            0,
            "006 193802.600 +2289.604620 +7347.301854 10.0",
            ["sats", "time", "lat", "long", "velocity"],
        )
        ddmm = parse_vbo_line(
            1,
            "006 193802.700 +3816.007700 +12227.301860 11.0",
            ["sats", "time", "lat", "long", "velocity"],
        )

        assert pure_minutes is not None
        self.assertAlmostEqual(pure_minutes.latitude or 0.0, 38.160077, places=6)
        self.assertAlmostEqual(pure_minutes.longitude or 0.0, -122.455031, places=6)

        assert ddmm is not None
        self.assertAlmostEqual(ddmm.latitude or 0.0, 38.266795, places=6)
        self.assertAlmostEqual(ddmm.longitude or 0.0, -122.455031, places=6)

    def test_can_raw_chunk_parser_preserves_source_line_and_hex_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "can_raw_hex_chunks_usb_test.txt"
            path.write_text(
                "1779554347898,74 34 35 31 38 30 0D\n"
                "1779554347983,74 34 35 34 38 30 0D 74 34 35 35 38 30 0D\n",
                encoding="utf-8",
            )

            chunks = parse_can_raw_chunk_file(path)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].timestamp, 1779554347898.0)
        self.assertEqual(chunks[0].line, "1779554347898,74 34 35 31 38 30 0D")
        self.assertEqual(chunks[0].chunk, "74 34 35 31 38 30 0D")
        self.assertEqual(chunks[1].chunk, "74 34 35 34 38 30 0D 74 34 35 35 38 30 0D")

    def test_selected_can_txt_file_builds_can_raw_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "can_raw_hex_chunks_usb_test.txt"
            path.write_text("1779554347898,74 34 35 31 38 30 0D\n", encoding="utf-8")
            config = ServerConfig(input_file=path)

            source, sample_count, columns, duration = _build_source(config, Broadcaster())

        self.assertIsInstance(source, CanRawChunkTelemetrySource)
        self.assertEqual(sample_count, 1)
        self.assertEqual(columns, ["timestamp_ms", "raw_hex_chunk"])
        self.assertEqual(duration, 0.0)

    def test_can_raw_frame_file_decodes_to_csv_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "can_raw_frames_usb_test.txt"
            path.write_text(
                "1779554348072,t45080000070000009407\n"
                "1779554348022,t4578010000006414FFFF\n",
                encoding="utf-8",
            )

            rows, decoded_csv = decode_can_raw_frame_file_to_csv(path)

            self.assertTrue(decoded_csv.exists())
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].values["gear"], 7)
            self.assertEqual(rows[0].values["ecuSpeedMph"], 0.0)
            self.assertIsNone(rows[0].values["speed"])
            self.assertAlmostEqual(rows[0].values["waterTempF"], 194.0)
            self.assertEqual(rows[1].values["brakePressurePsi"], 65535.0)

    def test_selected_can_frame_file_builds_decoded_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "can_raw_frames_usb_test.txt"
            path.write_text("1779554348072,t45080000070000009407\n", encoding="utf-8")
            config = ServerConfig(input_file=path, decoded=True)

            source, sample_count, columns, duration = _build_source(config, Broadcaster())

        self.assertIsInstance(source, CanDecodedTelemetrySource)
        self.assertEqual(sample_count, 1)
        self.assertIn("rpm", columns)
        self.assertEqual(duration, 0.0)

    def test_row_to_can_frames_fallbacks_and_scaling(self) -> None:
        from apexai.scripts.map_server import row_to_can_frames

        # Test case 1: ecuSpeedMph is missing, fallback to speed (km/h) converted to mph
        row = {"rpm": "3000.0", "gear": "3", "speed": "100.0"}  # 100 km/h
        state = {
            "rpm": 0.0,
            "speed": 0.0,
            "ecuSpeedMph": 0.0,
            "gear": 0,
            "waterTempF": 0.0,
            "oilPressurePsi": 0.0,
            "fuelPressurePsi": 0.0,
            "brakePressurePsi": 0.0,
        }
        frames = row_to_can_frames(row, state)
        # Should generate 0x450 (rpm, gear, ecuSpeedMph) and 0x457 (speed) frames
        self.assertEqual(len(frames), 2)
        
        # Verify state values
        self.assertEqual(state["rpm"], 3000.0)
        self.assertEqual(state["gear"], 3)
        self.assertEqual(state["speed"], 100.0)
        self.assertAlmostEqual(state["ecuSpeedMph"], 100.0 * 0.621371, places=4)

        # Test case 2: speed (GPS speed) is missing, fallback to ecuSpeedMph (mph) converted to km/h
        row2 = {"ecuSpeedMph": "60.0", "brakePressurePsi": "100.0"}
        state2 = {
            "rpm": 0.0,
            "speed": 0.0,
            "ecuSpeedMph": 0.0,
            "gear": 0,
            "waterTempF": 0.0,
            "oilPressurePsi": 0.0,
            "fuelPressurePsi": 0.0,
            "brakePressurePsi": 0.0,
        }
        frames2 = row_to_can_frames(row2, state2)
        self.assertEqual(len(frames2), 2)
        self.assertEqual(state2["ecuSpeedMph"], 60.0)
        self.assertAlmostEqual(state2["speed"], 60.0 / 0.621371, places=4)


if __name__ == "__main__":
    unittest.main()
