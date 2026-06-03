"""CLI bootstrap for the ApexAI telemetry streaming server.

This module owns command-line parsing and source construction. It validates the
selected VBO or CAN raw chunk file, creates the matching replay producer, then
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
from .telemetry_sources import (
    CanDecodedTelemetrySource,
    CanRawChunkTelemetrySource,
    ParsedVBO,
    TelemetrySource,
    VBOTelemetrySource,
    decode_can_raw_frame_file_to_csv,
    parse_can_raw_chunk_file,
)
from .vbo_parser import VBOParseError, parse_vbo_file


class _ArgumentFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    """Preserve multiline hints while also showing default argument values."""


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the telemetry server.

    The parser includes source-independent server options and a single-file
    ``--input-file`` selector. ``--vbo-file`` remains as a compatibility alias.

    Returns:
        Configured argument parser for ``python -m apexai.server``.
    """

    parser = argparse.ArgumentParser(
        description="ApexAI telemetry streaming server",
        formatter_class=_ArgumentFormatter,
        epilog=(
            "Hints:\n"
            "  VBO replay: apexai-server --input-file dashboard/data/raw/VBOX0148.vbo --autostart\n"
            "  CAN raw replay: apexai-server --input-file telemetry-data/CAN_files/can_raw_hex_chunks_usb_20260523_113848_600.txt --autostart\n"
            "  CAN decoded replay: apexai-server --input-file telemetry-data/CAN_files/can_raw_frames_usb_20260523_113848_600.txt --decoded --autostart\n"
            "  Output frequency: POST /replay/stream-interval with seconds=0.1 for about 10 Hz."
        ),
    )
    parser.add_argument(
        "--input-file",
        default=None,
        help="Path to one telemetry file. Supports .vbo, can_raw_hex_chunks*.txt, and can_raw_frames*.txt files.",
    )
    parser.add_argument(
        "--vbo-file",
        default=None,
        help="Backward-compatible alias for --input-file when selecting one VBO file.",
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
        help="Replay speed multiplier for VBO timestamps or CAN raw chunk capture timestamps.",
    )
    parser.add_argument(
        "--stream-interval",
        default=None,
        type=float,
        help=(
            "Fixed seconds between published packets. Omit to use VBO timestamps or CAN capture timestamps. "
            "Example: 0.1 is about 10 Hz."
        ),
    )
    parser.add_argument(
        "--no-loop",
        action="store_false",
        dest="loop",
        help="Disable looping the replay files.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        dest="loop",
        help="Loop the replay files (default).",
    )
    parser.set_defaults(loop=True)
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Start the selected source during FastAPI startup instead of waiting for POST /replay/start.",
    )
    parser.add_argument(
        "--decoded",
        action="store_true",
        help="Decode CAN raw frame files through apexai.scripts.decode_can before streaming readable values.",
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
        input_file=Path(args.input_file or args.vbo_file) if (args.input_file or args.vbo_file) else None,
        decoded=args.decoded,
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
            arguments. ``config.input_file`` selects one VBO or CAN file when set.
        broadcaster: Publisher shared by all output transports.

    Returns:
        Tuple containing the source, sample count, source columns/signals, and
        approximate duration when known.

    Raises:
        SystemExit: If required source files are missing or VBO parsing fails.
    """

    if config.input_file is not None:
        return _build_file_source(config.input_file, config, broadcaster)

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


def _build_file_source(
    input_file: Path,
    config: ServerConfig,
    broadcaster: Broadcaster,
) -> tuple[TelemetrySource, int, list[str], float | None]:
    """Create a telemetry source from one selected input file."""

    suffix = input_file.suffix.lower()
    if suffix == ".vbo":
        return _build_vbo_file_source(input_file, config, broadcaster)
    if suffix == ".txt" and "can_raw_hex_chunks" in input_file.name:
        if config.decoded:
            raise SystemExit("--decoded requires a can_raw_frames*.txt file; hex chunk files are streamed raw.")
        return _build_can_raw_file_source(input_file, config, broadcaster)
    if suffix == ".txt" and "can_raw_frames" in input_file.name:
        if not config.decoded:
            raise SystemExit("CAN raw frame files must be streamed with --decoded.")
        return _build_can_decoded_file_source(input_file, config, broadcaster)
    raise SystemExit(
        "Unsupported telemetry input file. Use a .vbo, can_raw_hex_chunks*.txt, or can_raw_frames*.txt file."
    )


def _build_vbo_file_source(
    vbo_file: Path,
    config: ServerConfig,
    broadcaster: Broadcaster,
) -> tuple[TelemetrySource, int, list[str], float | None]:
    """Create a VBO replay source from a single VBO file."""

    try:
        lines, columns, first_ts, last_ts = parse_vbo_file(vbo_file)
    except (FileNotFoundError, VBOParseError) as exc:
        logging.getLogger(__name__).error("%s", exc)
        raise SystemExit(1) from exc
    except Exception as exc:
        logging.getLogger(__name__).exception("failed to parse VBO file %s", vbo_file)
        raise SystemExit(1) from exc

    if not lines:
        logging.getLogger(__name__).error("no telemetry samples parsed from VBO file %s", vbo_file)
        raise SystemExit(1)

    parsed_vbo = ParsedVBO(
        file_path=str(vbo_file),
        columns=columns,
        data_lines=lines,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        sequence_offset=0,
        time_offset=0.0,
    )
    duration = None if first_ts is None or last_ts is None else max(0.0, last_ts - first_ts)
    return (
        VBOTelemetrySource(
            [parsed_vbo],
            broadcaster,
            replay_speed=config.replay_speed,
            stream_interval=config.stream_interval,
            loop=config.loop,
        ),
        len(lines),
        columns,
        duration,
    )


def _build_can_raw_file_source(
    can_file: Path,
    config: ServerConfig,
    broadcaster: Broadcaster,
) -> tuple[TelemetrySource, int, list[str], float | None]:
    """Create an opaque CAN raw hex chunk replay source."""

    try:
        chunks = parse_can_raw_chunk_file(can_file)
    except FileNotFoundError as exc:
        logging.getLogger(__name__).error("%s", exc)
        raise SystemExit(1) from exc

    if not chunks:
        logging.getLogger(__name__).error("no CAN raw hex chunks parsed from file %s", can_file)
        raise SystemExit(1)

    first_ts = chunks[0].timestamp
    last_ts = chunks[-1].timestamp
    duration = max(0.0, (last_ts - first_ts) / 1000.0)
    return (
        CanRawChunkTelemetrySource(
            can_file,
            chunks,
            broadcaster,
            replay_speed=config.replay_speed,
            stream_interval=config.stream_interval,
            loop=config.loop,
        ),
        len(chunks),
        ["timestamp_ms", "raw_hex_chunk"],
        duration,
    )


def _build_can_decoded_file_source(
    can_file: Path,
    config: ServerConfig,
    broadcaster: Broadcaster,
) -> tuple[TelemetrySource, int, list[str], float | None]:
    """Decode a CAN raw frame file to CSV and create a readable replay source."""

    try:
        rows, decoded_csv = decode_can_raw_frame_file_to_csv(can_file)
    except (FileNotFoundError, RuntimeError) as exc:
        logging.getLogger(__name__).error("%s", exc)
        raise SystemExit(1) from exc

    if not rows:
        logging.getLogger(__name__).error("no decoded CAN frames parsed from file %s", can_file)
        raise SystemExit(1)

    first_ts = rows[0].timestamp
    last_ts = rows[-1].timestamp
    duration = max(0.0, last_ts - first_ts)
    return (
        CanDecodedTelemetrySource(
            can_file,
            rows,
            decoded_csv,
            broadcaster,
            replay_speed=config.replay_speed,
            stream_interval=config.stream_interval,
            loop=config.loop,
        ),
        len(rows),
        list(rows[0].values.keys()),
        duration,
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
        columns: Original VBO column names or CAN raw payload labels.
        duration: Approximate replay duration in seconds.

    Returns:
        None.
    """

    duration_text = "unknown" if duration is None else f"{duration:.3f}s"
    print("ApexAI telemetry streaming server")
    state = source.state()
    if config.input_file is not None:
        print(f"  Input file: {config.input_file}")
    else:
        file_names = ", ".join(f.name for f in list(config.data_dir.glob("*.vbo")))
        print(f"  VBO files: {file_names}")
    print(f"  Source: {state.source}")
    if isinstance(source, CanDecodedTelemetrySource):
        print(f"  Decoded CSV: {source.decoded_csv}")
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
