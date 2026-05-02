"""Pydantic request and response schemas for the replay API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ReplayStatus = Literal["idle", "playing", "paused", "stopped", "finished"]
TelemetrySourceKind = Literal["vbo", "can"]


class TelemetryPacket(BaseModel):
    """Normalized telemetry sample streamed to clients.

    Attributes:
        sequence: Zero-based packet order after timestamp sorting.
        timestamp: Sample timestamp in seconds.
        latitude: Latitude in decimal degrees, if present in the VBO data.
        longitude: Longitude in decimal degrees, if present in the VBO data.
        speed: Vehicle speed from the VBO velocity/speed column.
        heading: Vehicle heading in degrees.
        altitude: Vehicle altitude/height.
        satellites: Number of GPS satellites.
        throttle: Throttle input value.
        brake: Brake input value.
        steering: Steering input value.
        gear: Current gear.
        lap: Current lap number.
        raw: Original parsed VBO row after primitive value coercion.
    """

    sequence: int = Field(description="Zero-based packet order after timestamp sorting.")
    timestamp: float = Field(description="Sample timestamp in seconds.")
    latitude: float | None = Field(default=None, description="Latitude in decimal degrees.")
    longitude: float | None = Field(default=None, description="Longitude in decimal degrees.")
    speed: float | None = Field(default=None, description="Vehicle speed.")
    heading: float | None = Field(default=None, description="Vehicle heading in degrees.")
    altitude: float | None = Field(default=None, description="Vehicle altitude or height.")
    satellites: int | None = Field(default=None, description="Number of GPS satellites.")
    throttle: float | None = Field(default=None, description="Throttle input value.")
    brake: float | None = Field(default=None, description="Brake input value.")
    steering: float | None = Field(default=None, description="Steering input value.")
    gear: int | None = Field(default=None, description="Current gear.")
    lap: int | None = Field(default=None, description="Current lap number.")
    raw: dict[str, Any] = Field(default_factory=dict, description="Original parsed VBO row.")


class TelemetryTracePoint(BaseModel):
    """Minimal GPS sample used by the frontend to preload the full race trace."""

    sequence: int = Field(description="Zero-based packet order after timestamp sorting.")
    timestamp: float = Field(description="Sample timestamp in seconds.")
    latitude: float = Field(description="Latitude in decimal degrees.")
    longitude: float = Field(description="Longitude in decimal degrees.")
    heading: float | None = Field(default=None, description="Vehicle heading in degrees.")


class ReplayState(BaseModel):
    """Current state of the replay engine.

    Attributes:
        status: Replay lifecycle state.
        source: Active telemetry source kind.
        current_index: Index of the next sample to publish, or number of live
            CAN packets published.
        total_samples: Total number of parsed telemetry samples.
        replay_speed: Multiplier applied to original telemetry sample intervals.
        stream_interval: Fixed seconds between streamed packets, when set.
        loop: Whether replay loops after the final sample.
        vbo_file: Source VBO file path. Empty for non-VBO sources.
        source_file: Source file path, such as the VBO or CAN DBC path.
        can_interface: python-can interface name when using CAN.
        can_channel: python-can channel when using CAN.
    """

    status: ReplayStatus = Field(description="Replay lifecycle state.")
    source: TelemetrySourceKind = Field(default="vbo", description="Active telemetry source kind.")
    current_index: int = Field(description="Index of the next sample to publish.")
    total_samples: int = Field(description="Total number of parsed telemetry samples.")
    replay_speed: float = Field(description="Replay speed multiplier.")
    stream_interval: float | None = Field(default=None, description="Fixed seconds between streamed packets.")
    loop: bool = Field(description="Whether replay loops after the final sample.")
    vbo_file: str = Field(description="Source VBO file path.")
    source_file: str | None = Field(default=None, description="Source file path for the active source.")
    can_interface: str | None = Field(default=None, description="python-can interface name when using CAN.")
    can_channel: str | None = Field(default=None, description="python-can channel when using CAN.")


class SpeedUpdate(BaseModel):
    """Request body for changing replay speed.

    Attributes:
        speed: Positive replay speed multiplier.
    """

    speed: float = Field(description="Positive replay speed multiplier.")


class StreamIntervalUpdate(BaseModel):
    """Request body for changing the fixed stream interval.

    Attributes:
        seconds: Positive seconds between packets, or ``null`` to use VBO timestamps.
    """

    seconds: float | None = Field(
        default=None,
        description="Positive seconds between streamed packets, or null to use source timestamps.",
    )


class SeekRequest(BaseModel):
    """Request body for seeking to a telemetry sample.

    Attributes:
        index: Zero-based sample index to seek to.
    """

    index: int = Field(description="Zero-based sample index to seek to.")
