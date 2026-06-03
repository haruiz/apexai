"""Async telemetry source implementations for VBO and raw CAN chunk replay."""

from __future__ import annotations

import asyncio
import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .broadcaster import Broadcaster
from .schemas import (
    CanDecodedPacket,
    CanRawChunkPacket,
    ReplayState,
    TelemetryPacket,
    TelemetryStreamPacket,
    TelemetryTracePoint,
)
from .vbo_parser import parse_vbo_line

logger = logging.getLogger(__name__)

try:
    from apexai.scripts.decode_can import CANableTelemetryDecoder, csv_safe_row, parse_slcan_line
except ImportError:  # pragma: no cover - exercised only in packaged layouts without scripts/
    CANableTelemetryDecoder = None
    csv_safe_row = None
    parse_slcan_line = None


@dataclass
class ParsedVBO:
    file_path: str
    columns: list[str]
    data_lines: list[str]
    first_timestamp: float | None
    last_timestamp: float | None
    sequence_offset: int
    time_offset: float


@dataclass
class ParsedCanRawChunk:
    sequence: int
    timestamp: float
    line: str
    chunk: str


@dataclass
class ParsedCanDecodedRow:
    sequence: int
    timestamp: float
    values: dict[str, Any]


class TelemetrySource(Protocol):
    """Control surface shared by telemetry producers used by the API."""

    total_samples: int
    latest_packet: TelemetryStreamPacket | None

    def state(self) -> ReplayState:
        """Return a serializable snapshot for ``GET /state``."""

    async def play(self) -> ReplayState:
        """Start or resume publishing telemetry packets."""

    async def pause(self) -> ReplayState:
        """Pause packet publication without discarding source configuration."""

    async def stop(self) -> ReplayState:
        """Stop publishing telemetry and reset transient state."""

    async def reset(self) -> ReplayState:
        """Reset source state without necessarily closing the server."""

    async def seek(self, index: int) -> ReplayState:
        """Seek to a source-specific packet index, when supported."""

    async def set_speed(self, speed: float) -> ReplayState:
        """Set a source-specific replay speed multiplier, when supported."""

    async def set_stream_interval(self, seconds: float | None) -> ReplayState:
        """Set output cadence or clear throttling for source-driven timing."""

    async def set_loop(self, loop: bool) -> ReplayState:
        """Set whether replay loops after the final sample, when supported."""

    def trace(self) -> list[TelemetryTracePoint]:
        """Return all GPS samples needed to preload the full race trace."""


class VBOTelemetrySource:
    """Replay parsed VBO packets through the shared telemetry broadcaster."""

    def __init__(
        self,
        vbos: list[ParsedVBO],
        broadcaster: Broadcaster,
        *,
        replay_speed: float = 1.0,
        stream_interval: float | None = None,
        loop: bool = False,
    ) -> None:
        self.vbos = vbos
        self.broadcaster = broadcaster
        self.vbo_file = ", ".join(Path(v.file_path).name for v in vbos)
        self.total_samples = sum(len(v.data_lines) for v in vbos)
        self.replay_speed = max(replay_speed, 0.01)
        if stream_interval is not None and stream_interval <= 0:
            raise ValueError("stream interval must be greater than zero")
        self.stream_interval = stream_interval
        self.loop = loop
        self.status = "idle"
        self.current_index = 0
        self.simulation_time: float | None = None
        self.latest_packet: TelemetryPacket | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._timing_changed = asyncio.Event()

    def state(self) -> ReplayState:
        return ReplayState(
            status=self.status,
            source="vbo",
            current_index=self.current_index,
            total_samples=self.total_samples,
            replay_speed=self.replay_speed,
            stream_interval=self.stream_interval,
            loop=self.loop,
            vbo_file=self.vbo_file,
            source_file=self.vbo_file,
        )

    def _get_packet(self, index: int) -> TelemetryPacket | None:
        for vbo in self.vbos:
            if index < len(vbo.data_lines):
                packet = parse_vbo_line(index + vbo.sequence_offset, vbo.data_lines[index], vbo.columns)
                if packet:
                    packet.timestamp += vbo.time_offset
                return packet
            index -= len(vbo.data_lines)
        return None

    def trace(self) -> list[TelemetryTracePoint]:
        """Iterate all lines on the fly to build the map trace without memory bloat."""
        trace_points = []
        for i in range(self.total_samples):
            packet = self._get_packet(i)
            if packet and packet.latitude is not None and packet.longitude is not None:
                trace_points.append(
                    TelemetryTracePoint(
                        sequence=packet.sequence,
                        timestamp=packet.timestamp,
                        latitude=packet.latitude,
                        longitude=packet.longitude,
                        heading=packet.heading,
                        speed=packet.speed,
                        altitude=packet.altitude,
                        satellites=packet.satellites,
                        throttle=packet.throttle,
                        brake=packet.brake,
                        steering=packet.steering,
                        gear=packet.gear,
                        lap=packet.lap,
                    )
                )
        return trace_points

    async def play(self) -> ReplayState:
        async with self._lock:
            if self.status == "finished" and self.current_index >= self.total_samples:
                self.current_index = 0
            self.status = "playing"
            self._timing_changed.set()
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run(), name="apexai-vbo-source")
        logger.info("vbo replay started")
        return self.state()

    async def pause(self) -> ReplayState:
        async with self._lock:
            if self.status == "playing":
                self.status = "paused"
                self._timing_changed.set()
        logger.info("vbo replay paused")
        return self.state()

    async def stop(self) -> ReplayState:
        async with self._lock:
            self.status = "stopped"
            self.current_index = 0
            self.simulation_time = None
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("vbo replay stopped")
        return self.state()

    async def reset(self) -> ReplayState:
        async with self._lock:
            self.status = "idle"
            self.current_index = 0
            self.simulation_time = None
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("vbo replay reset")
        return self.state()

    async def seek(self, index: int) -> ReplayState:
        if index < 0 or index >= self.total_samples:
            raise IndexError(f"seek index {index} is outside sample range 0..{self.total_samples - 1}")
        async with self._lock:
            self.current_index = index
            self.simulation_time = None
            self.latest_packet = self._get_packet(index)
            if self.status == "finished":
                self.status = "paused"
            self._timing_changed.set()
        return self.state()

    async def set_speed(self, speed: float) -> ReplayState:
        if speed <= 0:
            raise ValueError("replay speed must be greater than zero")
        async with self._lock:
            self.replay_speed = speed
            self._timing_changed.set()
        logger.info("vbo replay speed set to %s", speed)
        return self.state()

    async def set_stream_interval(self, seconds: float | None) -> ReplayState:
        if seconds is not None and seconds <= 0:
            raise ValueError("stream interval must be greater than zero")
        async with self._lock:
            self.stream_interval = seconds
            self._timing_changed.set()
        logger.info("vbo stream interval set to %s", seconds)
        return self.state()

    async def set_loop(self, loop: bool) -> ReplayState:
        async with self._lock:
            self.loop = loop
            self._timing_changed.set()
        logger.info("vbo loop set to %s", loop)
        return self.state()

    async def _run(self) -> None:
        while True:
            async with self._lock:
                status = self.status
                index = self.current_index

            if status != "playing":
                await asyncio.sleep(0.05)
                continue

            if index >= self.total_samples:
                async with self._lock:
                    if self.loop:
                        self.current_index = 0
                        self.simulation_time = None
                        continue
                    self.status = "finished"
                logger.info("vbo replay finished")
                continue

            async with self._lock:
                if self.status != "playing" or self.current_index != index:
                    continue
                packet = self._get_packet(index)
                if packet is None:
                    self.current_index = index + 1
                    continue
                
                speed = self.replay_speed
                stream_interval = self.stream_interval
                
                if stream_interval is not None:
                    self.simulation_time = None
                    self.latest_packet = packet
                    await self.broadcaster.publish(packet)
                    self.current_index = index + 1
                    interval = stream_interval / speed
                else:
                    self.simulation_time = None
                    self.latest_packet = packet
                    await self.broadcaster.publish(packet)
                    
                    self.current_index = index + 1
                    next_index = self.current_index
                    
                    next_packet = self._get_packet(next_index)
                    if next_packet:
                        interval = next_packet.timestamp - packet.timestamp
                        if interval <= 0 or interval > 60:
                            interval = 0.1
                    else:
                        interval = 0.1
                    interval = interval / speed

                self._timing_changed.clear()

            try:
                await asyncio.wait_for(self._timing_changed.wait(), timeout=interval)
            except TimeoutError:
                pass


def parse_can_raw_chunk_file(path: str | Path) -> list[ParsedCanRawChunk]:
    """Load a raw CAN hex chunk capture without decoding or transforming chunks."""

    can_path = Path(path)
    if not can_path.exists():
        raise FileNotFoundError(f"CAN raw chunk file does not exist: {can_path}")
    if not can_path.is_file():
        raise FileNotFoundError(f"CAN raw chunk path is not a file: {can_path}")

    chunks: list[ParsedCanRawChunk] = []
    for line in can_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not line.strip():
            continue
        if "," in line:
            timestamp_text, chunk = line.split(",", 1)
            try:
                timestamp = float(timestamp_text)
            except ValueError:
                timestamp = float(len(chunks))
        else:
            timestamp = float(len(chunks))
            chunk = line
        chunks.append(
            ParsedCanRawChunk(
                sequence=len(chunks),
                timestamp=timestamp,
                line=line,
                chunk=chunk,
            )
        )
    return chunks


class CanRawChunkTelemetrySource:
    """Replay captured CAN raw hex chunks as opaque stream packets."""

    def __init__(
        self,
        file_path: str | Path,
        chunks: list[ParsedCanRawChunk],
        broadcaster: Broadcaster,
        *,
        replay_speed: float = 1.0,
        stream_interval: float | None = None,
        loop: bool = False,
    ) -> None:
        self.file_path = str(file_path)
        self.chunks = chunks
        self.broadcaster = broadcaster
        self.total_samples = len(chunks)
        self.replay_speed = max(replay_speed, 0.01)
        if stream_interval is not None and stream_interval <= 0:
            raise ValueError("stream interval must be greater than zero")
        self.stream_interval = stream_interval
        self.loop = loop
        self.status = "idle"
        self.current_index = 0
        self.latest_packet: CanRawChunkPacket | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._timing_changed = asyncio.Event()

    def state(self) -> ReplayState:
        return ReplayState(
            status=self.status,
            source="can",
            current_index=self.current_index,
            total_samples=self.total_samples,
            replay_speed=self.replay_speed,
            stream_interval=self.stream_interval,
            loop=self.loop,
            vbo_file="",
            source_file=self.file_path,
        )

    def _get_packet(self, index: int) -> CanRawChunkPacket | None:
        if index < 0 or index >= self.total_samples:
            return None
        chunk = self.chunks[index]
        return CanRawChunkPacket(
            sequence=chunk.sequence,
            timestamp=chunk.timestamp,
            line=chunk.line,
            chunk=chunk.chunk,
        )

    def trace(self) -> list[TelemetryTracePoint]:
        return []

    async def play(self) -> ReplayState:
        async with self._lock:
            if self.status == "finished" and self.current_index >= self.total_samples:
                self.current_index = 0
            self.status = "playing"
            self._timing_changed.set()
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run(), name="apexai-can-raw-source")
        logger.info("CAN raw chunk replay started")
        return self.state()

    async def pause(self) -> ReplayState:
        async with self._lock:
            if self.status == "playing":
                self.status = "paused"
                self._timing_changed.set()
        logger.info("CAN raw chunk replay paused")
        return self.state()

    async def stop(self) -> ReplayState:
        async with self._lock:
            self.status = "stopped"
            self.current_index = 0
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("CAN raw chunk replay stopped")
        return self.state()

    async def reset(self) -> ReplayState:
        async with self._lock:
            self.status = "idle"
            self.current_index = 0
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("CAN raw chunk replay reset")
        return self.state()

    async def seek(self, index: int) -> ReplayState:
        if index < 0 or index >= self.total_samples:
            raise IndexError(f"seek index {index} is outside sample range 0..{self.total_samples - 1}")
        async with self._lock:
            self.current_index = index
            self.latest_packet = self._get_packet(index)
            if self.status == "finished":
                self.status = "paused"
            self._timing_changed.set()
        return self.state()

    async def set_speed(self, speed: float) -> ReplayState:
        if speed <= 0:
            raise ValueError("replay speed must be greater than zero")
        async with self._lock:
            self.replay_speed = speed
            self._timing_changed.set()
        logger.info("CAN raw chunk replay speed set to %s", speed)
        return self.state()

    async def set_stream_interval(self, seconds: float | None) -> ReplayState:
        if seconds is not None and seconds <= 0:
            raise ValueError("stream interval must be greater than zero")
        async with self._lock:
            self.stream_interval = seconds
            self._timing_changed.set()
        logger.info("CAN raw chunk stream interval set to %s", seconds)
        return self.state()

    async def set_loop(self, loop: bool) -> ReplayState:
        async with self._lock:
            self.loop = loop
            self._timing_changed.set()
        logger.info("CAN raw chunk loop set to %s", loop)
        return self.state()

    async def _run(self) -> None:
        while True:
            async with self._lock:
                status = self.status
                index = self.current_index

            if status != "playing":
                await asyncio.sleep(0.05)
                continue

            if index >= self.total_samples:
                async with self._lock:
                    if self.loop:
                        self.current_index = 0
                        continue
                    self.status = "finished"
                logger.info("CAN raw chunk replay finished")
                continue

            async with self._lock:
                if self.status != "playing" or self.current_index != index:
                    continue
                packet = self._get_packet(index)
                if packet is None:
                    self.current_index = index + 1
                    continue
                self.latest_packet = packet
                await self.broadcaster.publish(packet)

                self.current_index = index + 1
                next_index = self.current_index
                speed = self.replay_speed
                stream_interval = self.stream_interval
                self._timing_changed.clear()

            if next_index >= self.total_samples:
                await asyncio.sleep(0)
                continue

            if stream_interval is not None:
                interval = stream_interval / speed
            else:
                next_chunk = self.chunks[next_index]
                interval = (next_chunk.timestamp - packet.timestamp) / 1000.0
                if interval <= 0 or interval > 60:
                    interval = 0.01
                interval = interval / speed

            try:
                await asyncio.wait_for(self._timing_changed.wait(), timeout=interval)
            except TimeoutError:
                pass


def decode_can_raw_frame_file_to_csv(path: str | Path, output_csv: str | Path | None = None) -> tuple[list[ParsedCanDecodedRow], Path]:
    """Decode a raw SLCAN frame log into CSV rows using ``apexai.scripts.decode_can`` helpers."""

    if CANableTelemetryDecoder is None or parse_slcan_line is None or csv_safe_row is None:
        raise RuntimeError("apexai.scripts.decode_can is required for --decoded CAN frame streaming")

    frame_path = Path(path)
    if not frame_path.exists():
        raise FileNotFoundError(f"CAN raw frame file does not exist: {frame_path}")
    if not frame_path.is_file():
        raise FileNotFoundError(f"CAN raw frame path is not a file: {frame_path}")

    csv_path = Path(output_csv) if output_csv is not None else frame_path.with_name(f"{frame_path.stem}_decoded.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    decoder = CANableTelemetryDecoder()
    fieldnames = list(decoder.state.keys())
    rows: list[ParsedCanDecodedRow] = []

    with frame_path.open("r", encoding="utf-8", errors="replace") as input_file:
        with csv_path.open("w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=fieldnames)
            writer.writeheader()

            for line in input_file:
                parsed = parse_slcan_line(line)
                if not parsed:
                    continue

                timestamp_ms, can_id, data_bytes = parsed
                decoded_state = decoder.decode_frame(can_id, data_bytes)
                if decoded_state is None:
                    continue
                if timestamp_ms is not None:
                    decoded_state["timestamp"] = timestamp_ms / 1000.0

                csv_row = csv_safe_row(decoded_state)
                writer.writerow(csv_row)
                values = dict(decoded_state)
                rows.append(
                    ParsedCanDecodedRow(
                        sequence=int(values["sequence"]),
                        timestamp=float(values["timestamp"]),
                        values=values,
                    )
                )

    return rows, csv_path


class CanDecodedTelemetrySource:
    """Replay decoded CAN frame states as readable telemetry packets."""

    def __init__(
        self,
        file_path: str | Path,
        rows: list[ParsedCanDecodedRow],
        decoded_csv: str | Path,
        broadcaster: Broadcaster,
        *,
        replay_speed: float = 1.0,
        stream_interval: float | None = None,
        loop: bool = False,
    ) -> None:
        self.file_path = str(file_path)
        self.decoded_csv = str(decoded_csv)
        self.rows = rows
        self.broadcaster = broadcaster
        self.total_samples = len(rows)
        self.replay_speed = max(replay_speed, 0.01)
        if stream_interval is not None and stream_interval <= 0:
            raise ValueError("stream interval must be greater than zero")
        self.stream_interval = stream_interval
        self.loop = loop
        self.status = "idle"
        self.current_index = 0
        self.latest_packet: CanDecodedPacket | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._timing_changed = asyncio.Event()

    def state(self) -> ReplayState:
        return ReplayState(
            status=self.status,
            source="can",
            current_index=self.current_index,
            total_samples=self.total_samples,
            replay_speed=self.replay_speed,
            stream_interval=self.stream_interval,
            loop=self.loop,
            vbo_file="",
            source_file=self.file_path,
        )

    def _get_packet(self, index: int) -> CanDecodedPacket | None:
        if index < 0 or index >= self.total_samples:
            return None
        row = self.rows[index]
        values = dict(row.values)
        values["source"] = "can"
        values["raw"] = dict(row.values)
        return CanDecodedPacket(**values)

    def trace(self) -> list[TelemetryTracePoint]:
        trace_points = []
        for row in self.rows:
            latitude = row.values.get("latitude")
            longitude = row.values.get("longitude")
            if latitude is None or longitude is None:
                continue
            trace_points.append(
                TelemetryTracePoint(
                    sequence=row.sequence,
                    timestamp=row.timestamp,
                    latitude=float(latitude),
                    longitude=float(longitude),
                    heading=_optional_float(row.values.get("heading")),
                    speed=_optional_float(row.values.get("speed")),
                    altitude=_optional_float(row.values.get("altitude")),
                    satellites=_optional_int(row.values.get("satellites")),
                    throttle=_optional_float(row.values.get("throttle")),
                    brake=_optional_float(row.values.get("brake")),
                    steering=_optional_float(row.values.get("steering")),
                    gear=_optional_int(row.values.get("gear")),
                    lap=_optional_int(row.values.get("lap")),
                )
            )
        return trace_points

    async def play(self) -> ReplayState:
        async with self._lock:
            if self.status == "finished" and self.current_index >= self.total_samples:
                self.current_index = 0
            self.status = "playing"
            self._timing_changed.set()
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run(), name="apexai-can-decoded-source")
        logger.info("CAN decoded replay started")
        return self.state()

    async def pause(self) -> ReplayState:
        async with self._lock:
            if self.status == "playing":
                self.status = "paused"
                self._timing_changed.set()
        logger.info("CAN decoded replay paused")
        return self.state()

    async def stop(self) -> ReplayState:
        async with self._lock:
            self.status = "stopped"
            self.current_index = 0
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("CAN decoded replay stopped")
        return self.state()

    async def reset(self) -> ReplayState:
        async with self._lock:
            self.status = "idle"
            self.current_index = 0
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("CAN decoded replay reset")
        return self.state()

    async def seek(self, index: int) -> ReplayState:
        if index < 0 or index >= self.total_samples:
            raise IndexError(f"seek index {index} is outside sample range 0..{self.total_samples - 1}")
        async with self._lock:
            self.current_index = index
            self.latest_packet = self._get_packet(index)
            if self.status == "finished":
                self.status = "paused"
            self._timing_changed.set()
        return self.state()

    async def set_speed(self, speed: float) -> ReplayState:
        if speed <= 0:
            raise ValueError("replay speed must be greater than zero")
        async with self._lock:
            self.replay_speed = speed
            self._timing_changed.set()
        logger.info("CAN decoded replay speed set to %s", speed)
        return self.state()

    async def set_stream_interval(self, seconds: float | None) -> ReplayState:
        if seconds is not None and seconds <= 0:
            raise ValueError("stream interval must be greater than zero")
        async with self._lock:
            self.stream_interval = seconds
            self._timing_changed.set()
        logger.info("CAN decoded stream interval set to %s", seconds)
        return self.state()

    async def set_loop(self, loop: bool) -> ReplayState:
        async with self._lock:
            self.loop = loop
            self._timing_changed.set()
        logger.info("CAN decoded loop set to %s", loop)
        return self.state()

    async def _run(self) -> None:
        while True:
            async with self._lock:
                status = self.status
                index = self.current_index

            if status != "playing":
                await asyncio.sleep(0.05)
                continue

            if index >= self.total_samples:
                async with self._lock:
                    if self.loop:
                        self.current_index = 0
                        continue
                    self.status = "finished"
                logger.info("CAN decoded replay finished")
                continue

            async with self._lock:
                if self.status != "playing" or self.current_index != index:
                    continue
                packet = self._get_packet(index)
                if packet is None:
                    self.current_index = index + 1
                    continue
                self.latest_packet = packet
                await self.broadcaster.publish(packet)

                self.current_index = index + 1
                next_index = self.current_index
                speed = self.replay_speed
                stream_interval = self.stream_interval
                self._timing_changed.clear()

            if next_index >= self.total_samples:
                await asyncio.sleep(0)
                continue

            if stream_interval is not None:
                interval = stream_interval / speed
            else:
                interval = self.rows[next_index].timestamp - packet.timestamp
                if interval <= 0 or interval > 60:
                    interval = 0.01
                interval = interval / speed

            try:
                await asyncio.wait_for(self._timing_changed.wait(), timeout=interval)
            except TimeoutError:
                pass


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    number = _optional_float(value)
    return None if number is None else int(number)
