"""Configuration objects for the ApexAI replay server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration created from command-line arguments.

    Attributes:
        vbo_file: Path to the Racelogic VBOX ``.vbo`` file to replay.
        host: Network interface uvicorn should bind to.
        port: TCP port uvicorn should listen on.
        replay_speed: Multiplier applied to original telemetry sample intervals.
        stream_interval: Fixed seconds between streamed packets, when set.
        loop: Whether replay should restart after the final telemetry sample.
        autostart: Whether replay should begin during FastAPI startup.
    """

    vbo_file: Path
    host: str = "0.0.0.0"
    port: int = 8000
    replay_speed: float = 1.0
    stream_interval: float | None = None
    loop: bool = False
    autostart: bool = False
