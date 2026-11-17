# MATH 637 campus energy pipeline

Local SQLite storage and historical ingestion for the five-building forecasting
project. Python 3.12+ is required; the application uses only the standard library.

## Local setup

Run from the project directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
energy-pipeline init
energy-pipeline import-history /Users/sean/Downloads/energy_history.json
energy-pipeline status
python -m pytest
```

CSV is also supported. Import either history file first. Importing the other
format adds source provenance without duplicating matching observations.

```sh
energy-pipeline import-history /Users/sean/Downloads/energy_history.csv
```

The default database is `data/energy.sqlite3`, relative to the current directory.
To use another location, put the option before the command:

```sh
energy-pipeline --database /absolute/path/energy.sqlite3 status
```

## Storage behavior

- `observations`: one row per timestamp, with the API cursor, publication time,
  observed weather, quality, scoring eligibility, and normalized record.
- `demand_readings`: one row per building and timestamp, measured in kW.
- `buildings`: the five assignment building identifiers.
- `imports`: original file bytes, SHA-256 hash, source path, and import totals.
- `observation_imports`: links observations to their original import files.
- `schema_migrations`: records applied migrations in `database/migrations/`.
- `training_observations`: a view joining demand and observation metadata. It is
  an input for future feature creation, not a finished labeled training dataset.

Every connection enables foreign keys. Imports are transactional. Matching
observations are deduplicated; conflicting cursors or timestamps fail the entire
import without overwriting existing observations. Invalid data are rejected with
a record number. Stale and unscorable observations remain flagged in storage;
missing intervals are not filled and no targets are invented.

Publication and weather receipt times are retained so future training code can
filter features to information available at each historical prediction time.
The observed weather in these history files is not a future weather forecast.

## Persistence and next milestones

Database files, local data, virtual environments, and `.env` files are ignored by
Git. Commit code and migrations, not runtime database files or API credentials.
Keep private backups; this initial implementation does not automate backups.

This milestone does not yet poll the API, schedule jobs, train models, submit
forecasts, or serve a dashboard. Next, add a collector with atomic page storage
and cursor checkpoints, then archive weather forecasts and build time-aware
training examples. A historical import deliberately does not set the live API
checkpoint; the collector must verify overlap against the actual API history.

Local jobs will only run while this computer is awake and connected. The same
code can later be installed on a server, with its database on persistent disk.
