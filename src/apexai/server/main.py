"""CLI bootstrap for the ApexAI telemetry streaming server.

This module owns command-line parsing and source construction. It validates the
arguments needed by each source, creates the selected VBO or CAN producer, then
passes that producer into the FastAPI app. SSE and WebSocket clients connect to
the same endpoints regardless of which source is selected.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from .api import create_app
from .broadcaster import Broadcaster
from .config import ServerConfig
from .telemetry_sources import ParsedVBO, TelemetrySource, VBOTelemetrySource
from .vbo_parser import VBOParseError, parse_vbo_file


class _ArgumentFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    """Preserve multiline hints while also showing default argument values."""


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the telemetry server.

    The parser includes both source-independent server options and
    source-specific input options. ``--source vbo`` requires ``--vbo-file``.
    ``--source can`` requires ``--dbc-file`` and uses the CAN interface/channel
    arguments to open a ``python-can`` bus.

    Returns:
        Configured argument parser for ``python -m apexai.server``.
    """

    parser = argparse.ArgumentParser(
        description="ApexAI telemetry streaming server",
        formatter_class=_ArgumentFormatter,
        epilog=(
            "Hints:\n"
            "  VBO replay: apexai-server --autostart\n"
            "  Output frequency: POST /replay/stream-interval with seconds=0.1 for about 10 Hz."
        ),
    )
    parser.add_argument("--data-dir", default="data", help="Path to the directory containing VBO files.")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface for the FastAPI server to bind.")
    import os
    default_port = int(os.environ.get("PORT", 8000))
    parser.add_argument("--port", default=default_port, type=int, help="TCP port for HTTP, SSE, and WebSocket traffic.")
    parser.add_argument(
        "--replay-speed",
        default=1.0,
        type=float,
        help="VBO-only replay speed multiplier. Ignored by live CAN because CAN timing is source-driven.",
    )
    parser.add_argument(
        "--stream-interval",
        default=None,
        type=float,
        help=(
            "Fixed seconds between published packets. For VBO, omit to use source timestamps. "
            "For CAN, omit to publish every decoded frame. Example: 0.1 is about 10 Hz."
        ),
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="VBO-only option to restart replay from the first sample after the final sample.",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Start the selected source during FastAPI startup instead of waiting for POST /replay/start.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse arguments, build the telemetry source, and run FastAPI.

    Args:
        argv: Optional argument list for tests or embedded usage. When ``None``,
            arguments are read from ``sys.argv``.

    Returns:
        None.

    Raises:
        SystemExit: If required source-specific arguments are missing, timing
            values are invalid, the VBO file cannot be parsed, or a VBO file has
            no samples.
    """

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    args = build_parser().parse_args(argv)
    if args.stream_interval is not None and args.stream_interval <= 0:
        raise SystemExit("--stream-interval must be greater than zero")
    config = ServerConfig(
        data_dir=Path(args.data_dir),
        host=args.host,
        port=args.port,
        replay_speed=args.replay_speed,
        stream_interval=args.stream_interval,
        loop=args.loop,
        autostart=args.autostart,
    )

    broadcaster = Broadcaster()
    source, sample_count, columns, duration = _build_source(config, broadcaster)
    _print_summary(config, source, sample_count, columns, duration)

    app = create_app(config, source, broadcaster)
    uvicorn.run(app, host=config.host, port=config.port)


def _build_source(
    config: ServerConfig,
    broadcaster: Broadcaster,
) -> tuple[TelemetrySource, int, list[str], float | None]:
    """Create the configured telemetry source.

    Args:
        config: Runtime server configuration created from command-line
            arguments. ``config.source`` selects VBO or CAN.
        broadcaster: Publisher shared by all output transports.

    Returns:
        Tuple containing the source, sample count, source columns/signals, and
        approximate duration when known.

    Raises:
        SystemExit: If required source files are missing or VBO parsing fails.
    """

    vbo_files = list(config.data_dir.glob("*.vbo"))
    if not vbo_files:
        raise SystemExit(f"No VBO files found in directory: {config.data_dir}")

    parsed_vbos: list[ParsedVBO] = []
    all_columns = []
    total_duration = 0.0
    current_time_offset = 0.0
    current_sequence_offset = 0
    last_timestamp = None

    for vbo_file in vbo_files:
        try:
            lines, columns, first_ts, last_ts = parse_vbo_file(vbo_file)
        except (FileNotFoundError, VBOParseError) as exc:
            logging.getLogger(__name__).error("%s", exc)
            raise SystemExit(1) from exc
        except Exception as exc:
            logging.getLogger(__name__).exception("failed to parse VBO file %s", vbo_file)
            raise SystemExit(1) from exc

        if not lines:
            continue

        time_offset = 0.0
        if last_timestamp is not None and first_ts is not None:
            time_offset = current_time_offset + (last_timestamp + 1.0 - first_ts)
            current_time_offset = time_offset
            
        parsed_vbos.append(
            ParsedVBO(
                file_path=str(vbo_file),
                columns=columns,
                data_lines=lines,
                first_timestamp=first_ts,
                last_timestamp=last_ts,
                sequence_offset=current_sequence_offset,
                time_offset=time_offset,
            )
        )
        
        current_sequence_offset += len(lines)
        if last_ts is not None:
            last_timestamp = last_ts
        for col in columns:
            if col not in all_columns:
                all_columns.append(col)
        if last_ts is not None and first_ts is not None:
            total_duration += max(0.0, last_ts - first_ts)

    if not parsed_vbos:
        logging.getLogger(__name__).error("no telemetry samples parsed from any VBO files")
        raise SystemExit(1)

    return (
        VBOTelemetrySource(
            parsed_vbos,
            broadcaster,
            replay_speed=config.replay_speed,
            stream_interval=config.stream_interval,
            loop=config.loop,
        ),
        current_sequence_offset,
        all_columns,
        total_duration,
    )


def _print_summary(
    config: ServerConfig,
    source: TelemetrySource,
    sample_count: int,
    columns: list[str],
    duration: float | None,
) -> None:
    """Print a concise startup summary with source-specific hints.

    Args:
        config: Runtime server configuration.
        source: Constructed source used to report initial state.
        sample_count: Number of parsed telemetry samples.
        columns: Original VBO column names. Empty for live CAN.
        duration: Approximate replay duration in seconds. Unknown for live CAN.

    Returns:
        None.
    """

    duration_text = "unknown" if duration is None else f"{duration:.3f}s"
    print("ApexAI telemetry streaming server")
    file_names = ", ".join(f.name for f in list(config.data_dir.glob("*.vbo")))
    print(f"  VBO files: {file_names}")
    print(f"  Samples: {sample_count}")
    print(f"  Columns: {', '.join(columns)}")
    print(f"  Approx duration: {duration_text}")
    print(f"  Replay speed: {config.replay_speed}x")
    print(f"  Stream interval: {_format_stream_interval(config.stream_interval)}")
    print(f"  Loop: {config.loop}")
    print(f"  Autostart: {config.autostart}")
    print(f"  State: {source.state().status}")
    sys.stdout.flush()


def _format_stream_interval(stream_interval: float | None) -> str:
    """Format the fixed stream interval for startup output.

    Args:
        stream_interval: Positive fixed seconds between packets, or ``None`` for
            source-driven timing.

    Returns:
        Human-readable text for the startup summary.
    """

    if stream_interval is None:
        return "source timestamps"
    return f"{stream_interval:g}s"


if __name__ == "__main__":
    main()
