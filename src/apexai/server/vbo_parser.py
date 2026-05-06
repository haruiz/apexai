"""Parser for Racelogic VBOX ``.vbo`` telemetry files."""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any

from .schemas import TelemetryPacket

logger = logging.getLogger(__name__)


class VBOParseError(ValueError):
    """Raised when a VBO file cannot be parsed into telemetry samples."""


_NORMALIZED_ALIASES = {
    "time": {"time", "timestamp", "utc", "sats_time"},
    "latitude": {"lat", "latitude"},
    "longitude": {"long", "lon", "lng", "longitude"},
    "speed": {"velocity", "vel", "speed", "kmh", "mph"},
    "heading": {"heading", "head"},
    "altitude": {"height", "alt", "altitude"},
    "satellites": {"satellites", "sats", "sat"},
    "brake": {"brake", "brakepos", "brake_position"},
    "throttle": {"throttle", "throttlepos", "throttle_position", "tps"},
    "steering": {"steering", "steer", "steeringangle", "steering_angle"},
    "gear": {"gear", "gearnum", "gear_num"},
    "lap": {"lap", "lapnum", "lap_number"},
}


def parse_vbo_file(path: str | Path) -> tuple[list[str], list[str], float | None, float | None]:
    """Parse a Racelogic VBOX file and extract the raw data lines.

    Args:
        path: Filesystem path to a ``.vbo`` text file.

    Returns:
        Tuple containing raw data lines, source column names, first timestamp,
        and last timestamp in seconds.

    Raises:
        FileNotFoundError: If the path does not exist or is not a file.
        VBOParseError: If required VBO sections or telemetry rows are missing.
    """

    vbo_path = Path(path)
    if not vbo_path.exists():
        raise FileNotFoundError(f"VBO file does not exist: {vbo_path}")
    if not vbo_path.is_file():
        raise FileNotFoundError(f"VBO path is not a file: {vbo_path}")

    text = vbo_path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    column_index = _section_index(lines, "column names")
    data_index = _section_index(lines, "data")
    if column_index is None:
        raise VBOParseError("VBO file is missing a [column names] section")
    if data_index is None:
        raise VBOParseError("VBO file is missing a [data] section")

    column_line = _next_non_empty(lines, column_index + 1, data_index)
    if not column_line:
        raise VBOParseError("VBO [column names] section is empty")

    columns = _split_row(column_line)
    if not columns:
        raise VBOParseError("VBO [column names] section did not contain any columns")

    rows: list[str] = []
    for line in lines[data_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith("["):
            break
        if not stripped:
            continue
        rows.append(stripped)

    if not rows:
        raise VBOParseError("VBO [data] section did not contain telemetry rows")

    first_packet = parse_vbo_line(0, rows[0], columns)
    last_packet = parse_vbo_line(len(rows) - 1, rows[-1], columns)

    first_ts = first_packet.timestamp if first_packet else None
    last_ts = last_packet.timestamp if last_packet else None

    return rows, columns, first_ts, last_ts


def parse_vbo_line(sequence: int, line: str, columns: list[str]) -> TelemetryPacket | None:
    """Parse a single raw VBO data row into a TelemetryPacket.

    Args:
        sequence: The sequence number for this row.
        line: Raw text row from the VBO file.
        columns: The column definitions for the file.

    Returns:
        A parsed TelemetryPacket or None if the row is empty.
    """
    values = _split_row(line)
    if not values:
        return None
    if len(values) < len(columns):
        values.extend([""] * (len(columns) - len(values)))

    raw = {column: _coerce_value(value) for column, value in zip(columns, values, strict=False)}
    normalized = _normalized_values(raw)
    timestamp = _timestamp_seconds(normalized.get("time"), sequence)

    return TelemetryPacket(
        sequence=sequence,
        timestamp=timestamp,
        latitude=_coordinate(normalized.get("latitude"), is_longitude=False),
        longitude=_coordinate(normalized.get("longitude"), is_longitude=True),
        speed=_optional_float(normalized.get("speed")),
        heading=_optional_float(normalized.get("heading")),
        altitude=_optional_float(normalized.get("altitude")),
        satellites=_optional_int(normalized.get("satellites")),
        throttle=_optional_float(normalized.get("throttle")),
        brake=_optional_float(normalized.get("brake")),
        steering=_optional_float(normalized.get("steering")),
        gear=_optional_int(normalized.get("gear")),
        lap=_optional_int(normalized.get("lap")),
        raw=raw,
    )


def _section_index(lines: list[str], section: str) -> int | None:
    """Find the line index for a bracketed VBO section."""
    target = f"[{section}]"
    for index, line in enumerate(lines):
        if line.strip().lower() == target:
            return index
    return None


def _next_non_empty(lines: list[str], start: int, stop: int) -> str | None:
    """Find the first non-empty content line in a half-open line range."""
    for line in lines[start:stop]:
        stripped = line.strip()
        if stripped and not stripped.startswith("["):
            return stripped
    return None


def _split_row(line: str) -> list[str]:
    """Split a VBO column or data row into fields."""
    return [part for part in re.split(r"[\t, ]+", line.strip()) if part]


def _coerce_value(value: str) -> Any:
    """Convert a string field to a primitive value when possible."""
    if value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return value
    if not math.isfinite(number):
        return None
    if number.is_integer():
        return int(number)
    return number


def _normalized_values(raw: dict[str, Any]) -> dict[str, Any]:
    """Map known VBO column aliases to canonical telemetry names."""
    values: dict[str, Any] = {}
    for key, value in raw.items():
        canonical = _canonical_name(key)
        if canonical and canonical not in values:
            values[canonical] = value
    return values


def _canonical_name(name: str) -> str | None:
    """Return the canonical telemetry field name for a source column."""
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    compact = normalized.replace("_", "")
    for canonical, aliases in _NORMALIZED_ALIASES.items():
        if normalized in aliases or compact in aliases:
            return canonical
    return None


def _timestamp_seconds(value: Any, sequence: int) -> float:
    """Normalize a timestamp value to seconds."""
    number = _optional_float(value)
    if number is None:
        return sequence * 0.1
    if abs(number) >= 10000:
        whole = int(abs(number))
        fraction = abs(number) - whole
        seconds = whole % 100
        minutes = (whole // 100) % 100
        hours = whole // 10000
        parsed = hours * 3600 + minutes * 60 + seconds + fraction
        return -parsed if number < 0 else parsed
    return number


def _coordinate(value: Any, *, is_longitude: bool) -> float | None:
    """Normalize a latitude or longitude value to decimal degrees."""
    number = _optional_float(value)
    if number is None:
        return None
    limit = 180 if is_longitude else 90
    if abs(number) <= limit:
        return number
        
    # The dataset coordinates are stored purely in minutes (e.g. 2289.715548).
    decimal = abs(number) / 60.0
    
    if is_longitude:
        # VBOX standard: Positive is West, Negative is East
        # Standard GPS: Positive is East, Negative is West
        return -decimal if number > 0 else decimal
    else:
        # VBOX standard: Positive is North, Negative is South
        return -decimal if number < 0 else decimal


def _optional_float(value: Any) -> float | None:
    """Convert a value to a finite float when possible."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: Any) -> int | None:
    """Convert a value to an integer when possible."""
    number = _optional_float(value)
    return None if number is None else int(number)
