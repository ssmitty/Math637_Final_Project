"""Collect observations and archive weather forecasts independently of a dashboard."""

from dataclasses import dataclass
import logging
import math
from pathlib import Path
import time
from typing import Any, Callable

from database.collection import get_cursor, save_forecast, save_page
from database.storage import initialize
from energy_pipeline.api import ApiClient, ApiError, decode
from energy_pipeline.history import normalize, number, timestamp

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionResult:
    pages: int
    inserted: int
    cursor: int
    has_more: bool


def validate_page(payload: dict[str, Any], after: int) -> tuple[list[dict], int, bool]:
    data = payload.get("data")
    following = payload.get("next_cursor")
    has_more = payload.get("has_more")
    if not isinstance(data, list) or len(data) > 96:
        raise ValueError("Observation page must contain at most 96 timestamps")
    if type(following) is not int or type(has_more) is not bool:
        raise ValueError("Invalid pagination metadata")
    try:
        records = [normalize(record) for record in data]
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Invalid observation record in API response") from error
    cursor = after
    for record in records:
        if record["cursor"] <= cursor:
            raise ValueError("Observation cursors must increase beyond saved cursor")
        cursor = record["cursor"]
    if following != cursor or (not records and has_more):
        raise ValueError("API cursor does not match the returned page")
    return records, following, has_more


def collect_observations(
    database: Path, client: ApiClient, *, max_pages: int = 100,
) -> CollectionResult:
    if max_pages < 1:
        raise ValueError("Maximum page count must be positive")
    initialize(database)
    cursor = get_cursor(database)
    inserted = 0
    for page in range(1, max_pages + 1):
        response = client.get("/v1/observations", {"after": cursor, "limit": 96})
        records, following, has_more = validate_page(decode(response), cursor)
        inserted += save_page(
            database, after=cursor, next_cursor=following,
            records=records, raw=response.body,
        )
        cursor = following
        if not has_more:
            return CollectionResult(page, inserted, cursor, False)
    LOGGER.warning("Page limit reached; remaining history will resume next run")
    return CollectionResult(max_pages, inserted, cursor, True)


def collect_weather(database: Path, client: ApiClient) -> bool:
    try:
        response = client.get("/v1/weather/forecast")
    except ApiError as error:
        if error.status == 404 or error.retryable:
            LOGGER.warning("Weather forecast unavailable: %s", error)
            return False
        raise
    payload = decode(response)
    try:
        forecast_id = payload["forecast_id"]
        source = payload["source"]
        if not isinstance(forecast_id, (str, int)) or isinstance(forecast_id, bool):
            raise ValueError("Invalid forecast identifier")
        if not str(forecast_id) or not isinstance(source, str) or not source:
            raise ValueError("Forecast identifier and source must be nonempty")
        forecast = {
            "forecast_id": str(forecast_id), "source": source,
            "issued_at": timestamp(payload["issued_at"]),
            "received_at": timestamp(payload["received_at"]),
        }
        if forecast["received_at"] < forecast["issued_at"]:
            raise ValueError("Forecast receipt cannot precede issuance")
        if not isinstance(payload["periods"], list) or not payload["periods"]:
            raise ValueError("Weather forecast must contain periods")
        periods = sorted((timestamp(p["valid_at"]), number(p["temperature_c"]))
                         for p in payload["periods"])
        if len({p[0] for p in periods}) != len(periods):
            raise ValueError("Weather forecast has duplicate target times")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Invalid weather forecast response") from error
    return save_forecast(database, forecast, periods, response.body)


def run_collection(
    database: Path, client: ApiClient, *, loop: bool = False,
    interval: float = 900, max_pages: int = 100,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    if not math.isfinite(interval) or interval < 60:
        raise ValueError("Collection interval must be finite and at least 60 seconds")
    next_weather = 0.0
    while True:
        try:
            result = collect_observations(database, client, max_pages=max_pages)
            LOGGER.info(
                "Collection saved %s new timestamps across %s pages; cursor=%s",
                result.inserted, result.pages, result.cursor,
            )
            if clock() >= next_weather:
                collect_weather(database, client)
                next_weather = clock() + 3600
        except ApiError as error:
            if not loop or not error.retryable:
                raise
            LOGGER.error("Collection cycle failed: %s; retrying next cycle", error)
        if not loop:
            return
        sleep(interval)
