"""Transactional storage of collection pages, checkpoints, and weather forecasts."""

from pathlib import Path
import sqlite3
from typing import Any

from database.storage import connect, save_observation, utc_now

STREAM = "campus-energy-observations"


def get_cursor(path: Path) -> int:
    with connect(path) as connection:
        row = connection.execute(
            "SELECT cursor FROM collection_state WHERE stream = ?", (STREAM,)
        ).fetchone()
        return row[0] if row else 0


def save_page(
    path: Path, *, after: int, next_cursor: int,
    records: list[dict[str, Any]], raw: bytes,
) -> int:
    """A page and its checkpoint either both commit or both roll back."""
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT cursor FROM collection_state WHERE stream = ?", (STREAM,)
        ).fetchone()
        current = row[0] if row else 0
        if current != after:
            raise ValueError("Collection cursor changed; run only one collector")
        inserted = sum(save_observation(connection, record) for record in records)
        # Do not accumulate empty raw pages every 15 minutes.
        if records:
            connection.execute(
                "INSERT INTO api_pages "
                "(stream, after_cursor, next_cursor, fetched_at_utc, raw_content) "
                "VALUES (?, ?, ?, ?, ?)",
                (STREAM, after, next_cursor, utc_now(), raw),
            )
            connection.execute(
                "INSERT INTO collection_state VALUES (?, ?, ?) "
                "ON CONFLICT(stream) DO UPDATE SET "
                "cursor = excluded.cursor, updated_at_utc = excluded.updated_at_utc",
                (STREAM, next_cursor, utc_now()),
            )
        return inserted


def save_forecast(
    path: Path, forecast: dict[str, Any], periods: list[tuple[str, float]],
    raw: bytes,
) -> bool:
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute(
            "SELECT issued_at_utc, received_at_utc, source "
            "FROM weather_forecasts WHERE forecast_id = ?",
            (forecast["forecast_id"],),
        ).fetchone()
        identity = (forecast["issued_at"], forecast["received_at"], forecast["source"])
        if previous:
            stored = connection.execute(
                "SELECT valid_at_utc, temperature_c FROM weather_forecast_periods "
                "WHERE forecast_id = ? ORDER BY valid_at_utc",
                (forecast["forecast_id"],),
            ).fetchall()
            if tuple(previous) != identity or [tuple(row) for row in stored] != periods:
                raise ValueError("Conflicting archived weather forecast")
            return False
        connection.execute(
            "INSERT INTO weather_forecasts VALUES (?, ?, ?, ?, ?, ?)",
            (forecast["forecast_id"], *identity, utc_now(), raw),
        )
        connection.executemany(
            "INSERT INTO weather_forecast_periods VALUES (?, ?, ?)",
            [(forecast["forecast_id"], valid, temperature)
             for valid, temperature in periods],
        )
        return True


def collection_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT cursor, updated_at_utc FROM collection_state WHERE stream = ?",
        (STREAM,),
    ).fetchone()
    return {
        "api_cursor": row["cursor"] if row else 0,
        "last_collected_at": row["updated_at_utc"] if row else None,
        "weather_forecasts": connection.execute(
            "SELECT COUNT(*) FROM weather_forecasts"
        ).fetchone()[0],
    }
