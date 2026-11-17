# MATH 637 campus energy pipeline

Local SQLite storage and historical ingestion for the five-building forecasting
project. Python 3.12+ is required; the application uses only the standard library.

## Local setup

Run from the project directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[dev]'
energy-pipeline init
energy-pipeline import-history /Users/sean/Downloads/energy_history.json
energy-pipeline status
python -m pytest
```

After changing application code, rerun `python -m pip install '.[dev]'` to update
the installed command.

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
- `collection_state` and `api_pages`: live collection checkpoint and raw pages.
- `weather_forecasts` and `weather_forecast_periods`: archived forecasts with
  issue, receipt, and target times for historical model evaluation.
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

## API collection

First apply migrations if the database already exists:

```sh
energy-pipeline init
```

Provide your team key in the `ENERGY_API_KEY` environment variable. In macOS zsh,
enter it through a hidden prompt so it is not saved in shell history:

```sh
read -rs 'ENERGY_API_KEY?Team API key: '
export ENERGY_API_KEY
```

Run one collection cycle, or keep collecting every 15 minutes:

```sh
energy-pipeline collect
energy-pipeline collect --loop
```

Use Ctrl+C to stop. Run only one collector per database. The collector retrieves
up to 100 demand pages per cycle (96 timestamps per page), then resumes on the
next cycle if more remain. A one-time run also reports if its page limit is hit.
Override the limit with `--max-pages`. The loop archives weather forecasts once
per hour, starting on its first cycle. A one-time run attempts weather once.

The first live collection starts at cursor zero, even after historical import.
Matching records are verified and skipped. A mismatch stops collection for
investigation without overwriting the original data. Each nonempty page, its
readings, and its checkpoint commit atomically. Network calls happen outside
database transactions. No cursor is inferred from a historical file.

Requests are spaced at least 2.1 seconds apart, leaving headroom below the shared
30-request minute limit. Retries use increasing delays, honor `Retry-After` on
HTTP 429, and stop after five attempts. Other team programs share the same API
quota. Temporary demand failures are retried on the next loop cycle; permanent
HTTP errors, malformed responses, and data conflicts stop the collector. Weather
404 and temporary failures are logged without discarding saved demand pages.
The key is never written to logs or the database, and redirects are rejected.

`energy-pipeline status` reports the API cursor, last saved nonempty demand page,
and archived weather forecast count alongside the stored demand coverage.
An unchanged cursor does not prove a collection process is currently running.

## Persistence and next milestones

Database files, local data, virtual environments, and `.env` files are ignored by
Git. Commit code and migrations, not runtime database files or API credentials.
Keep private backups; this initial implementation does not automate backups.

This implementation does not train models, submit forecasts, serve a dashboard,
or install a background service. Next, build time-aware training examples and a
baseline hourly prediction/submission job. API behavior is tested using simulated
responses; live integration requires the private team key.

Local jobs will only run while this computer is awake and connected. The same
code can later be installed on a server, with its database on persistent disk.
