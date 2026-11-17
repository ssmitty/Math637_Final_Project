"""Keep SQL operations separate from import and forecasting logic."""

from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on failure, and always close the connection."""
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(path: Path) -> None:
    """Apply pending migrations without replacing existing data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = files("database").joinpath("migrations")
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at_utc TEXT NOT NULL)"
        )
        for migration in sorted(migrations.iterdir(), key=lambda item: item.name):
            if not migration.name.endswith(".sql"):
                continue
            applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?", (migration.name,)
            ).fetchone()
            if applied:
                continue
            # These migrations contain simple statements, not triggers or scripts.
            for statement in migration.read_text().split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations VALUES (?, ?)",
                (migration.name, utc_now()),
            )


def save_observation(
    connection: sqlite3.Connection, record: dict[str, Any]
) -> bool:
    """Insert a new timestamp; reject conflicting immutable observations."""
    canonical = json.dumps(record, sort_keys=True, allow_nan=False)
    existing = connection.execute(
        "SELECT normalized_json FROM observations "
        "WHERE cursor = ? OR timestamp_utc = ?",
        (record["cursor"], record["timestamp"]),
    ).fetchall()
    if existing:
        if len(existing) != 1 or existing[0]["normalized_json"] != canonical:
            raise ValueError(
                f"Conflicting observation at cursor {record['cursor']} "
                f"or timestamp {record['timestamp']}"
            )
        return False
    weather = record["weather"]
    connection.execute(
        "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record["cursor"], record["timestamp"], record["published_at"],
            weather["temperature_c"], weather["observed_at"],
            weather["received_at"], weather["age_seconds_at_publication"],
            weather["source"], record["quality"], int(record["scorable"]),
            canonical, utc_now(),
        ),
    )
    connection.executemany(
        "INSERT INTO demand_readings VALUES (?, ?, ?)",
        [(record["cursor"], building, value)
         for building, value in record["demand_kw"].items()],
    )
    return True


def find_import(connection: sqlite3.Connection, digest: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM imports WHERE sha256 = ?", (digest,)
    ).fetchone()


def save_import(
    connection: sqlite3.Connection, source: Path, digest: str,
    content: bytes, cursors: list[int], inserted: int,
) -> None:
    result = connection.execute(
        "INSERT INTO imports (sha256, source_path, file_format, raw_content, "
        "imported_at_utc, timestamp_count, inserted_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (digest, str(source.resolve()), source.suffix[1:].lower(), content,
         utc_now(), len(cursors), inserted),
    )
    connection.executemany(
        "INSERT INTO observation_imports VALUES (?, ?)",
        [(result.lastrowid, cursor) for cursor in cursors],
    )


def summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("Database does not exist. Run init or import-history first.")
    with connect(path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS timestamps, MIN(timestamp_utc) AS first_timestamp, "
            "MAX(timestamp_utc) AS latest_timestamp, "
            "COALESCE(SUM(scorable = 0), 0) AS unscorable_timestamps "
            "FROM observations"
        ).fetchone()
        result = dict(row)
        result["demand_readings"] = connection.execute(
            "SELECT COUNT(*) FROM demand_readings"
        ).fetchone()[0]
        result["imports"] = connection.execute(
            "SELECT COUNT(*) FROM imports"
        ).fetchone()[0]
        return result
