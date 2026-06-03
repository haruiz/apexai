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
import sys
from typing import Dict, Any, Optional


class CANableTelemetryDecoder:
    def __init__(self):
        self.sequence = 0

        # Latest state of all decoded telemetry channels, matching mobile
        # TelemetryPacket in mobile/app/src/main/java/.../models/DataContracts.kt.
        self.state = {
            "sequence": 0,
            "timestamp": 0.0,
            "latitude": None,
            "longitude": None,
            "speed": None,
            "heading": None,
            "altitude": None,
            "satellites": None,
            "throttle": None,
            "brake": None,
            "steering": None,
            "gear": None,
            "lap": None,
            "rpm": None,
            "waterTempF": None,
            "waterPressurePsi": None,
            "rollRateDps": None,
            "oilFilterTempF": None,
            "oilPressurePsi": None,
            "analogOilTempF": None,
            "fuelPressurePsi": None,
            "ecuMilOut": None,
            "brakePressurePsi": None,
            "ecuDbwApp1Percent": None,
            "pedalPositionPercent": None,
            "brakeSwitchApplied": None,
            "pitchRateDps": None,
            "yawRateDps": None,
            "lateralAccelG": None,
            "inlineAccelG": None,
            "fuelLevelGallons": None,
            "batteryVoltage": None,
            "verticalAccelG": None,
            "wheelSpeedFlMph": None,
            "wheelSpeedFrMph": None,
            "wheelSpeedRlMph": None,
            "wheelSpeedRrMph": None,
            "ecuSpeedMph": None,
            "outsideTempF": None,
            "engineOilTempF": None,
            "dscIntervening": None,
            "shockPots": None,
            "tireSlipVectors": None,
            "wheelSpeedDeltas": None,
        }

    @staticmethod
    def u16(data: bytes, offset: int) -> int:
        return (data[offset + 1] << 8) | data[offset]

    @staticmethod
    def s16(data: bytes, offset: int) -> int:
        value = CANableTelemetryDecoder.u16(data, offset)
        return value - 0x10000 if value & 0x8000 else value

    @staticmethod
    def s32(data: bytes, offset: int) -> int:
        value = (
            (data[offset + 3] << 24)
            | (data[offset + 2] << 16)
            | (data[offset + 1] << 8)
            | data[offset]
        )
        return value - 0x100000000 if value & 0x80000000 else value

    @staticmethod
    def percent(value: float) -> float:
        return max(0.0, min(100.0, value))

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
            self.state["ecuSpeedMph"] = self.u16(data, 4) * 0.1
            self.state["waterTempF"] = self.u16(data, 6) * 0.1

        elif can_id == 0x451:
            fl = self.u16(data, 0) * 0.1
            fr = self.u16(data, 2) * 0.1
            rl = self.u16(data, 4) * 0.1
            rr = self.u16(data, 6) * 0.1
            average_wheel_speed = (fl + fr + rl + rr) / 4.0
            self.state["wheelSpeedFlMph"] = fl
            self.state["wheelSpeedFrMph"] = fr
            self.state["wheelSpeedRlMph"] = rl
            self.state["wheelSpeedRrMph"] = rr
            self.state["wheelSpeedDeltas"] = [
                fl - average_wheel_speed,
                fr - average_wheel_speed,
                rl - average_wheel_speed,
                rr - average_wheel_speed,
            ]

        elif can_id == 0x452:
            self.state["engineOilTempF"] = self.u16(data, 0) * 0.1
            pedal_position = self.percent(self.u16(data, 6) * 0.01)
            self.state["ecuDbwApp1Percent"] = pedal_position
            self.state["throttle"] = pedal_position
            self.state["pedalPositionPercent"] = pedal_position

        elif can_id == 0x453:
            self.state["fuelLevelGallons"] = self.u16(data, 0) * 0.01
            self.state["brakeSwitchApplied"] = self.u16(data, 6) == 1

        elif can_id == 0x454:
            self.state["ecuMilOut"] = int(self.u16(data, 0))

        elif can_id == 0x455:
            self.state["inlineAccelG"] = self.s16(data, 0) * 0.01
            self.state["lateralAccelG"] = self.s16(data, 2) * 0.01
            self.state["verticalAccelG"] = self.s16(data, 4) * 0.01

        elif can_id == 0x456:
            self.state["rollRateDps"] = self.s16(data, 0) * 0.1
            self.state["pitchRateDps"] = self.s16(data, 2) * 0.1
            self.state["yawRateDps"] = self.s16(data, 4) * 0.1

        elif can_id == 0x457:
            gps_speed_mph = self.u16(data, 2) * 0.1
            brake_pressure = float(self.u16(data, 6))
            self.state["oilPressurePsi"] = self.u16(data, 0) * 0.1
            self.state["speed"] = gps_speed_mph
            self.state["fuelPressurePsi"] = self.u16(data, 4) * 0.1
            self.state["brakePressurePsi"] = brake_pressure
            self.state["brake"] = brake_pressure

        elif can_id == 0x458:
            analog_oil_temp = self.u16(data, 0) * 0.1
            self.state["analogOilTempF"] = analog_oil_temp
            self.state["oilFilterTempF"] = analog_oil_temp

        elif can_id == 0x459:
            self.state["latitude"] = self.s32(data, 0) * 0.0000001
            self.state["longitude"] = self.s32(data, 4) * 0.0000001

        else:
            # Unrecognized/unused CAN ID
            return None

        self.sequence += 1
        self.state["sequence"] = self.sequence
        return self.state.copy()


def parse_slcan_line(line: str) -> Optional[tuple[Optional[float], int, bytes]]:
    """
    Parses either <timestamp_ms>,t<can_id><dlc><data_hex> or raw
    t<can_id><dlc><data_hex> SLCAN lines.
    Returns: (timestamp_ms, can_id, data_bytes), with timestamp_ms as None when
    the source line has no timestamp prefix.
    """
    line = line.strip()
    if not line:
        return None

    try:
        timestamp_ms = None
        frame = line
        if "," in line:
            ts_str, frame = line.split(",", 1)
            timestamp_ms = float(ts_str)

        if not frame.startswith("t") or len(frame) < 5:
            return None

        can_id = int(frame[1:4], 16)
        dlc = int(frame[4], 16)
        if dlc != 8:
            return None

        payload_hex = frame[5 : 5 + dlc * 2]
        if len(payload_hex) != dlc * 2:
            return None

        data_bytes = bytes.fromhex(payload_hex)
        return timestamp_ms, can_id, data_bytes

    except Exception:
        return None


def csv_safe_row(state: Dict[str, Any]) -> Dict[str, Any]:
    row = {}
    for key, value in state.items():
        if value is None:
            row[key] = ""
        elif isinstance(value, (list, dict)):
            row[key] = json.dumps(value, separators=(",", ":"))
        else:
            row[key] = value
    return row


def main():
    default_input = "/Users/haruiz/open-source/apexai/mobile/telemetry_pull/can_raw_frames_usb_20260523_153741_885.txt"
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

                if timestamp_ms is not None:
                    decoded_state["timestamp"] = timestamp_ms / 1000.0
                decoded_frames += 1

                # Update channel stats
                stats["max_rpm"] = max(stats["max_rpm"], decoded_state["rpm"] or 0.0)
                stats["max_speed"] = max(stats["max_speed"], decoded_state["speed"] or 0.0)
                lat_g = decoded_state["lateralAccelG"] or 0.0
                stats["min_lat_g"] = min(stats["min_lat_g"], lat_g)
                stats["max_lat_g"] = max(stats["max_lat_g"], lat_g)
                stats["max_brake_psi"] = max(stats["max_brake_psi"], decoded_state["brakePressurePsi"] or 0.0)
                if (
                    decoded_state["latitude"] is not None
                    and decoded_state["longitude"] is not None
                    and (decoded_state["latitude"] != 0.0 or decoded_state["longitude"] != 0.0)
                ):
                    stats["valid_gps_points"] += 1

                # Write outputs
                if csv_writer:
                    csv_writer.writerow(csv_safe_row(decoded_state))
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
