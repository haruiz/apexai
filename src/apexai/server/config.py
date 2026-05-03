"""Configuration objects for the ApexAI replay server."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


TelemetrySourceKind = Literal["vbo", "can"]


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration created from command-line arguments.

    Attributes:
        source: Telemetry source kind.
        vbo_files: Paths to the Racelogic VBOX ``.vbo`` files to replay.
        dbc_file: Path to the CAN DBC used to decode raw frames.
        can_interface: python-can interface name, such as socketcan or slcan.
        can_channel: python-can channel, such as can0 or a USB serial device.
        can_bitrate: Optional CAN bus bitrate.
        host: Network interface uvicorn should bind to.
        port: TCP port uvicorn should listen on.
        replay_speed: Multiplier applied to original telemetry sample intervals.
        stream_interval: Fixed seconds between streamed packets, when set.
        loop: Whether replay should restart after the final telemetry sample.
        autostart: Whether replay should begin during FastAPI startup.
    """

    source: TelemetrySourceKind = "vbo"
    vbo_files: list[Path] = field(default_factory=list)
    dbc_file: Path | None = None
    can_interface: str = "socketcan"
    can_channel: str = "can0"
    can_bitrate: int | None = None
    host: str = "0.0.0.0"
    port: int = 8000
    replay_speed: float = 1.0
    stream_interval: float | None = None
    loop: bool = False
    autostart: bool = False
