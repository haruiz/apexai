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


class CanRawChunkPacket(BaseModel):
    """Opaque CAN raw hex chunk streamed from a captured chunk file.

    The server does not decode, split, or otherwise transform CAN chunk data.
    ``line`` preserves the complete source line without its trailing newline,
    while ``chunk`` preserves the raw hex chunk text after the timestamp comma.
    """

    source: Literal["can"] = Field(default="can", description="Active telemetry source kind.")
    sequence: int = Field(description="Zero-based chunk order from the source file.")
    timestamp: float = Field(description="Capture timestamp in milliseconds when present, otherwise sequence.")
    line: str = Field(description="Complete source line without its trailing newline.")
    chunk: str = Field(description="Raw hex chunk text exactly as captured after the timestamp comma.")


class CanDecodedPacket(BaseModel):
    """Decoded CAN telemetry state streamed from a raw SLCAN frame file."""

    source: Literal["can"] = Field(default="can", description="Active telemetry source kind.")
    sequence: int = Field(description="Decoded packet sequence.")
    timestamp: float = Field(description="Frame timestamp in seconds.")
    latitude: float | None = None
    longitude: float | None = None
    speed: float | None = None
    heading: float | None = None
    altitude: float | None = None
    satellites: int | None = None
    throttle: float | None = None
    brake: float | None = None
    steering: float | None = None
    gear: int | None = None
    lap: int | None = None
    rpm: float | None = None
    waterTempF: float | None = None
    waterPressurePsi: float | None = None
    rollRateDps: float | None = None
    oilFilterTempF: float | None = None
    oilPressurePsi: float | None = None
    analogOilTempF: float | None = None
    fuelPressurePsi: float | None = None
    ecuMilOut: int | None = None
    brakePressurePsi: float | None = None
    ecuDbwApp1Percent: float | None = None
    pedalPositionPercent: float | None = None
    brakeSwitchApplied: bool | None = None
    pitchRateDps: float | None = None
    yawRateDps: float | None = None
    lateralAccelG: float | None = None
    inlineAccelG: float | None = None
    fuelLevelGallons: float | None = None
    batteryVoltage: float | None = None
    verticalAccelG: float | None = None
    wheelSpeedFlMph: float | None = None
    wheelSpeedFrMph: float | None = None
    wheelSpeedRlMph: float | None = None
    wheelSpeedRrMph: float | None = None
    ecuSpeedMph: float | None = None
    outsideTempF: float | None = None
    engineOilTempF: float | None = None
    dscIntervening: bool | None = None
    shockPots: Any = None
    tireSlipVectors: Any = None
    wheelSpeedDeltas: list[float] | None = None
    raw: dict[str, Any] = Field(default_factory=dict, description="Full decoded CSV row/state.")


TelemetryStreamPacket = TelemetryPacket | CanRawChunkPacket | CanDecodedPacket


class TelemetryTracePoint(BaseModel):
    """GPS sample used by the frontend to preload and color the full race trace."""

    sequence: int = Field(description="Zero-based packet order after timestamp sorting.")
    timestamp: float = Field(description="Sample timestamp in seconds.")
    latitude: float = Field(description="Latitude in decimal degrees.")
    longitude: float = Field(description="Longitude in decimal degrees.")
    heading: float | None = Field(default=None, description="Vehicle heading in degrees.")
    speed: float | None = Field(default=None, description="Vehicle speed.")
    altitude: float | None = Field(default=None, description="Vehicle altitude or height.")
    satellites: int | None = Field(default=None, description="Number of GPS satellites.")
    throttle: float | None = Field(default=None, description="Throttle input value.")
    brake: float | None = Field(default=None, description="Brake input value.")
    steering: float | None = Field(default=None, description="Steering input value.")
    gear: int | None = Field(default=None, description="Current gear.")
    lap: int | None = Field(default=None, description="Current lap number.")


class ReplayState(BaseModel):
    """Current state of the replay engine.

    Attributes:
        status: Replay lifecycle state.
        source: Active telemetry source kind.
        current_index: Index of the next sample or CAN raw chunk to publish.
        total_samples: Total number of parsed telemetry samples.
        replay_speed: Multiplier applied to original telemetry sample intervals.
        stream_interval: Fixed seconds between streamed packets, when set.
        loop: Whether replay loops after the final sample.
        vbo_file: Source VBO file path. Empty for non-VBO sources.
        source_file: Source file path, such as the VBO or CAN raw chunk file.
        can_interface: Legacy field retained for older clients; unused for raw chunk replay.
        can_channel: Legacy field retained for older clients; unused for raw chunk replay.
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
    can_interface: str | None = Field(default=None, description="Legacy CAN interface field; unused for raw chunk replay.")
    can_channel: str | None = Field(default=None, description="Legacy CAN channel field; unused for raw chunk replay.")


class SpeedUpdate(BaseModel):
    """Request body for changing replay speed.

    Attributes:
        speed: Positive replay speed multiplier.
    """

    speed: float = Field(description="Positive replay speed multiplier.")


class LoopUpdate(BaseModel):
    """Request body for changing the replay loop mode.

    Attributes:
        loop: Whether replay loops after the final sample.
    """

    loop: bool = Field(description="Whether replay loops after the final sample.")


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
