#!/usr/bin/env python3
"""
CAN Raw Frames Decoder for ApexAI Telemetry
Decodes SLCAN raw log files strictly according to the CANable2_Pixel10.md specification.
Supports both CSV and JSONL output format options.
"""

import argparse
import csv
import json
import os
import struct
import sys
from typing import Dict, Any, List, Optional


class CANableTelemetryDecoder:
    def __init__(self):
        # Latest state of all decoded telemetry channels
        self.state = {
            "timestamp_ms": 0.0,
            "rpm": 0.0,
            "gear": 0,
            "speed_mph": 0.0,
            "water_temp_f": 0.0,
            "water_pressure_psi": 0.0,  # Unused in S54 swap spec
            "wheel_speed_fl_mph": 0.0,
            "wheel_speed_fr_mph": 0.0,
            "wheel_speed_rl_mph": 0.0,
            "wheel_speed_rr_mph": 0.0,
            "engine_oil_temp_f": 0.0,
            "outside_temp_f": 0.0,      # Unused in S54 swap spec
            "throttle_percent": 0.0,
            "fuel_level_gallons": 0.0,
            "battery_voltage": 0.0,     # Unused in S54 swap spec
            "brake_switch_applied": False,
            "ecu_mil_out": 0,
            "inline_accel_g": 0.0,
            "lateral_accel_g": 0.0,
            "vertical_accel_g": 0.0,
            "roll_rate_dps": 0.0,
            "pitch_rate_dps": 0.0,
            "yaw_rate_dps": 0.0,
            "steering": 0.0,            # Unused in S54 swap spec
            "oil_pressure_psi": 0.0,
            "gps_speed_mph": 0.0,
            "ecu_speed_mph": 0.0,
            "fuel_pressure_psi": 0.0,
            "brake_pressure_psi": 0.0,
            "oil_filter_temp_f": 0.0,   # Analog Oil Temp sensor
            "dsc_intervening": False,   # Unused in S54 swap spec
            "latitude": 0.0,
            "longitude": 0.0,
        }

    @staticmethod
    def u16(data: bytes, offset: int) -> int:
        return struct.unpack("<H", data[offset : offset + 2])[0]

    @staticmethod
    def s16(data: bytes, offset: int) -> int:
        return struct.unpack("<h", data[offset : offset + 2])[0]

    @staticmethod
    def s32(data: bytes, offset: int) -> int:
        return struct.unpack("<i", data[offset : offset + 4])[0]

    def decode_frame(self, can_id: int, data: bytes) -> Optional[Dict[str, Any]]:
        """
        Decodes a CAN frame and updates the internal telemetry state.
        Returns a copy of the updated state if the frame was recognized and decoded.
        """
        if len(data) != 8:
            return None

        # Process frames strictly according to CANable2_Pixel10.md specification
        if can_id == 0x450:
            self.state["rpm"] = float(self.u16(data, 0))
            self.state["gear"] = int(self.u16(data, 2))
            # ECU VEH SPD (ecu_speed_mph and speed_mph)
            self.state["speed_mph"] = self.u16(data, 4) * 0.1
            self.state["ecu_speed_mph"] = self.state["speed_mph"]
            self.state["water_temp_f"] = self.u16(data, 6) * 0.1

        elif can_id == 0x451:
            self.state["wheel_speed_fl_mph"] = self.u16(data, 0) * 0.1
            self.state["wheel_speed_fr_mph"] = self.u16(data, 2) * 0.1
            self.state["wheel_speed_rl_mph"] = self.u16(data, 4) * 0.1
            self.state["wheel_speed_rr_mph"] = self.u16(data, 6) * 0.1

        elif can_id == 0x452:
            self.state["engine_oil_temp_f"] = self.u16(data, 0) * 0.1
            self.state["throttle_percent"] = self.u16(data, 4) * 0.01

        elif can_id == 0x453:
            self.state["fuel_level_gallons"] = self.u16(data, 0) * 0.01
            self.state["brake_switch_applied"] = self.u16(data, 6) == 1

        elif can_id == 0x454:
            self.state["ecu_mil_out"] = int(self.u16(data, 0))

        elif can_id == 0x455:
            self.state["inline_accel_g"] = self.s16(data, 0) * 0.01
            self.state["lateral_accel_g"] = self.s16(data, 2) * 0.01
            self.state["vertical_accel_g"] = self.s16(data, 4) * 0.01

        elif can_id == 0x456:
            self.state["roll_rate_dps"] = self.s16(data, 0) * 0.1
            self.state["pitch_rate_dps"] = self.s16(data, 2) * 0.1
            self.state["yaw_rate_dps"] = self.s16(data, 4) * 0.1

        elif can_id == 0x457:
            self.state["oil_pressure_psi"] = self.u16(data, 0) * 0.1
            self.state["gps_speed_mph"] = self.u16(data, 2) * 0.1
            self.state["fuel_pressure_psi"] = self.u16(data, 4) * 0.1
            self.state["brake_pressure_psi"] = float(self.u16(data, 6))

        elif can_id == 0x458:
            self.state["oil_filter_temp_f"] = self.u16(data, 0) * 0.1

        elif can_id == 0x459:
            self.state["latitude"] = self.s32(data, 0) * 0.0000001
            self.state["longitude"] = self.s32(data, 4) * 0.0000001

        else:
            # Unrecognized/unused CAN ID
            return None

        return self.state.copy()


def parse_slcan_line(line: str) -> Optional[tuple[int, int, bytes]]:
    """
    Parses a raw log line of the format: <timestamp_ms>,t<can_id><dlc><data_hex>
    Returns: (timestamp_ms, can_id, data_bytes)
    """
    line = line.strip()
    if not line or "," not in line:
        return None

    try:
        ts_str, frame = line.split(",", 1)
        timestamp_ms = float(ts_str)

        if not frame.startswith("t") or len(frame) < 5:
            return None

        can_id = int(frame[1:4], 16)
        dlc = int(frame[4], 16)

        payload_hex = frame[5 : 5 + dlc * 2]
        if len(payload_hex) != dlc * 2:
            return None

        data_bytes = bytes.fromhex(payload_hex)
        return timestamp_ms, can_id, data_bytes

    except Exception:
        return None


def main():
    default_input = "data/can_raw_frames.txt" if os.path.exists("data/can_raw_frames.txt") else "../data/can_raw_frames.txt"
    parser = argparse.ArgumentParser(
        description="Decode raw SLCAN CAN frames log into human-readable CSV/JSONL telemetry data."
    )
    parser.add_argument(
        "input",
        type=str,
        nargs="?",
        default=default_input,
        help="Path to the input raw log file.",
    )
    parser.add_argument(
        "-o",
        "--output-csv",
        type=str,
        help="Path to the output CSV file.",
    )
    parser.add_argument(
        "-j",
        "--output-jsonl",
        type=str,
        help="Path to the output JSONL file.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable interactive terminal progress print.",
    )
    args = parser.parse_args()

    input_path = args.input
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    # Determine default output paths if none are provided
    output_csv_path = args.output_csv
    output_jsonl_path = args.output_jsonl

    if not output_csv_path and not output_jsonl_path:
        # Default to a CSV alongside the input file
        base_no_ext, _ = os.path.splitext(input_path)
        output_csv_path = f"{base_no_ext}_decoded.csv"
        print(f"No output path specified. Defaulting output CSV to: {output_csv_path}")

    decoder = CANableTelemetryDecoder()

    # Fieldnames from the telemetry state
    fieldnames = list(decoder.state.keys())

    csv_file = None
    csv_writer = None
    jsonl_file = None

    try:
        if output_csv_path:
            # Ensure parent directories exist
            os.makedirs(os.path.dirname(os.path.abspath(output_csv_path)) or ".", exist_ok=True)
            csv_file = open(output_csv_path, "w", newline="", encoding="utf-8")
            csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            csv_writer.writeheader()

        if output_jsonl_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_jsonl_path)) or ".", exist_ok=True)
            jsonl_file = open(output_jsonl_path, "w", encoding="utf-8")

        total_lines = 0
        decoded_frames = 0
        unknown_frames = set()

        # Channel stats for summary
        stats = {
            "max_rpm": 0.0,
            "max_speed": 0.0,
            "min_lat_g": 0.0,
            "max_lat_g": 0.0,
            "max_brake_psi": 0.0,
            "valid_gps_points": 0,
        }

        # First pass or buffered counts for accurate progress reporting
        print(f"Processing '{input_path}'...")
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                total_lines += 1

                parsed = parse_slcan_line(line)
                if not parsed:
                    continue

                timestamp_ms, can_id, data_bytes = parsed
                decoded_state = decoder.decode_frame(can_id, data_bytes)

                if decoded_state is None:
                    unknown_frames.add(hex(can_id))
                    continue

                # Set current timestamp
                decoded_state["timestamp_ms"] = timestamp_ms
                decoded_frames += 1

                # Update channel stats
                stats["max_rpm"] = max(stats["max_rpm"], decoded_state["rpm"])
                stats["max_speed"] = max(stats["max_speed"], decoded_state["speed_mph"])
                stats["min_lat_g"] = min(stats["min_lat_g"], decoded_state["lateral_accel_g"])
                stats["max_lat_g"] = max(stats["max_lat_g"], decoded_state["lateral_accel_g"])
                stats["max_brake_psi"] = max(stats["max_brake_psi"], decoded_state["brake_pressure_psi"])
                if decoded_state["latitude"] != 0.0 or decoded_state["longitude"] != 0.0:
                    stats["valid_gps_points"] += 1

                # Write outputs
                if csv_writer:
                    csv_writer.writerow(decoded_state)
                if jsonl_file:
                    jsonl_file.write(json.dumps(decoded_state) + "\n")

                # Progress printing
                if not args.quiet and total_lines % 20000 == 0:
                    print(f"  Processed {total_lines} lines, decoded {decoded_frames} valid packets...")

        print("\nProcessing Complete!")
        print(f"Total lines read:      {total_lines}")
        print(f"Valid decoded frames:  {decoded_frames}")
        if unknown_frames:
            print(f"Unrecognized CAN IDs:  {', '.join(sorted(list(unknown_frames)))}")

        print("\n--- Telemetry Highlights ---")
        print(f"Peak Engine RPM:       {stats['max_rpm']:.0f} RPM")
        print(f"Peak Speed:            {stats['max_speed']:.1f} mph")
        print(f"Peak Brake Pressure:   {stats['max_brake_psi']:.1f} psi")
        print(f"Lateral G Range:       [{stats['min_lat_g']:.2f}g, {stats['max_lat_g']:.2f}g]")
        print(f"Decoded GPS Points:    {stats['valid_gps_points']}")

        if csv_file:
            print(f"\nSaved CSV output to:  {output_csv_path}")
        if jsonl_file:
            print(f"Saved JSONL output to: {output_jsonl_path}")

    finally:
        if csv_file:
            csv_file.close()
        if jsonl_file:
            jsonl_file.close()


if __name__ == "__main__":
    main()
