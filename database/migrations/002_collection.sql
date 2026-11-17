CREATE TABLE collection_state (
    stream TEXT PRIMARY KEY,
    cursor INTEGER NOT NULL CHECK (cursor >= 0),
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE api_pages (
    page_id INTEGER PRIMARY KEY,
    stream TEXT NOT NULL,
    after_cursor INTEGER NOT NULL,
    next_cursor INTEGER NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    raw_content BLOB NOT NULL
);

CREATE TABLE weather_forecasts (
    forecast_id TEXT PRIMARY KEY,
    issued_at_utc TEXT NOT NULL,
    received_at_utc TEXT NOT NULL,
    source TEXT NOT NULL,
    first_fetched_at_utc TEXT NOT NULL,
    raw_content BLOB NOT NULL
);

CREATE INDEX forecasts_by_receipt ON weather_forecasts(received_at_utc);

CREATE TABLE weather_forecast_periods (
    forecast_id TEXT NOT NULL REFERENCES weather_forecasts(forecast_id),
    valid_at_utc TEXT NOT NULL,
    temperature_c REAL NOT NULL,
    PRIMARY KEY (forecast_id, valid_at_utc)
);
