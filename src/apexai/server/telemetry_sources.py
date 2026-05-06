"""Async telemetry source implementations for VBO replay and live CAN input."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .broadcaster import Broadcaster
from .schemas import ReplayState, TelemetryPacket, TelemetryTracePoint
from .vbo_parser import parse_vbo_line

logger = logging.getLogger(__name__)


@dataclass
class ParsedVBO:
    file_path: str
    columns: list[str]
    data_lines: list[str]
    first_timestamp: float | None
    last_timestamp: float | None
    sequence_offset: int
    time_offset: float


class TelemetrySource(Protocol):
    """Control surface shared by telemetry producers used by the API."""

    total_samples: int
    latest_packet: TelemetryPacket | None

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

    def _interpolate_packet(self, p1: TelemetryPacket, p2: TelemetryPacket, timestamp: float) -> TelemetryPacket:
        if p2.timestamp == p1.timestamp:
            return p1.model_copy(deep=True)
            
        ratio = (timestamp - p1.timestamp) / (p2.timestamp - p1.timestamp)
        
        def interp(v1: float | None, v2: float | None) -> float | None:
            if v1 is None or v2 is None:
                return v1 if v1 is not None else v2
            return v1 + ratio * (v2 - v1)
            
        packet = p1.model_copy(deep=True)
        packet.timestamp = timestamp
        packet.latitude = interp(p1.latitude, p2.latitude)
        packet.longitude = interp(p1.longitude, p2.longitude)
        packet.speed = interp(p1.speed, p2.speed)
        
        if p1.heading is not None and p2.heading is not None:
            diff = p2.heading - p1.heading
            if diff > 180:
                diff -= 360
            elif diff < -180:
                diff += 360
            packet.heading = (p1.heading + ratio * diff) % 360
        else:
            packet.heading = p1.heading if p1.heading is not None else p2.heading
            
        packet.altitude = interp(p1.altitude, p2.altitude)
        packet.throttle = interp(p1.throttle, p2.throttle)
        packet.brake = interp(p1.brake, p2.brake)
        packet.steering = interp(p1.steering, p2.steering)
        
        return packet

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
                    if self.simulation_time is None:
                        self.simulation_time = packet.timestamp
                        
                    while self.current_index < self.total_samples:
                        p1 = self._get_packet(self.current_index)
                        p2 = self._get_packet(self.current_index + 1)
                        if p1 is None:
                            break
                        if p2 is None:
                            if self.simulation_time > p1.timestamp:
                                self.current_index += 1
                            break
                        if self.simulation_time <= p2.timestamp:
                            break
                        self.current_index += 1
                        
                    index = self.current_index
                    if index >= self.total_samples:
                        self._timing_changed.clear()
                        continue
                        
                    p1 = self._get_packet(index)
                    p2 = self._get_packet(index + 1)
                    
                    if p1 and p2 and p1.timestamp <= self.simulation_time <= p2.timestamp:
                        pub_packet = self._interpolate_packet(p1, p2, self.simulation_time)
                    else:
                        pub_packet = p1 or packet
                        
                    self.latest_packet = pub_packet
                    await self.broadcaster.publish(pub_packet)
                    
                    self.simulation_time += stream_interval * speed
                    interval = stream_interval
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


