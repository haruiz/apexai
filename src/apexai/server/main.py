"""CLI bootstrap for the ApexAI telemetry replay server."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from .api import create_app
from .broadcaster import Broadcaster
from .config import ServerConfig
from .replay_engine import ReplayEngine
from .vbo_parser import VBOParseError, parse_vbo_file


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the replay server.

    Returns:
        Configured argument parser for ``python -m apexai.server``.
    """

    parser = argparse.ArgumentParser(description="ApexAI VBO telemetry replay server")
    parser.add_argument("--vbo-file", required=True, help="Path to the Racelogic VBOX .vbo file")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", default=8000, type=int, help="Port to bind")
    parser.add_argument("--replay-speed", default=1.0, type=float, help="Replay speed multiplier")
    parser.add_argument(
        "--stream-interval",
        default=None,
        type=float,
        help="Fixed seconds between streamed packets; defaults to VBO timestamp intervals",
    )
    parser.add_argument("--loop", action="store_true", help="Loop replay after the final sample")
    parser.add_argument("--autostart", action="store_true", help="Start replay when the server starts")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse arguments, load telemetry, and run the FastAPI server.

    Args:
        argv: Optional argument list for tests or embedded usage. When ``None``,
            arguments are read from ``sys.argv``.

    Returns:
        None.

    Raises:
        SystemExit: If the VBO file cannot be parsed or contains no samples.
    """

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    args = build_parser().parse_args(argv)
    if args.stream_interval is not None and args.stream_interval <= 0:
        raise SystemExit("--stream-interval must be greater than zero")
    config = ServerConfig(
        vbo_file=Path(args.vbo_file),
        host=args.host,
        port=args.port,
        replay_speed=args.replay_speed,
        stream_interval=args.stream_interval,
        loop=args.loop,
        autostart=args.autostart,
    )

    try:
        samples, columns, duration = parse_vbo_file(config.vbo_file)
    except (FileNotFoundError, VBOParseError) as exc:
        logging.getLogger(__name__).error("%s", exc)
        raise SystemExit(1) from exc
    except Exception as exc:
        logging.getLogger(__name__).exception("failed to parse VBO file")
        raise SystemExit(1) from exc

    if not samples:
        logging.getLogger(__name__).error("no telemetry samples parsed from %s", config.vbo_file)
        raise SystemExit(1)

    _print_summary(config, len(samples), columns, duration)

    broadcaster = Broadcaster()
    engine = ReplayEngine(
        samples,
        broadcaster,
        vbo_file=config.vbo_file,
        replay_speed=config.replay_speed,
        stream_interval=config.stream_interval,
        loop=config.loop,
    )
    app = create_app(config, engine, broadcaster)
    uvicorn.run(app, host=config.host, port=config.port)


def _print_summary(config: ServerConfig, sample_count: int, columns: list[str], duration: float | None) -> None:
    """Print a concise startup summary.

    Args:
        config: Runtime server configuration.
        sample_count: Number of parsed telemetry samples.
        columns: Original VBO column names.
        duration: Approximate replay duration in seconds.

    Returns:
        None.
    """

    duration_text = "unknown" if duration is None else f"{duration:.3f}s"
    print("ApexAI telemetry replay server")
    print(f"  VBO file: {config.vbo_file}")
    print(f"  Samples: {sample_count}")
    print(f"  Columns: {', '.join(columns)}")
    print(f"  Approx duration: {duration_text}")
    print(f"  Replay speed: {config.replay_speed}x")
    print(f"  Stream interval: {_format_stream_interval(config.stream_interval)}")
    print(f"  Loop: {config.loop}")
    print(f"  Autostart: {config.autostart}")
    sys.stdout.flush()


def _format_stream_interval(stream_interval: float | None) -> str:
    """Format the fixed stream interval for startup output."""

    if stream_interval is None:
        return "source timestamps"
    return f"{stream_interval:g}s"


if __name__ == "__main__":
    main()
