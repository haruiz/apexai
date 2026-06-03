#!/usr/bin/env python3
"""
Interactive FastAPI Server for CAN Telemetry and GPS track plotting.
Reads and parses decoded CAN CSV files dynamically, serving a premium web-based
automotive dashboard with real-time gauges, live simulation, and track coloring.
"""
import json
import csv
import argparse
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from apexai.scripts.simulate_can import parse_log_file as parse_chunk_log_file


@dataclass
class AppSettings:
    maps_api_key: str = ""
    sim_host: str = "127.0.0.1"
    sim_port: int = 8080


DATA_ROOTS = [Path.cwd()]
APP_SETTINGS = AppSettings()
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "map_server.html"


def render_dashboard_html() -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__DEFAULT_API_KEY_JSON__", json.dumps(APP_SETTINGS.maps_api_key))


def coordinate_rejection_reason(latitude: Optional[float], longitude: Optional[float]) -> Optional[str]:
    if latitude is None or longitude is None:
        return "missing latitude/longitude"
    if latitude == 0.0 and longitude == 0.0:
        return "zero GPS placeholder"
    if abs(latitude) == 90.0 and longitude == 0.0:
        return "startup GPS sentinel"
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return "outside latitude/longitude range"
    return None


def is_valid_coordinate(latitude: Optional[float], longitude: Optional[float]) -> bool:
    return coordinate_rejection_reason(latitude, longitude) is None


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def find_csv_files(data_roots: List[Path]) -> List[Dict[str, Any]]:
    files = []
    for root in data_roots:
        if root.exists() and root.is_dir():
            for p in root.rglob("*.csv"):
                stat = p.stat()
                files.append({
                    "name": p.name,
                    "path": _display_path(p, root),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "directory": p.parent.name
                })
    # Sort files by modification time descending (newest first)
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files


def find_chunk_files(data_roots: List[Path]) -> List[Dict[str, Any]]:
    files = []
    for root in data_roots:
        if root.exists() and root.is_dir():
            for p in root.rglob("can_raw_hex_chunks*.txt"):
                stat = p.stat()
                files.append({
                    "name": p.name,
                    "path": _display_path(p, root),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "directory": p.parent.name
                })
    files.sort(key=lambda x: x["mtime"], reverse=True)
    return files


def resolve_data_file(path_value: str) -> Path:
    requested_path = Path(path_value).expanduser()
    candidates = [requested_path] if requested_path.is_absolute() else [root / requested_path for root in DATA_ROOTS]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    raise HTTPException(status_code=404, detail="Requested file not found.")


def to_u16_bytes(val: float, multiplier: float = 1.0) -> Tuple[int, int]:
    v = int(float(val or 0.0) * multiplier)
    v = max(0, min(65535, v))
    return v & 0xFF, (v >> 8) & 0xFF


def to_s16_bytes(val: float, multiplier: float = 1.0) -> Tuple[int, int]:
    v = int(float(val or 0.0) * multiplier)
    v = max(-32768, min(32767, v))
    if v < 0:
        v += 65536
    return v & 0xFF, (v >> 8) & 0xFF


def to_s32_bytes(val: float, multiplier: float = 1.0) -> Tuple[int, int, int, int]:
    v = int(float(val or 0.0) * multiplier)
    v = max(-2147483648, min(2147483647, v))
    if v < 0:
        v += 4294967296
    return v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF


def encode_can_frame(can_id: int, data: bytearray) -> bytes:
    hex_str = "".join(f"{b:02X}" for b in data)
    return f"t{can_id:03X}8{hex_str}\r".encode("ascii")


def row_to_can_frames(row: Dict[str, Any], current_state: Dict[str, Any]) -> List[bytes]:
    frames = []
    
    # 0x450: rpm, gear, ecuSpeedMph, waterTempF
    has_450 = False
    for col in ["rpm", "gear", "ecuSpeedMph", "waterTempF"]:
        val = row.get(col)
        # Fallback column names for ecuSpeedMph
        if col == "ecuSpeedMph" and (val is None or val == ""):
            val = row.get("ecu_speed_mph") or row.get("speed_mph")
        if val is not None and val != "":
            has_450 = True
            try:
                current_state[col] = float(val)
            except ValueError:
                pass

    # Fallback to speed (GPS speed, which is in km/h) converted to mph if ecuSpeedMph is missing
    ecu_speed_row = row.get("ecuSpeedMph") or row.get("ecu_speed_mph") or row.get("speed_mph")
    if (ecu_speed_row is None or ecu_speed_row == "") and row.get("speed") is not None and row.get("speed") != "":
        try:
            current_state["ecuSpeedMph"] = float(row["speed"]) * 0.621371
            has_450 = True
        except ValueError:
            pass

    if has_450:
        data = bytearray(8)
        r_lsb, r_msb = to_u16_bytes(current_state.get("rpm", 0.0))
        data[0], data[1] = r_lsb, r_msb
        g_lsb, g_msb = to_u16_bytes(current_state.get("gear", 0))
        data[2], data[3] = g_lsb, g_msb
        s_lsb, s_msb = to_u16_bytes(current_state.get("ecuSpeedMph", 0.0), 10.0)
        data[4], data[5] = s_lsb, s_msb
        w_lsb, w_msb = to_u16_bytes(current_state.get("waterTempF", 0.0), 10.0)
        data[6], data[7] = w_lsb, w_msb
        frames.append(encode_can_frame(0x450, data))

    # 0x451: wheelSpeedFlMph, wheelSpeedFrMph, wheelSpeedRlMph, wheelSpeedRrMph
    has_451 = False
    for col in ["wheelSpeedFlMph", "wheelSpeedFrMph", "wheelSpeedRlMph", "wheelSpeedRrMph"]:
        if row.get(col) is not None and row.get(col) != "":
            has_451 = True
            try:
                current_state[col] = float(row[col])
            except ValueError:
                pass
    if has_451:
        data = bytearray(8)
        f_lsb, f_msb = to_u16_bytes(current_state.get("wheelSpeedFlMph", 0.0), 10.0)
        data[0], data[1] = f_lsb, f_msb
        r_lsb, r_msb = to_u16_bytes(current_state.get("wheelSpeedFrMph", 0.0), 10.0)
        data[2], data[3] = r_lsb, r_msb
        l_lsb, l_msb = to_u16_bytes(current_state.get("wheelSpeedRlMph", 0.0), 10.0)
        data[4], data[5] = l_lsb, l_msb
        o_lsb, o_msb = to_u16_bytes(current_state.get("wheelSpeedRrMph", 0.0), 10.0)
        data[6], data[7] = o_lsb, o_msb
        frames.append(encode_can_frame(0x451, data))

    # 0x452: engineOilTempF, throttle
    has_452 = False
    for col in ["engineOilTempF", "throttle"]:
        if row.get(col) is not None and row.get(col) != "":
            has_452 = True
            try:
                current_state[col] = float(row[col])
            except ValueError:
                pass
    if has_452:
        data = bytearray(8)
        o_lsb, o_msb = to_u16_bytes(current_state.get("engineOilTempF", 0.0), 10.0)
        data[0], data[1] = o_lsb, o_msb
        t_lsb, t_msb = to_u16_bytes(current_state.get("throttle", 0.0), 100.0)
        data[6], data[7] = t_lsb, t_msb
        frames.append(encode_can_frame(0x452, data))

    # 0x453: fuelLevelGallons, brakeSwitchApplied
    has_453 = False
    for col in ["fuelLevelGallons", "brakeSwitchApplied"]:
        if row.get(col) is not None and row.get(col) != "":
            has_453 = True
            try:
                if col == "brakeSwitchApplied":
                    current_state[col] = 1 if row[col] in ["True", "1"] else 0
                else:
                    current_state[col] = float(row[col])
            except ValueError:
                pass
    if has_453:
        data = bytearray(8)
        f_lsb, f_msb = to_u16_bytes(current_state.get("fuelLevelGallons", 0.0), 100.0)
        data[0], data[1] = f_lsb, f_msb
        data[6] = int(current_state.get("brakeSwitchApplied", 0))
        frames.append(encode_can_frame(0x453, data))
    # 0x454: ecuMilOut
    if row.get("ecuMilOut") is not None and row.get("ecuMilOut") != "":
        try:
            current_state["ecuMilOut"] = float(row["ecuMilOut"])
        except ValueError:
            pass
        data = bytearray(8)
        mil_lsb, mil_msb = to_u16_bytes(current_state.get("ecuMilOut", 0.0))
        data[0], data[1] = mil_lsb, mil_msb
        frames.append(encode_can_frame(0x454, data))

    # 0x455: inlineAccelG, lateralAccelG, verticalAccelG
    has_455 = False
    for col in ["inlineAccelG", "lateralAccelG", "verticalAccelG"]:
        if row.get(col) is not None and row.get(col) != "":
            has_455 = True
            try:
                current_state[col] = float(row[col])
            except ValueError:
                pass
    if has_455:
        data = bytearray(8)
        i_lsb, i_msb = to_s16_bytes(current_state.get("inlineAccelG", 0.0), 100.0)
        data[0], data[1] = i_lsb, i_msb
        l_lsb, l_msb = to_s16_bytes(current_state.get("lateralAccelG", 0.0), 100.0)
        data[2], data[3] = l_lsb, l_msb
        v_lsb, v_msb = to_s16_bytes(current_state.get("verticalAccelG", 0.0), 100.0)
        data[4], data[5] = v_lsb, v_msb
        frames.append(encode_can_frame(0x455, data))

    # 0x456: rollRateDps, pitchRateDps, yawRateDps
    has_456 = False
    for col in ["rollRateDps", "pitchRateDps", "yawRateDps"]:
        if row.get(col) is not None and row.get(col) != "":
            has_456 = True
            try:
                current_state[col] = float(row[col])
            except ValueError:
                pass
    if has_456:
        data = bytearray(8)
        r_lsb, r_msb = to_s16_bytes(current_state.get("rollRateDps", 0.0), 10.0)
        data[0], data[1] = r_lsb, r_msb
        p_lsb, p_msb = to_s16_bytes(current_state.get("pitchRateDps", 0.0), 10.0)
        data[2], data[3] = p_lsb, p_msb
        y_lsb, y_msb = to_s16_bytes(current_state.get("yawRateDps", 0.0), 10.0)
        data[4], data[5] = y_lsb, y_msb
        frames.append(encode_can_frame(0x456, data))

    # 0x457: oilPressurePsi, speed, fuelPressurePsi, brakePressurePsi
    has_457 = False
    for col in ["oilPressurePsi", "speed", "fuelPressurePsi", "brakePressurePsi"]:
        val = row.get(col)
        # Fallback column names for speed (GPS speed)
        if col == "speed" and (val is None or val == ""):
            val = row.get("gps_speed_mph")
        if val is not None and val != "":
            has_457 = True
            try:
                current_state[col] = float(val)
            except ValueError:
                pass

    # Fallback to ecuSpeedMph (which is in mph) converted to km/h if speed is missing
    gps_speed_row = row.get("speed") or row.get("gps_speed_mph")
    if (gps_speed_row is None or gps_speed_row == "") and row.get("ecuSpeedMph") is not None and row.get("ecuSpeedMph") != "":
        try:
            current_state["speed"] = float(row["ecuSpeedMph"]) / 0.621371
            has_457 = True
        except ValueError:
            pass

    if has_457:
        data = bytearray(8)
        o_lsb, o_msb = to_u16_bytes(current_state.get("oilPressurePsi", 0.0), 10.0)
        data[0], data[1] = o_lsb, o_msb
        # GPS speed in the CAN frame is expected to be in mph.
        # Since speed in current_state is in km/h, scale by 0.621371.
        s_lsb, s_msb = to_u16_bytes(current_state.get("speed", 0.0) * 0.621371, 10.0)
        data[2], data[3] = s_lsb, s_msb
        f_lsb, f_msb = to_u16_bytes(current_state.get("fuelPressurePsi", 0.0), 10.0)
        data[4], data[5] = f_lsb, f_msb
        b_lsb, b_msb = to_u16_bytes(current_state.get("brakePressurePsi", 0.0), 1.0)
        data[6], data[7] = b_lsb, b_msb
        frames.append(encode_can_frame(0x457, data))

    # 0x458: analogOilTempF
    if row.get("analogOilTempF") is not None and row.get("analogOilTempF") != "":
        try:
            current_state["analogOilTempF"] = float(row["analogOilTempF"])
        except ValueError:
            pass
        data = bytearray(8)
        a_lsb, a_msb = to_u16_bytes(current_state["analogOilTempF"], 10.0)
        data[0], data[1] = a_lsb, a_msb
        frames.append(encode_can_frame(0x458, data))

    # 0x459: latitude, longitude
    if row.get("latitude") is not None and row.get("latitude") != "" and row.get("longitude") is not None and row.get("longitude") != "":
        try:
            current_state["latitude"] = float(row["latitude"])
            current_state["longitude"] = float(row["longitude"])
            data = bytearray(8)
            lat_bytes = to_s32_bytes(current_state["latitude"], 10000000.0)
            lng_bytes = to_s32_bytes(current_state["longitude"], 10000000.0)
            data[0], data[1], data[2], data[3] = lat_bytes
            data[4], data[5], data[6], data[7] = lng_bytes
            frames.append(encode_can_frame(0x459, data))
        except ValueError:
            pass

    return frames


def parse_csv_to_can_chunks(file_path: Path) -> List[Tuple[float, bytes]]:
    chunks = []
    current_state = {
        "rpm": 0.0,
        "speed": 0.0,
        "ecuSpeedMph": 0.0,
        "gear": 0,
        "throttle": 0.0,
        "brakePressurePsi": 0.0,
        "brakeSwitchApplied": 0,
        "fuelLevelGallons": 0.0,
        "engineOilTempF": 0.0,
        "inlineAccelG": 0.0,
        "lateralAccelG": 0.0,
        "verticalAccelG": 0.0,
        "rollRateDps": 0.0,
        "pitchRateDps": 0.0,
        "yawRateDps": 0.0,
        "oilPressurePsi": 0.0,
        "fuelPressurePsi": 0.0,
        "analogOilTempF": 0.0,
        "latitude": 0.0,
        "longitude": 0.0,
    }
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_val = row.get("timestamp")
            if ts_val:
                try:
                    timestamp_ms = float(ts_val) * 1000.0
                except ValueError:
                    timestamp_ms = 0.0
            else:
                timestamp_ms = 0.0
                
            row_frames = row_to_can_frames(row, current_state)
            if row_frames:
                merged_chunk = b"".join(row_frames)
                chunks.append((timestamp_ms, merged_chunk))
                
    # Sort chunks by timestamp
    chunks.sort(key=lambda x: x[0])
    return chunks


def parse_csv_telemetry(file_path: Path, min_distance_degrees: float = 0.0) -> Dict[str, Any]:
    points = []
    samples = []
    current_state = {
        "rpm": 0.0,
        "speed": 0.0,
        "gear": 0,
        "throttle": 0.0,
        "brakePressurePsi": 0.0,
        "lateralAccelG": 0.0,
        "inlineAccelG": 0.0,
    }
    
    stats = {
        "max_rpm": 0.0,
        "max_speed": 0.0,
        "max_brake_psi": 0.0,
        "min_lat_g": 0.0,
        "max_lat_g": 0.0,
        "min_inline_g": 0.0,
        "max_inline_g": 0.0,
        "lines": 0,
        "valid_gps_points": 0,
    }
    
    last_lat = None
    last_lng = None
    last_route_lat = None
    last_route_lng = None
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for line_idx, row in enumerate(reader, start=2):
            stats["lines"] += 1
            
            # Forward-fill stateful telemetry variables if present in the row
            for m in ["rpm", "speed", "gear", "throttle", "brakePressurePsi", "lateralAccelG", "inlineAccelG"]:
                val = row.get(m)
                if val is not None and val != "":
                    try:
                        if m == "gear":
                            current_state[m] = int(float(val))
                        else:
                            current_state[m] = float(val)
                    except ValueError:
                        pass
            
            # Record peaks
            stats["max_rpm"] = max(stats["max_rpm"], current_state["rpm"])
            stats["max_speed"] = max(stats["max_speed"], current_state["speed"])
            stats["max_brake_psi"] = max(stats["max_brake_psi"], current_state["brakePressurePsi"])
            stats["min_lat_g"] = min(stats["min_lat_g"], current_state["lateralAccelG"])
            stats["max_lat_g"] = max(stats["max_lat_g"], current_state["lateralAccelG"])
            stats["min_inline_g"] = min(stats["min_inline_g"], current_state["inlineAccelG"])
            stats["max_inline_g"] = max(stats["max_inline_g"], current_state["inlineAccelG"])
            
            # Check if GPS point is present
            lat_str = row.get("latitude")
            lng_str = row.get("longitude")
            if lat_str and lng_str:
                try:
                    lat = float(lat_str)
                    lng = float(lng_str)
                    if is_valid_coordinate(lat, lng):
                        last_lat = lat
                        last_lng = lng
                        stats["valid_gps_points"] += 1

                        if last_route_lat is None or last_route_lng is None:
                            moved = None
                        else:
                            moved = abs(lat - last_route_lat) + abs(lng - last_route_lng)

                        if moved is None or moved >= min_distance_degrees:
                            point = {
                                "lat": round(lat, 7),
                                "lng": round(lng, 7),
                                "timestamp": float(row["timestamp"]) if row.get("timestamp") else None,
                                "sequence": int(row["sequence"]) if row.get("sequence") else stats["lines"],
                                "rpm": current_state["rpm"],
                                "speed": current_state["speed"],
                                "gear": current_state["gear"],
                                "throttle": current_state["throttle"],
                                "brakePressurePsi": current_state["brakePressurePsi"],
                                "lateralAccelG": current_state["lateralAccelG"],
                                "inlineAccelG": current_state["inlineAccelG"],
                            }
                            points.append(point)
                            last_route_lat = lat
                            last_route_lng = lng
                except ValueError:
                    pass

            sample = {
                "lat": round(last_lat, 7) if last_lat is not None else None,
                "lng": round(last_lng, 7) if last_lng is not None else None,
                "timestamp": float(row["timestamp"]) if row.get("timestamp") else None,
                "sequence": int(row["sequence"]) if row.get("sequence") else stats["lines"],
                "rpm": current_state["rpm"],
                "speed": current_state["speed"],
                "gear": current_state["gear"],
                "throttle": current_state["throttle"],
                "brakePressurePsi": current_state["brakePressurePsi"],
                "lateralAccelG": current_state["lateralAccelG"],
                "inlineAccelG": current_state["inlineAccelG"],
            }
            samples.append(sample)
                    
    bounds = {}
    if points:
        bounds = {
            "minLat": min(p["lat"] for p in points),
            "maxLat": max(p["lat"] for p in points),
            "minLng": min(p["lng"] for p in points),
            "maxLng": max(p["lng"] for p in points),
        }
        
    return {
        "points": points,
        "samples": samples,
        "bounds": bounds,
        "stats": stats
    }


class ChunkReplayServer:
    def __init__(self, bind_ip: str, port: int):
        self.bind_ip = bind_ip
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.client_socket: Optional[socket.socket] = None
        self.accept_thread: Optional[threading.Thread] = None
        self.replay_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.status: Dict[str, Any] = {
            "serverRunning": False,
            "clientConnected": False,
            "streaming": False,
            "sentChunks": 0,
            "totalChunks": 0,
            "chunkFile": None,
            "lastError": None,
            "bind": bind_ip,
            "port": port,
        }

    def ensure_server(self) -> None:
        with self.lock:
            if self.server_socket is not None:
                return

            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.bind_ip, self.port))
            server_socket.listen(1)
            self.server_socket = server_socket
            self.status["serverRunning"] = True
            self.status["lastError"] = None

            self.accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self.accept_thread.start()

    def _accept_loop(self) -> None:
        while True:
            try:
                if self.server_socket is None:
                    return
                client_socket, _client_addr = self.server_socket.accept()
                with self.lock:
                    if self.client_socket is not None:
                        try:
                            self.client_socket.close()
                        except OSError:
                            pass
                    self.client_socket = client_socket
                    self.status["clientConnected"] = True
                    self.status["lastError"] = None
            except OSError as exc:
                with self.lock:
                    self.status["serverRunning"] = False
                    self.status["clientConnected"] = False
                    self.status["lastError"] = str(exc)
                return

    def start_replay(self, chunk_file: Path, speed: float, loop: bool = False) -> Dict[str, Any]:
        self.ensure_server()
        chunk_file = chunk_file.resolve()
        if chunk_file.suffix.lower() == ".csv":
            chunks = parse_csv_to_can_chunks(chunk_file)
        else:
            chunks = parse_chunk_log_file(str(chunk_file))
            
        if not chunks:
            raise ValueError("No valid raw serial chunks found in selected file.")

        self.stop_replay()
        self.stop_event.clear()
        with self.lock:
            self.status.update({
                "streaming": True,
                "sentChunks": 0,
                "totalChunks": len(chunks),
                "chunkFile": str(chunk_file),
                "lastError": None,
            })

        self.replay_thread = threading.Thread(
            target=self._stream_chunks,
            args=(chunks, speed, loop),
            daemon=True,
        )
        self.replay_thread.start()
        return self.snapshot()

    def stop_replay(self) -> Dict[str, Any]:
        self.stop_event.set()
        replay_thread = self.replay_thread
        if replay_thread and replay_thread.is_alive():
            replay_thread.join(timeout=1.0)
        self.replay_thread = None
        with self.lock:
            self.status["streaming"] = False
        return self.snapshot()

    def _stream_chunks(self, chunks: List[Any], speed: float, loop: bool) -> None:
        try:
            while not self.stop_event.is_set():
                start_time = time.time()
                first_chunk_ts = chunks[0][0]

                for index, (timestamp_ms, chunk) in enumerate(chunks):
                    if self.stop_event.is_set():
                        break

                    if speed > 0.0 and index > 0:
                        elapsed_log_sec = (timestamp_ms - first_chunk_ts) / 1000.0
                        target_time = start_time + (elapsed_log_sec / speed)
                        sleep_duration = target_time - time.time()
                        if sleep_duration > 0:
                            self.stop_event.wait(sleep_duration)

                    with self.lock:
                        client_socket = self.client_socket

                    if client_socket is not None:
                        try:
                            client_socket.sendall(chunk)
                        except OSError as exc:
                            with self.lock:
                                self.status["clientConnected"] = False
                                self.status["lastError"] = str(exc)
                                if self.client_socket is client_socket:
                                    self.client_socket = None
                            try:
                                client_socket.close()
                            except OSError:
                                pass

                    with self.lock:
                        self.status["sentChunks"] = index + 1

                if not loop:
                    break
        finally:
            with self.lock:
                self.status["streaming"] = False

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return dict(self.status)


chunk_replay_server = ChunkReplayServer(APP_SETTINGS.sim_host, APP_SETTINGS.sim_port)


# ==========================================
# FASTAPI APPLICATION DEFINITION
# ==========================================
app = FastAPI(
    title="ApexAI CAN Telemetry Dashboard",
    description="Interactive telemetry visualization with live gauges and route analysis."
)


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    # Load and pre-fill Google Maps API Key from global state
    return HTMLResponse(content=render_dashboard_html())


@app.get("/api/files")
async def get_files():
    try:
        return find_csv_files(DATA_ROOTS)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chunk-files")
async def get_chunk_files():
    try:
        return find_chunk_files(DATA_ROOTS)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/points")
async def get_points(
    file: str = Query(..., description="Relative path of the CSV file"),
    min_distance: float = Query(0.00001, description="Minimum distance in degrees to filter consecutive coordinates")
):
    try:
        safe_path = resolve_data_file(file)
        data = parse_csv_telemetry(safe_path, min_distance)
        return JSONResponse(content=data)
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error parsing CSV: {str(e)}")


@app.post("/api/chunk-replay/start")
async def start_chunk_replay(payload: Dict[str, Any] = Body(...)):
    try:
        chunk_file = payload.get("file")
        if not chunk_file:
            raise HTTPException(status_code=400, detail="Missing chunk file path.")
        safe_path = resolve_data_file(str(chunk_file))
        speed = float(payload.get("speed", 1.0))
        loop = bool(payload.get("loop", False))
        status = chunk_replay_server.start_replay(safe_path, speed=speed, loop=loop)
        return JSONResponse(content=status)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), **chunk_replay_server.snapshot()})


@app.post("/api/chunk-replay/stop")
async def stop_chunk_replay():
    return JSONResponse(content=chunk_replay_server.stop_replay())


@app.get("/api/chunk-replay/status")
async def chunk_replay_status():
    return JSONResponse(content=chunk_replay_server.snapshot())


def main() -> int:
    global APP_SETTINGS, DATA_ROOTS, chunk_replay_server

    parser = argparse.ArgumentParser(
        description="FastAPI Web Server for ApexAI GPS Track & CAN Telemetry Dashboard."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host address to bind the server to. Default: 0.0.0.0",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8000,
        help="Port to run the FastAPI server on. Default: 8000",
    )
    parser.add_argument(
        "--maps-api-key",
        default=APP_SETTINGS.maps_api_key,
        help="Google Maps Javascript API Key.",
    )
    parser.add_argument(
        "-d",
        "--data-path",
        action="append",
        default=None,
        help=(
            "Directory to scan for decoded CSV and CAN raw chunk files. "
            "Can be passed multiple times. Defaults to the current working directory."
        ),
    )
    parser.add_argument(
        "--sim-host",
        default=APP_SETTINGS.sim_host,
        help=f"CAN chunk simulator bind address. Default: {APP_SETTINGS.sim_host}",
    )
    parser.add_argument(
        "--sim-port",
        type=int,
        default=APP_SETTINGS.sim_port,
        help=f"CAN chunk simulator TCP port. Default: {APP_SETTINGS.sim_port}",
    )
    args = parser.parse_args()

    APP_SETTINGS = AppSettings(maps_api_key=args.maps_api_key, sim_host=args.sim_host, sim_port=args.sim_port)
    DATA_ROOTS = [Path(path).expanduser().resolve() for path in (args.data_path or [Path.cwd()])]
    chunk_replay_server = ChunkReplayServer(APP_SETTINGS.sim_host, APP_SETTINGS.sim_port)
    chunk_replay_server.ensure_server()

    print(f"Starting ApexAI Telemetry Dashboard at: http://{args.host}:{args.port}")
    print("Data paths:")
    for data_root in DATA_ROOTS:
        print(f"  {data_root}")
    print(f"CAN chunk simulator listening on {APP_SETTINGS.sim_host}:{APP_SETTINGS.sim_port}")
    print(f"To connect Android through adb, run: adb reverse tcp:{APP_SETTINGS.sim_port} tcp:{APP_SETTINGS.sim_port}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
