"""Verify cursor recovery, atomic storage, weather archives, and loop behavior."""

import json
from pathlib import Path

import pytest

from database.collection import get_cursor
from database.storage import connect, initialize, summary
from energy_pipeline.api import ApiError, Response
from energy_pipeline.collector import collect_observations, collect_weather
from energy_pipeline.collector import run_collection
from energy_pipeline.history import import_history
from test_history import write_history


@pytest.fixture
def record() -> dict:
    return {
        "cursor": 1, "timestamp": "2026-11-01T12:00:00Z",
        "published_at": "2026-11-01T12:00:02Z",
        "demand_kw": {name: 100.0 for name in (
            "classroom", "residence", "laboratory", "recreation", "library"
        )},
        "weather": None, "quality": "live", "scorable": True,
    }


def page(records: list[dict], cursor: int, more: bool = False) -> Response:
    return Response(200, {}, json.dumps({
        "data": records, "next_cursor": cursor, "has_more": more,
    }).encode())


class FakeClient:
    def __init__(self, responses: list) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple] = []

    def get(self, path, params=None) -> Response:
        self.calls.append((path, params))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def test_pages_resume_from_saved_cursor(tmp_path: Path, record: dict) -> None:
    path = tmp_path / "energy.sqlite3"
    second = dict(record, cursor=2, timestamp="2026-11-01T12:15:00Z",
                  published_at="2026-11-01T12:15:02Z")
    client = FakeClient([page([record], 1, True), page([second], 2)])
    result = collect_observations(path, client)
    assert result.inserted == 2
    assert client.calls[0][1]["after"] == 0
    assert client.calls[1][1]["after"] == 1
    resumed = FakeClient([page([], 2)])
    assert collect_observations(path, resumed).inserted == 0
    assert resumed.calls[0][1]["after"] == 2
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM api_pages").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_history_overlap_is_verified_before_checkpoint(
    tmp_path: Path, record: dict
) -> None:
    path = tmp_path / "energy.sqlite3"
    import_history(write_history(tmp_path, [record]), path)
    assert get_cursor(path) == 0
    result = collect_observations(path, FakeClient([page([record], 1)]))
    assert result.inserted == 0
    assert get_cursor(path) == 1
    assert summary(path)["demand_readings"] == 5


def test_conflicting_page_rolls_back_records_and_cursor(
    tmp_path: Path, record: dict
) -> None:
    path = tmp_path / "energy.sqlite3"
    existing = dict(record, cursor=2, timestamp="2026-11-01T12:15:00Z",
                    published_at="2026-11-01T12:15:02Z")
    import_history(write_history(tmp_path, [existing]), path)
    conflict = dict(existing, quality="changed")
    with pytest.raises(ValueError, match="Conflicting"):
        collect_observations(path, FakeClient([page([record, conflict], 2)]))
    assert get_cursor(path) == 0
    assert summary(path)["timestamps"] == 1
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM api_pages").fetchone()[0] == 0


@pytest.mark.parametrize("response", [
    page([], 1), page([], 0, True), Response(200, {}, b"not json"),
    Response(200, {}, b'{"data": [], "next_cursor": true, "has_more": false}'),
])
def test_invalid_page_does_not_advance_cursor(
    tmp_path: Path, response: Response
) -> None:
    path = tmp_path / "energy.sqlite3"
    with pytest.raises(ValueError):
        collect_observations(path, FakeClient([response]))
    assert get_cursor(path) == 0


def test_failure_after_first_page_preserves_progress(
    tmp_path: Path, record: dict
) -> None:
    path = tmp_path / "energy.sqlite3"
    with pytest.raises(ApiError):
        collect_observations(path, FakeClient([
            page([record], 1, True), ApiError("offline", retryable=True),
        ]))
    assert get_cursor(path) == 1
    assert summary(path)["timestamps"] == 1


def test_page_limit_is_bounded(tmp_path: Path, record: dict) -> None:
    path = tmp_path / "energy.sqlite3"
    result = collect_observations(
        path, FakeClient([page([record], 1, True)]), max_pages=1,
    )
    assert result.has_more
    assert result.pages == 1
    assert get_cursor(path) == 1


def forecast() -> dict:
    return {
        "forecast_id": "forecast-1", "source": "test",
        "issued_at": "2026-11-01T10:00:00Z",
        "received_at": "2026-11-01T10:05:00Z",
        "periods": [{"valid_at": "2026-11-01T18:00:00Z", "temperature_c": 12}],
    }


def test_weather_archiving_deduplicates_dynamic_metadata(tmp_path: Path) -> None:
    path = tmp_path / "energy.sqlite3"
    initialize(path)
    payload = forecast()
    response = Response(200, {}, json.dumps(payload).encode())
    assert collect_weather(path, FakeClient([response]))
    payload["as_of"] = "2026-11-01T11:00:00Z"
    assert not collect_weather(path, FakeClient([
        Response(200, {}, json.dumps(payload).encode())
    ]))
    with connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM weather_forecasts"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT received_at_utc FROM weather_forecasts"
        ).fetchone()[0] == "2026-11-01T10:05:00.000Z"


def test_weather_conflicts_are_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "energy.sqlite3"
    initialize(path)
    payload = forecast()
    collect_weather(path, FakeClient([Response(200, {}, json.dumps(payload).encode())]))
    payload["periods"][0]["temperature_c"] = 99
    with pytest.raises(ValueError, match="Conflicting"):
        collect_weather(path, FakeClient([
            Response(200, {}, json.dumps(payload).encode())
        ]))


def test_missing_weather_does_not_discard_demand(tmp_path: Path, record: dict) -> None:
    path = tmp_path / "energy.sqlite3"
    run_collection(path, FakeClient([
        page([record], 1), ApiError("not available", status=404),
    ]))
    assert summary(path)["timestamps"] == 1


def test_loop_retries_temporary_failures(tmp_path: Path) -> None:
    sleeps = []

    def stop(seconds: float) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_collection(tmp_path / "energy.sqlite3", FakeClient([
            ApiError("offline", retryable=True),
        ]), loop=True, sleep=stop)
    assert sleeps == [900]


def test_loop_stops_on_auth_failure(tmp_path: Path) -> None:
    with pytest.raises(ApiError):
        run_collection(tmp_path / "energy.sqlite3", FakeClient([
            ApiError("unauthorized", status=401),
        ]), loop=True, sleep=lambda _: pytest.fail("Must not retry auth errors"))


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_invalid_intervals_are_rejected(tmp_path: Path, interval: float) -> None:
    with pytest.raises(ValueError, match="interval"):
        run_collection(tmp_path / "energy.sqlite3", FakeClient([]), interval=interval)


def test_existing_history_survives_collection_migration(
    tmp_path: Path, record: dict
) -> None:
    from importlib.resources import files
    import sqlite3

    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    try:
        initial = files("database").joinpath("migrations/001_initial.sql")
        connection.executescript(initial.read_text())
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at_utc TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?, ?)",
            ("001_initial.sql", "2026-11-01T12:00:00Z"),
        )
        from database.storage import save_observation
        from energy_pipeline.history import normalize

        save_observation(connection, normalize(record))
        connection.commit()
    finally:
        connection.close()
    initialize(path)
    assert summary(path)["timestamps"] == 1
    assert summary(path)["demand_readings"] == 5
    assert get_cursor(path) == 0


def test_weather_is_collected_hourly_in_loop(tmp_path: Path) -> None:
    weather = Response(200, {}, json.dumps(forecast()).encode())
    client = FakeClient([
        page([], 0), weather, page([], 0), page([], 0),
        page([], 0), page([], 0), weather,
    ])
    now = 0.0
    cycles = 0

    def advance(seconds: float) -> None:
        nonlocal now, cycles
        now += seconds
        cycles += 1
        if cycles == 5:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_collection(
            tmp_path / "energy.sqlite3", client, loop=True,
            sleep=advance, clock=lambda: now,
        )
    assert sum(path == "/v1/weather/forecast" for path, _ in client.calls) == 2
