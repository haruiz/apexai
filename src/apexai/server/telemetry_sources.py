"""Async telemetry source implementations for VBO replay and live CAN input.

The server has one set of output transports: HTTP control routes, Server-Sent
Events, and WebSocket. Those transports should not need to know whether packets
came from a recorded VBO file or a live CAN bus. This module provides that
separation by defining a shared ``TelemetrySource`` control surface plus two
concrete producers:

* ``VBOTelemetrySource`` replays already parsed ``TelemetryPacket`` rows with
  either source timestamps or a configured fixed interval.
* ``CANTelemetrySource`` reads raw CAN frames through ``python-can``, decodes
  them with a DBC file through ``cantools``, normalizes common signal names into
  ``TelemetryPacket``, and publishes packets as they arrive.

Both classes publish to ``Broadcaster``. The broadcaster then fans packets out
to every SSE or WebSocket client.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Any, Protocol

from .broadcaster import Broadcaster
from .schemas import ReplayState, TelemetryPacket

logger = logging.getLogger(__name__)


class TelemetrySource(Protocol):
    """Control surface shared by telemetry producers used by the API.

    FastAPI routes call this protocol instead of calling a concrete VBO or CAN
    class. That keeps route handlers stable while allowing the command line to
    choose a telemetry source at startup.

    ``samples`` is populated for recorded sources like VBO and remains empty for
    live sources like CAN. ``latest_packet`` always tracks the most recent packet
    published by the active source.
    """

    samples: list[TelemetryPacket]
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


class VBOTelemetrySource:
    """Replay parsed VBO packets through the shared telemetry broadcaster.

    VBO is an offline recording format. The parser has already converted each
    row into a normalized ``TelemetryPacket`` before this class is constructed.
    This source is responsible only for replay control: current index, timing,
    looping, speed changes, seeking, and publishing packets in order.
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
        """Initialize a VBO replay source.

        Args:
            samples: Timestamp-sorted packets parsed from a VBO file.
            broadcaster: Fan-out publisher used by SSE and WebSocket endpoints.
            vbo_file: Original VBO path, stored for state and diagnostics.
            replay_speed: Multiplier applied to source timestamp intervals.
            stream_interval: Fixed seconds between packets. When ``None``, the
                source uses intervals from the VBO timestamps.
            loop: Whether replay should restart after the final packet.

        Raises:
            ValueError: If ``stream_interval`` is not positive.
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
        """Return the current VBO replay state.

        The returned object is used by ``GET /state`` and by replay control
        responses. ``current_index`` is the next VBO sample that will be
        published, not the last one already sent.
        """

        return ReplayState(
            status=self.status,
            source="vbo",
            current_index=self.current_index,
            total_samples=len(self.samples),
            replay_speed=self.replay_speed,
            stream_interval=self.stream_interval,
            loop=self.loop,
            vbo_file=self.vbo_file,
            source_file=self.vbo_file,
        )

    async def play(self) -> ReplayState:
        """Start or resume replay.

        If replay had finished at the end of the file, this moves the index back
        to the first sample. The background task is created lazily and reused for
        later pause/resume cycles.
        """

        async with self._lock:
            if self.status == "finished" and self.current_index >= len(self.samples):
                self.current_index = 0
            self.status = "playing"
            self._timing_changed.set()
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run(), name="apexai-vbo-source")
        logger.info("vbo replay started")
        return self.state()

    async def pause(self) -> ReplayState:
        """Pause replay without changing the current sample index.

        The timing event wakes the background task if it is sleeping between
        packets, so pause takes effect promptly.
        """

        async with self._lock:
            if self.status == "playing":
                self.status = "paused"
                self._timing_changed.set()
        logger.info("vbo replay paused")
        return self.state()

    async def stop(self) -> ReplayState:
        """Stop replay and reset it to the beginning.

        This also clears ``latest_packet`` so ``/telemetry/latest`` reflects
        that replay is no longer holding a current sample.
        """

        async with self._lock:
            self.status = "stopped"
            self.current_index = 0
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("vbo replay stopped")
        return self.state()

    async def reset(self) -> ReplayState:
        """Reset replay position without forcing playback to start."""

        async with self._lock:
            self.status = "idle"
            self.current_index = 0
            self.latest_packet = None
            self._timing_changed.set()
        logger.info("vbo replay reset")
        return self.state()

    async def seek(self, index: int) -> ReplayState:
        """Move replay to a specific telemetry sample index.

        Seeking is only meaningful for recorded sources. The selected packet is
        also stored as ``latest_packet`` so the HTTP latest endpoint immediately
        reflects the new position.
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

        The multiplier only applies when ``stream_interval`` is ``None``. Fixed
        stream intervals are already explicit wall-clock delays, so they are not
        divided by replay speed.
        """

        if speed <= 0:
            raise ValueError("replay speed must be greater than zero")
        async with self._lock:
            self.replay_speed = speed
            self._timing_changed.set()
        logger.info("vbo replay speed set to %s", speed)
        return self.state()

    async def set_stream_interval(self, seconds: float | None) -> ReplayState:
        """Set or clear the fixed interval between streamed packets.

        Passing ``None`` restores source timestamp timing from the VBO file.
        Passing a positive value forces an exact output cadence, which is useful
        for testing phone or UI behavior at a known frequency.
        """

        if seconds is not None and seconds <= 0:
            raise ValueError("stream interval must be greater than zero")
        async with self._lock:
            self.stream_interval = seconds
            self._timing_changed.set()
        logger.info("vbo stream interval set to %s", seconds)
        return self.state()

    async def _run(self) -> None:
        """Publish telemetry packets until paused, stopped, or finished.

        This task intentionally stays alive while paused or stopped. Keeping the
        task alive avoids repeatedly allocating tasks and makes resume fast. All
        shared mutable state is read or changed under ``_lock`` so API calls and
        packet publication cannot race the current index.
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
                logger.info("vbo replay finished")
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


class CANTelemetrySource:
    """Read live CAN frames, decode them with a DBC, and publish telemetry.

    CAN is a live protocol, not a recorded table. A CAN adapter can be attached
    through SocketCAN, virtual CAN, a serial USB-C adapter using ``slcan``, or
    another ``python-can`` backend. Each frame is decoded with the configured DBC
    file, then common signal names are mapped into the normalized telemetry
    fields used by the UI and Android client.

    Unknown or vehicle-specific decoded signals are not discarded. They are
    preserved in ``TelemetryPacket.raw`` so downstream clients can still inspect
    them before the normalization map is tuned for a specific car or sensor box.
    """

    DEFAULT_SIGNAL_MAP: dict[str, tuple[str, ...]] = {
        "latitude": ("Latitude", "latitude", "GPSLatitude"),
        "longitude": ("Longitude", "longitude", "GPSLongitude"),
        "speed": ("VehicleSpeed", "Speed", "speed", "WheelBasedVehicleSpeed"),
        "heading": ("Heading", "heading", "GPSHeading"),
        "altitude": ("Altitude", "altitude", "GPSAltitude"),
        "satellites": ("Satellites", "satellites", "GPSSatellites"),
        "throttle": ("Throttle", "throttle", "AcceleratorPedalPosition"),
        "brake": ("Brake", "brake", "BrakePressure", "BrakePedal"),
        "steering": ("Steering", "steering", "SteeringAngle"),
        "gear": ("Gear", "gear", "CurrentGear"),
        "lap": ("Lap", "lap"),
    }

    def __init__(
        self,
        broadcaster: Broadcaster,
        *,
        dbc_file: str | Path,
        can_channel: str,
        can_interface: str = "socketcan",
        bitrate: int | None = None,
    ) -> None:
        """Initialize a live CAN source.

        Args:
            broadcaster: Fan-out publisher used by SSE and WebSocket endpoints.
            dbc_file: DBC file used by ``cantools`` to decode raw CAN payloads.
            can_channel: Channel understood by ``python-can``. Examples include
                ``can0``, ``vcan0``, ``test``, or ``/dev/ttyUSB0``.
            can_interface: ``python-can`` backend name, such as ``socketcan``,
                ``slcan``, ``virtual``, ``pcan``, or ``vector``.
            bitrate: Optional bus bitrate. Some interfaces require this, while
                SocketCAN devices are often configured by the OS before startup.
        """

        self.broadcaster = broadcaster
        self.dbc_file = str(dbc_file)
        self.can_channel = can_channel
        self.can_interface = can_interface
        self.bitrate = bitrate
        self.samples: list[TelemetryPacket] = []
        self.latest_packet: TelemetryPacket | None = None
        self.status = "idle"
        self.current_index = 0
        self.stream_interval: float | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._database: Any | None = None
        self._bus: Any | None = None

    def state(self) -> ReplayState:
        """Return the current CAN ingest state.

        ``current_index`` counts packets published since startup or reset. CAN
        does not have a finite sample count, so ``total_samples`` is always
        zero.
        """

        return ReplayState(
            status=self.status,
            source="can",
            current_index=self.current_index,
            total_samples=0,
            replay_speed=1.0,
            stream_interval=self.stream_interval,
            loop=False,
            vbo_file="",
            source_file=self.dbc_file,
            can_interface=self.can_interface,
            can_channel=self.can_channel,
        )

    async def play(self) -> ReplayState:
        """Start or resume live CAN ingest.

        The DBC and bus are opened lazily by the background task. This means the
        server can boot and report configuration before touching hardware, and
        failures are isolated to the CAN source task.
        """

        async with self._lock:
            self.status = "playing"
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run(), name="apexai-can-source")
        logger.info("can ingest started")
        return self.state()

    async def pause(self) -> ReplayState:
        """Pause live CAN publishing while keeping the bus task alive.

        Frames are not buffered while paused; the source simply stops reading and
        publishing until playback resumes.
        """

        async with self._lock:
            if self.status == "playing":
                self.status = "paused"
        logger.info("can ingest paused")
        return self.state()

    async def stop(self) -> ReplayState:
        """Stop live CAN ingest and close the bus.

        The background task is cancelled and the hardware/virtual bus is shut
        down so USB or SocketCAN resources are released cleanly.
        """

        async with self._lock:
            self.status = "stopped"
            self.latest_packet = None
            self.current_index = 0
            task = self._task
            self._task = None

        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        await self._shutdown_bus()
        logger.info("can ingest stopped")
        return self.state()

    async def reset(self) -> ReplayState:
        """Reset counters and latest packet for live CAN ingest."""

        async with self._lock:
            self.current_index = 0
            self.latest_packet = None
            if self.status in {"finished", "stopped"}:
                self.status = "idle"
        logger.info("can ingest reset")
        return self.state()

    async def seek(self, index: int) -> ReplayState:
        """Reject seek requests because live CAN streams are not indexed."""

        raise IndexError("seek is not supported for live CAN streams")

    async def set_speed(self, speed: float) -> ReplayState:
        """Reject replay speed changes because live CAN timing is source-driven.

        CAN data arrives from the vehicle or simulator at its own cadence. Use
        ``set_stream_interval`` to throttle output frequency instead.
        """

        if speed <= 0:
            raise ValueError("replay speed must be greater than zero")
        raise ValueError("replay speed is not supported for live CAN streams")

    async def set_stream_interval(self, seconds: float | None) -> ReplayState:
        """Throttle CAN publication to a fixed interval, or publish every frame.

        ``None`` publishes every decoded CAN frame. A positive value limits
        publication frequency, for example ``0.1`` seconds for roughly 10 Hz.
        """

        if seconds is not None and seconds <= 0:
            raise ValueError("stream interval must be greater than zero")
        async with self._lock:
            self.stream_interval = seconds
        logger.info("can stream interval set to %s", seconds)
        return self.state()

    async def _run(self) -> None:
        """Read, decode, normalize, and publish CAN frames.

        ``python-can`` exposes blocking bus reads, so each ``recv`` call runs in
        a worker thread through ``asyncio.to_thread``. That keeps the FastAPI
        event loop responsive for SSE, WebSocket, and HTTP control traffic while
        the source waits for vehicle frames.
        """

        try:
            database = await self._load_database()
            bus = await self._open_bus()
            last_publish = 0.0

            while True:
                async with self._lock:
                    status = self.status
                    stream_interval = self.stream_interval

                if status != "playing":
                    await asyncio.sleep(0.05)
                    continue

                message = await asyncio.to_thread(bus.recv, 1.0)
                if message is None:
                    continue

                try:
                    decoded = database.decode_message(message.arbitration_id, message.data)
                except Exception as exc:
                    logger.debug("dropping undecodable can frame id=%s: %s", message.arbitration_id, exc)
                    continue

                now = time.monotonic()
                if stream_interval is not None and now - last_publish < stream_interval:
                    continue

                packet = self._packet_from_can_message(message, decoded)
                async with self._lock:
                    if self.status != "playing":
                        continue
                    self.latest_packet = packet
                    self.current_index += 1
                    last_publish = now
                await self.broadcaster.publish(packet)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("can ingest stopped after an unrecoverable error")
            async with self._lock:
                self.status = "stopped"
        finally:
            await self._shutdown_bus()

    async def _load_database(self) -> Any:
        """Load the DBC file in a worker thread.

        DBC parsing can touch disk and do non-trivial parsing work, so it is kept
        off the event loop. The result is cached for the lifetime of this source.
        """

        if self._database is not None:
            return self._database

        try:
            import cantools
        except ImportError as exc:
            raise RuntimeError("CAN ingest requires the 'cantools' package") from exc

        self._database = await asyncio.to_thread(cantools.database.load_file, self.dbc_file)
        return self._database

    async def _open_bus(self) -> Any:
        """Open the configured python-can bus in a worker thread.

        Bus construction may open USB devices, sockets, vendor drivers, or
        virtual channels depending on ``can_interface``. Keeping it in a thread
        prevents hardware setup from blocking API startup work.
        """

        if self._bus is not None:
            return self._bus

        try:
            import can
        except ImportError as exc:
            raise RuntimeError("CAN ingest requires the 'python-can' package") from exc

        kwargs: dict[str, Any] = {
            "interface": self.can_interface,
            "channel": self.can_channel,
        }
        if self.bitrate is not None:
            kwargs["bitrate"] = self.bitrate
        self._bus = await asyncio.to_thread(can.interface.Bus, **kwargs)
        return self._bus

    async def _shutdown_bus(self) -> None:
        """Close the CAN bus if it has been opened."""

        bus = self._bus
        self._bus = None
        if bus is not None and hasattr(bus, "shutdown"):
            await asyncio.to_thread(bus.shutdown)

    def _packet_from_can_message(self, message: Any, decoded: dict[str, Any]) -> TelemetryPacket:
        """Normalize one decoded CAN frame into the shared packet schema.

        The normalized fields power common UI and coaching behavior. The raw
        dict keeps the full decoded DBC payload plus frame metadata, which makes
        debugging and vehicle-specific feature work possible without changing
        the stream contract.
        """

        sequence = self.current_index
        raw = {
            **decoded,
            "_can_id": message.arbitration_id,
            "_is_extended_id": message.is_extended_id,
            "_dlc": message.dlc,
            "_data_hex": bytes(message.data).hex(),
        }
        timestamp = float(message.timestamp) if message.timestamp is not None else time.time()
        return TelemetryPacket(
            sequence=sequence,
            timestamp=timestamp,
            latitude=self._first_numeric(decoded, "latitude"),
            longitude=self._first_numeric(decoded, "longitude"),
            speed=self._first_numeric(decoded, "speed"),
            heading=self._first_numeric(decoded, "heading"),
            altitude=self._first_numeric(decoded, "altitude"),
            satellites=self._first_int(decoded, "satellites"),
            throttle=self._first_numeric(decoded, "throttle"),
            brake=self._first_numeric(decoded, "brake"),
            steering=self._first_numeric(decoded, "steering"),
            gear=self._first_int(decoded, "gear"),
            lap=self._first_int(decoded, "lap"),
            raw=raw,
        )

    def _first_numeric(self, decoded: dict[str, Any], field: str) -> float | None:
        """Return the first numeric decoded value matching a normalized field."""

        value = self._first_value(decoded, field)
        if isinstance(value, bool) or value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _first_int(self, decoded: dict[str, Any], field: str) -> int | None:
        """Return the first integer decoded value matching a normalized field."""

        value = self._first_numeric(decoded, field)
        return None if value is None else int(value)

    def _first_value(self, decoded: dict[str, Any], field: str) -> Any | None:
        """Return the first decoded signal value matching a normalized field.

        Different DBC files use different signal names for the same concept.
        ``DEFAULT_SIGNAL_MAP`` captures common aliases so one server packet shape
        can serve multiple vehicles and sensor boxes.
        """

        for signal_name in self.DEFAULT_SIGNAL_MAP[field]:
            if signal_name in decoded:
                return decoded[signal_name]
        return None
