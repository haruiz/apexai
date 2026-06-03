"""Configuration objects for the ApexAI replay server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration created from command-line arguments.

    Attributes:
        input_file: Optional single telemetry file. Supported suffixes are
            Racelogic VBOX ``.vbo`` and CAN raw hex chunk ``.txt`` captures.
        decoded: Whether a CAN frame input should be decoded before streaming.
        data_dir: Path to the directory containing Racelogic VBOX ``.vbo`` files to replay.
        host: Network interface uvicorn should bind to.
        port: TCP port uvicorn should listen on.
        replay_speed: Multiplier applied to original telemetry sample intervals.
        stream_interval: Fixed seconds between streamed packets, when set.
        loop: Whether replay should restart after the final telemetry sample.
        autostart: Whether replay should begin during FastAPI startup.
    """

    input_file: Path | None = None
    decoded: bool = False
    data_dir: Path = Path("data")
    host: str = "0.0.0.0"
    port: int = 8000
    replay_speed: float = 1.0
    stream_interval: float | None = None
    loop: bool = True
    autostart: bool = False
