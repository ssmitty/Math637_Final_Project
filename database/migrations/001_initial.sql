CREATE TABLE buildings (
    building_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

INSERT INTO buildings VALUES
    ('classroom', 'Gore Hall'),
    ('residence', 'Brown Hall'),
    ('laboratory', 'Building X'),
    ('recreation', 'Lil Bob Gym'),
    ('library', 'Morris Library');

CREATE TABLE observations (
    cursor INTEGER PRIMARY KEY CHECK (cursor > 0),
    timestamp_utc TEXT NOT NULL UNIQUE,
    published_at_utc TEXT NOT NULL,
    temperature_c REAL,
    weather_observed_at_utc TEXT,
    weather_received_at_utc TEXT,
    weather_age_seconds REAL CHECK (weather_age_seconds >= 0),
    weather_source TEXT,
    quality TEXT NOT NULL,
    scorable INTEGER NOT NULL CHECK (scorable IN (0, 1)),
    normalized_json TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL
);

CREATE TABLE demand_readings (
    cursor INTEGER NOT NULL REFERENCES observations(cursor),
    building_id TEXT NOT NULL REFERENCES buildings(building_id),
    demand_kw REAL NOT NULL CHECK (demand_kw >= 0),
    PRIMARY KEY (cursor, building_id)
);

CREATE INDEX demand_by_building ON demand_readings(building_id, cursor);
CREATE INDEX observations_by_publication ON observations(published_at_utc);

CREATE TABLE imports (
    import_id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    source_path TEXT NOT NULL,
    file_format TEXT NOT NULL CHECK (file_format IN ('csv', 'json')),
    raw_content BLOB NOT NULL,
    imported_at_utc TEXT NOT NULL,
    timestamp_count INTEGER NOT NULL CHECK (timestamp_count >= 0),
    inserted_count INTEGER NOT NULL CHECK (inserted_count >= 0)
);

CREATE TABLE observation_imports (
    import_id INTEGER NOT NULL REFERENCES imports(import_id),
    cursor INTEGER NOT NULL REFERENCES observations(cursor),
    PRIMARY KEY (import_id, cursor)
);

CREATE INDEX imports_by_cursor ON observation_imports(cursor);

CREATE VIEW training_observations AS
SELECT o.cursor, o.timestamp_utc, o.published_at_utc, d.building_id,
       d.demand_kw, o.temperature_c, o.weather_observed_at_utc,
       o.weather_received_at_utc, o.weather_age_seconds, o.weather_source,
       o.quality, o.scorable, o.ingested_at_utc
FROM observations AS o
JOIN demand_readings AS d ON d.cursor = o.cursor;
