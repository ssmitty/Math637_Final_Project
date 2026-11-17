"""Normalize historical CSV and JSON without using future information."""

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Iterator

from database.storage import connect, find_import, initialize
from database.storage import save_import, save_observation

BUILDINGS = ("classroom", "residence", "laboratory", "recreation", "library")


@dataclass(frozen=True)
class ImportResult:
    timestamps: int
    inserted: int
    duplicates: int


def timestamp(value: Any, *, optional: bool = False) -> str | None:
    if optional and (value is None or value == ""):
        return None
    if not isinstance(value, str):
        raise ValueError("Expected a timezone-aware timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def number(value: Any, *, optional: bool = False) -> float | None:
    if optional and (value is None or value == ""):
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a measurement")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Measurement must be finite")
    return result


def from_csv(row: dict[str, str]) -> dict[str, Any]:
    return {
        "cursor": row["cursor"],
        "timestamp": row["timestamp_utc"],
        "published_at": row["published_at_utc"],
        "quality": row["quality"],
        "scorable": row["scorable"],
        "demand_kw": {building: row[f"{building}_kw"] for building in BUILDINGS},
        "weather": {
            "temperature_c": row.get("temperature_c"),
            "observed_at": row.get("weather_observed_at_utc"),
            "received_at": row.get("weather_received_at_utc"),
            "age_seconds_at_publication": row.get(
                "weather_age_seconds_at_publication"
            ),
            "source": row.get("weather_source"),
        },
    }


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    cursor = row["cursor"]
    if isinstance(cursor, bool) or not isinstance(cursor, (str, int)):
        raise ValueError("Cursor must be a positive integer")
    cursor = int(cursor)
    if cursor <= 0:
        raise ValueError("Cursor must be a positive integer")
    scorable = row["scorable"]
    if isinstance(scorable, str):
        if scorable.lower() not in ("true", "false"):
            raise ValueError("Invalid scorable flag")
        scorable = scorable.lower() == "true"
    if not isinstance(scorable, bool):
        raise ValueError("Scorable must be true or false")
    if set(row["demand_kw"]) != set(BUILDINGS):
        raise ValueError("Each timestamp must contain all five building IDs")
    demand = {building: number(row["demand_kw"][building]) for building in BUILDINGS}
    if any(value < 0 for value in demand.values()):
        raise ValueError("Demand must be nonnegative")
    measured = timestamp(row["timestamp"])
    published = timestamp(row["published_at"])
    if published < measured:
        raise ValueError("Publication cannot precede demand measurement")
    if not isinstance(row["quality"], str) or not row["quality"].strip():
        raise ValueError("Quality must be a nonempty string")
    weather = row.get("weather") or {}
    age = number(weather.get("age_seconds_at_publication"), optional=True)
    if age is not None and age < 0:
        raise ValueError("Weather age must be nonnegative")
    return {
        "cursor": cursor, "timestamp": measured, "published_at": published,
        "demand_kw": demand, "quality": row["quality"], "scorable": scorable,
        "weather": {
            "temperature_c": number(weather.get("temperature_c"), optional=True),
            "observed_at": timestamp(weather.get("observed_at"), optional=True),
            "received_at": timestamp(weather.get("received_at"), optional=True),
            "age_seconds_at_publication": age,
            "source": weather.get("source") or None,
        },
    }


def records(content: bytes, suffix: str) -> Iterator[dict[str, Any]]:
    text = content.decode("utf-8-sig")
    if suffix == ".csv":
        yield from csv.DictReader(io.StringIO(text))
    elif suffix == ".json":
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("Historical JSON must be a list of observations")
        yield from data
    else:
        raise ValueError("History file must be CSV or JSON")


def import_history(source: Path, database: Path) -> ImportResult:
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    initialize(database)
    with connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = find_import(connection, digest)
        if previous:
            count = previous["timestamp_count"]
            return ImportResult(count, 0, count)
        cursors: list[int] = []
        seen: set[int] = set()
        inserted = 0
        for index, row in enumerate(records(content, source.suffix.lower()), start=1):
            try:
                if source.suffix.lower() == ".csv":
                    row = from_csv(row)
                record = normalize(row)
                if record["cursor"] in seen:
                    raise ValueError("Repeated cursor within history file")
                seen.add(record["cursor"])
                inserted += save_observation(connection, record)
                cursors.append(record["cursor"])
            except (KeyError, TypeError, ValueError, AttributeError) as error:
                raise ValueError(f"Invalid history record {index}: {error}") from error
        if not cursors:
            raise ValueError("History file contains no observations")
        save_import(connection, source, digest, content, cursors, inserted)
        return ImportResult(len(cursors), inserted, len(cursors) - inserted)
