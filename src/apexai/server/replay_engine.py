"""Async replay engine for publishing telemetry in timestamp order."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .broadcaster import Broadcaster
from .schemas import ReplayState, TelemetryPacket

logger = logging.getLogger(__name__)


class ReplayEngine:
    """Async telemetry replay controller.

    The engine publishes packets in timestamp order while preserving the
    original sample intervals, adjusted by the configured replay speed, unless
    a fixed stream interval is configured.
    """

    def __init__(
        self,
        samples: list[TelemetryPacket],
        broadcaster: Broadcaster,
        *,
        vbo_file: str | Path,
        replay_speed: float = 1.0,
        stream_interval: float | None = None,
        loop: bool = False,
    ) -> None:
        """Initialize the replay engine.

        Args:
            samples: Timestamp-sorted telemetry packets to replay.
            broadcaster: Publisher used to send packets to connected clients.
            vbo_file: Source VBO file path for state reporting.
            replay_speed: Positive multiplier for playback timing.
            stream_interval: Fixed seconds between streamed packets, when set.
            loop: Whether replay should restart after the final sample.

        Returns:
            None.
        """

        self.samples = samples
        self.broadcaster = broadcaster
        self.vbo_file = str(vbo_file)
        self.replay_speed = max(replay_speed, 0.01)
        if stream_interval is not None and stream_interval <= 0:
            raise ValueError("stream interval must be greater than zero")
        self.stream_interval = stream_interval
        self.loop = loop
        self.status = "idle"
        self.current_index = 0
        self.latest_packet: TelemetryPacket | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._timing_changed = asyncio.Event()

    def state(self) -> ReplayState:
        """Return the current replay state.

        Returns:
            Snapshot of status, index, timing settings, loop setting, and source file.
        """

        return ReplayState(
            status=self.status,
            current_index=self.current_index,
            total_samples=len(self.samples),
            replay_speed=self.replay_speed,
            stream_interval=self.stream_interval,
            loop=self.loop,
            vbo_file=self.vbo_file,
        )

    async def play(self) -> ReplayState:
        """Start or resume replay.

        Returns:
            Updated replay state after entering the playing state.
        """

        async with self._lock:
            if self.status == "finished" and self.current_index >= len(self.samples):
                self.current_index = 0
            self.status = "playing"
            self._timing_changed.set()
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run(), name="apexai-replay-engine")
        logger.info("replay started")
        return self.state()

    async def pause(self) -> ReplayState:
        """Pause replay without changing the current sample index.

        Returns:
            Updated replay state.
        """

        async with self._lock:
            if self.status == "playing":
                self.status = "paused"
                self._timing_changed.set()
        logger.info("replay paused")
        return self.state()

    async def stop(self) -> ReplayState:
        """Stop replay and reset it to the beginning.

        Returns:
            Updated replay state with the current index reset to zero.
        """

        async with self._lock:
            self.status = "stopped"
            self.current_index = 0
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("replay stopped")
        return self.state()

    async def reset(self) -> ReplayState:
        """Reset replay position without forcing playback to start.

        Returns:
            Updated replay state.
        """

        async with self._lock:
            self.status = "idle"
            self.current_index = 0
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("replay reset")
        return self.state()

    async def seek(self, index: int) -> ReplayState:
        """Move replay to a specific telemetry sample index.

        Args:
            index: Zero-based sample index to seek to.

        Returns:
            Updated replay state.

        Raises:
            IndexError: If ``index`` is outside the parsed sample range.
        """

        if index < 0 or index >= len(self.samples):
            raise IndexError(f"seek index {index} is outside sample range 0..{len(self.samples) - 1}")
        async with self._lock:
            self.current_index = index
            self.latest_packet = self.samples[index]
            if self.status == "finished":
                self.status = "paused"
            self._timing_changed.set()
        return self.state()

    async def set_speed(self, speed: float) -> ReplayState:
        """Set the replay speed multiplier.

        Args:
            speed: Positive multiplier applied to playback intervals.

        Returns:
            Updated replay state.

        Raises:
            ValueError: If ``speed`` is less than or equal to zero.
        """

        if speed <= 0:
            raise ValueError("replay speed must be greater than zero")
        async with self._lock:
            self.replay_speed = speed
            self._timing_changed.set()
        logger.info("replay speed set to %s", speed)
        return self.state()

    async def set_stream_interval(self, seconds: float | None) -> ReplayState:
        """Set or clear the fixed interval between streamed packets.

        Args:
            seconds: Positive seconds between packets, or ``None`` to restore
                source timestamp intervals adjusted by replay speed.

        Returns:
            Updated replay state.

        Raises:
            ValueError: If ``seconds`` is less than or equal to zero.
        """

        if seconds is not None and seconds <= 0:
            raise ValueError("stream interval must be greater than zero")
        async with self._lock:
            self.stream_interval = seconds
            self._timing_changed.set()
        logger.info("stream interval set to %s", seconds)
        return self.state()

    async def _run(self) -> None:
        """Publish telemetry packets until paused, stopped, or finished.

        Returns:
            None.
        """

        while True:
            async with self._lock:
                status = self.status
                index = self.current_index

            if status != "playing":
                await asyncio.sleep(0.05)
                continue

            if index >= len(self.samples):
                async with self._lock:
                    if self.loop:
                        self.current_index = 0
                        continue
                    self.status = "finished"
                logger.info("replay finished")
                continue

            async with self._lock:
                if self.status != "playing" or self.current_index != index:
                    continue
                packet = self.samples[index]
                self.latest_packet = packet
                await self.broadcaster.publish(packet)

            async with self._lock:
                if self.status != "playing" or self.current_index != index:
                    continue
                self.current_index = index + 1
                next_index = self.current_index
                speed = self.replay_speed
                stream_interval = self.stream_interval
                self._timing_changed.clear()

            if next_index >= len(self.samples):
                await asyncio.sleep(0)
                continue

            if stream_interval is None:
                interval = self.samples[next_index].timestamp - packet.timestamp
                if interval <= 0 or interval > 60:
                    interval = 0.1
                interval = interval / speed
            else:
                interval = stream_interval

            try:
                await asyncio.wait_for(self._timing_changed.wait(), timeout=interval)
            except TimeoutError:
                pass
