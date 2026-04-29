"""Parser for Racelogic VBOX ``.vbo`` telemetry files."""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

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


def parse_vbo_file(path: str | Path) -> tuple[list[TelemetryPacket], list[str], float | None]:
    """Parse a Racelogic VBOX file into normalized telemetry packets.

    Args:
        path: Filesystem path to a ``.vbo`` text file.

    Returns:
        Tuple containing normalized packets, source column names, and an
        approximate duration in seconds when it can be calculated.

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

    rows: list[dict[str, Any]] = []
    for line in lines[data_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith("["):
            break
        if not stripped:
            continue
        values = _split_row(stripped)
        if not values:
            continue
        if len(values) < len(columns):
            values.extend([""] * (len(columns) - len(values)))
        row = {column: _coerce_value(value) for column, value in zip(columns, values, strict=False)}
        rows.append(row)

    if not rows:
        raise VBOParseError("VBO [data] section did not contain telemetry rows")

    frame = pd.DataFrame(rows)
    normalized = [_packet_from_row(index, row) for index, row in frame.iterrows()]
    normalized.sort(key=lambda packet: (packet.timestamp, packet.sequence))
    normalized = [packet.model_copy(update={"sequence": index}) for index, packet in enumerate(normalized)]
    duration = _duration(normalized)
    return normalized, list(frame.columns), duration


def _section_index(lines: list[str], section: str) -> int | None:
    """Find the line index for a bracketed VBO section.

    Args:
        lines: All lines from the VBO file.
        section: Section name without surrounding brackets.

    Returns:
        Zero-based line index when found, otherwise ``None``.
    """

    target = f"[{section}]"
    for index, line in enumerate(lines):
        if line.strip().lower() == target:
            return index
    return None


def _next_non_empty(lines: list[str], start: int, stop: int) -> str | None:
    """Find the first non-empty content line in a half-open line range.

    Args:
        lines: All lines from the VBO file.
        start: Inclusive start index.
        stop: Exclusive stop index.

    Returns:
        Stripped line text, or ``None`` if no content line exists.
    """

    for line in lines[start:stop]:
        stripped = line.strip()
        if stripped and not stripped.startswith("["):
            return stripped
    return None


def _split_row(line: str) -> list[str]:
    """Split a VBO column or data row into fields.

    Args:
        line: Raw text row from the VBO file.

    Returns:
        List of non-empty field strings split on spaces, tabs, or commas.
    """

    return [part for part in re.split(r"[\t, ]+", line.strip()) if part]


def _coerce_value(value: str) -> Any:
    """Convert a string field to a primitive value when possible.

    Args:
        value: Raw field string.

    Returns:
        ``None`` for empty or non-finite values, ``int`` for integer-like
        numbers, ``float`` for decimal numbers, or the original string.
    """

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


def _packet_from_row(sequence: int, row: pd.Series) -> TelemetryPacket:
    """Build a normalized telemetry packet from a parsed DataFrame row.

    Args:
        sequence: Source row sequence before final timestamp sorting.
        row: Pandas row containing parsed VBO field values.

    Returns:
        Normalized telemetry packet with raw values preserved.
    """

    raw = {str(key): _json_safe(value) for key, value in row.to_dict().items()}
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


def _normalized_values(raw: dict[str, Any]) -> dict[str, Any]:
    """Map known VBO column aliases to canonical telemetry names.

    Args:
        raw: Parsed source row keyed by original VBO column name.

    Returns:
        Dictionary keyed by canonical telemetry field names.
    """

    values: dict[str, Any] = {}
    for key, value in raw.items():
        canonical = _canonical_name(key)
        if canonical and canonical not in values:
            values[canonical] = value
    return values


def _canonical_name(name: str) -> str | None:
    """Return the canonical telemetry field name for a source column.

    Args:
        name: Original VBO column name.

    Returns:
        Canonical telemetry name when recognized, otherwise ``None``.
    """

    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    compact = normalized.replace("_", "")
    for canonical, aliases in _NORMALIZED_ALIASES.items():
        if normalized in aliases or compact in aliases:
            return canonical
    return None


def _timestamp_seconds(value: Any, sequence: int) -> float:
    """Normalize a timestamp value to seconds.

    Args:
        value: Raw timestamp value, usually seconds or VBOX HHMMSS.ss format.
        sequence: Row sequence used for 10 Hz fallback timing.

    Returns:
        Timestamp in seconds.
    """

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
    """Normalize a latitude or longitude value to decimal degrees.

    Args:
        value: Raw coordinate value, either decimal degrees or DDMM.MMMM.
        is_longitude: Whether the value should be validated as longitude.

    Returns:
        Decimal degrees, or ``None`` when the value is missing or invalid.
    """

    number = _optional_float(value)
    if number is None:
        return None
    limit = 180 if is_longitude else 90
    if abs(number) <= limit:
        return number
    degrees = int(abs(number) // 100)
    minutes = abs(number) - degrees * 100
    decimal = degrees + minutes / 60
    return -decimal if number < 0 else decimal


def _optional_float(value: Any) -> float | None:
    """Convert a value to a finite float when possible.

    Args:
        value: Input value from a parsed VBO row.

    Returns:
        Finite float, or ``None`` for missing/non-numeric values.
    """

    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: Any) -> int | None:
    """Convert a value to an integer when possible.

    Args:
        value: Input value from a parsed VBO row.

    Returns:
        Integer value, or ``None`` for missing/non-numeric values.
    """

    number = _optional_float(value)
    return None if number is None else int(number)


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy scalar values into JSON-safe primitives.

    Args:
        value: Value from a pandas DataFrame row.

    Returns:
        JSON-safe primitive value, or ``None`` for pandas missing values.
    """

    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _duration(samples: list[TelemetryPacket]) -> float | None:
    """Calculate approximate replay duration from parsed samples.

    Args:
        samples: Timestamp-sorted telemetry packets.

    Returns:
        Non-negative duration in seconds, or ``None`` when fewer than two
        samples exist.
    """

    if len(samples) < 2:
        return None
    return max(0.0, samples[-1].timestamp - samples[0].timestamp)
