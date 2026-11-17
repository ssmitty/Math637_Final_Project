"""Exercise transaction safety, provenance, and duplicate/conflict handling."""

import csv
import json
from pathlib import Path
import sqlite3

import pytest

from database.storage import connect, initialize, summary
from energy_pipeline.history import import_history


@pytest.fixture
def record() -> dict:
    return {
        "cursor": 1,
        "timestamp": "2026-11-01T12:00:00Z",
        "published_at": "2026-11-01T12:00:02Z",
        "demand_kw": {name: 100.0 for name in (
            "classroom", "residence", "laboratory", "recreation", "library"
        )},
        "weather": {
            "temperature_c": 10.0,
            "observed_at": "2026-11-01T11:50:00Z",
            "received_at": "2026-11-01T11:55:00Z",
            "age_seconds_at_publication": 602,
            "source": "test station",
        },
        "quality": "live", "scorable": True,
    }


def write_history(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_initialization_is_repeatable_and_enforces_foreign_keys(tmp_path: Path) -> None:
    path = tmp_path / "energy.sqlite3"
    initialize(path)
    initialize(path)
    with connect(path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM buildings").fetchone()[0] == 5
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO demand_readings VALUES (?, ?, ?)", (999, "library", 50)
            )


def test_import_is_repeatable_and_preserves_original_file(
    tmp_path: Path, record: dict
) -> None:
    path = tmp_path / "energy.sqlite3"
    source = write_history(tmp_path, [record])
    assert import_history(source, path).inserted == 1
    assert import_history(source, path).duplicates == 1
    assert summary(path)["demand_readings"] == 5
    assert summary(path)["imports"] == 1
    with connect(path) as connection:
        assert connection.execute(
            "SELECT raw_content FROM imports"
        ).fetchone()[0] == source.read_bytes()


def test_csv_and_json_match(tmp_path: Path, record: dict) -> None:
    path = tmp_path / "energy.sqlite3"
    import_history(write_history(tmp_path, [record]), path)
    weather = record["weather"]
    row = {
        "cursor": 1, "timestamp_utc": record["timestamp"],
        "published_at_utc": record["published_at"],
        "quality": "live", "scorable": "true", "temperature_c": 10,
        "weather_observed_at_utc": weather["observed_at"],
        "weather_received_at_utc": weather["received_at"],
        "weather_age_seconds_at_publication": 602,
        "weather_source": weather["source"],
        **{f"{name}_kw": 100 for name in record["demand_kw"]},
    }
    source = tmp_path / "history.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    result = import_history(source, path)
    assert result.duplicates == 1
    assert result.inserted == 0
    assert summary(path)["imports"] == 2


@pytest.mark.parametrize("field,value", [
    ("cursor", 1.5), ("cursor", True), ("scorable", "maybe"),
    ("timestamp", "2026-11-01T12:00:00"),
    ("published_at", "2026-11-01T11:00:00Z"),
])
def test_invalid_metadata_rolls_back(
    tmp_path: Path, record: dict, field: str, value: object
) -> None:
    record[field] = value
    path = tmp_path / "energy.sqlite3"
    with pytest.raises(ValueError):
        import_history(write_history(tmp_path, [record]), path)
    assert summary(path)["timestamps"] == 0
    assert summary(path)["imports"] == 0


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), None])
def test_invalid_demand_rolls_back(
    tmp_path: Path, record: dict, value: float | None
) -> None:
    record["demand_kw"]["library"] = value
    path = tmp_path / "energy.sqlite3"
    with pytest.raises(ValueError):
        import_history(write_history(tmp_path, [record]), path)
    assert summary(path)["demand_readings"] == 0


def test_conflict_rolls_back_earlier_rows_in_same_import(
    tmp_path: Path, record: dict
) -> None:
    path = tmp_path / "energy.sqlite3"
    import_history(write_history(tmp_path, [record]), path)
    next_record = dict(record, cursor=2, timestamp="2026-11-01T12:15:00Z",
                       published_at="2026-11-01T12:15:02Z")
    conflict = dict(record, quality="changed")
    with pytest.raises(ValueError, match="Conflicting"):
        import_history(write_history(tmp_path, [next_record, conflict]), path)
    assert summary(path)["timestamps"] == 1
    assert summary(path)["imports"] == 1


def test_stale_flags_and_missing_weather_are_preserved(
    tmp_path: Path, record: dict
) -> None:
    record.update(quality="stale", scorable=False, weather=None)
    path = tmp_path / "energy.sqlite3"
    import_history(write_history(tmp_path, [record]), path)
    assert summary(path)["unscorable_timestamps"] == 1
    with connect(path) as connection:
        row = connection.execute("SELECT * FROM observations").fetchone()
        assert row["temperature_c"] is None
        assert row["quality"] == "stale"


def test_same_timestamp_with_different_cursor_is_rejected(
    tmp_path: Path, record: dict
) -> None:
    path = tmp_path / "energy.sqlite3"
    import_history(write_history(tmp_path, [record]), path)
    with pytest.raises(ValueError, match="Conflicting"):
        import_history(write_history(tmp_path, [dict(record, cursor=2)]), path)
    assert summary(path)["timestamps"] == 1


def test_empty_history_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "energy.sqlite3"
    with pytest.raises(ValueError, match="no observations"):
        import_history(write_history(tmp_path, []), path)
    assert summary(path)["imports"] == 0


def test_malformed_csv_reports_record_number(tmp_path: Path) -> None:
    source = tmp_path / "bad.csv"
    source.write_text("cursor,timestamp_utc\n1,2026-11-01T12:00:00Z\n")
    path = tmp_path / "energy.sqlite3"
    with pytest.raises(ValueError, match="Invalid history record 1"):
        import_history(source, path)
    assert summary(path)["imports"] == 0


def test_duplicate_cursor_within_file_rolls_back(
    tmp_path: Path, record: dict
) -> None:
    path = tmp_path / "energy.sqlite3"
    with pytest.raises(ValueError, match="Repeated cursor"):
        import_history(write_history(tmp_path, [record, record]), path)
    assert summary(path)["timestamps"] == 0


def test_missing_building_is_rejected(tmp_path: Path, record: dict) -> None:
    del record["demand_kw"]["library"]
    path = tmp_path / "energy.sqlite3"
    with pytest.raises(ValueError, match="all five"):
        import_history(write_history(tmp_path, [record]), path)
    assert summary(path)["timestamps"] == 0


def test_status_does_not_create_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError, match="does not exist"):
        summary(path)
    assert not path.exists()
