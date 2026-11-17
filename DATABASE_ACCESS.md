# Using the database for modeling

This guide is for macOS. You can copy and paste the commands without knowing
Python or SQL. Run each command in Terminal, then press Enter.

The database is a local file named `data/energy.sqlite3`. No database account,
paid service, or running server is needed. Reading saved data does not require
the team API key.

## 1. Open the project folder

Open Terminal. Type `cd` followed by a space, drag the project folder from Finder
into Terminal, and press Enter. This tells Terminal which folder to work in.

On Sean's current computer, you can instead paste:

```zsh
cd "/Users/sean/Documents/ChatGPT/637 DataScience Project"
```

Keep this Terminal window open for the remaining steps.

## 2. Set up Python once

Skip this step if the project already works on your computer.
You need Python 3.12 or newer; check with `python3 --version`.

```zsh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/energy-pipeline init
```

These commands create the project's Python environment, install the application,
and prepare the database. `init` preserves existing readings.

## 3. Check that data is available

```zsh
.venv/bin/energy-pipeline status
```

Look for:

- **timestamps:** how many measurement times are stored.
- **demand_readings:** how many individual building readings are stored.
- **latest_timestamp:** the newest demand measurement, shown in UTC.

If these counts are above zero, proceed to step 4.

**If the database is empty:** GitHub contains the code, not the database or key.
Obtain `energy_history.json` from the course materials or your team and put it in
Downloads. Then run:

```zsh
.venv/bin/energy-pipeline import-history ~/Downloads/energy_history.json
.venv/bin/energy-pipeline status
```

Importing the same history again does not add duplicate readings. To collect
newer data, follow [API collection in the README](README.md#api-collection).
You do not need to run collection while analyzing data already stored.

## 4. Export the data for modeling

Paste this entire command into Terminal. It reads the database without changing
it and creates a CSV file you can open in Excel or use in a modeling notebook.
`sqlite3` is the SQLite command-line tool available on this Mac.

```zsh
sqlite3 -readonly -header -csv data/energy.sqlite3 \
  "SELECT * FROM training_observations ORDER BY timestamp_utc, building_id;" \
  > data/modeling_data.csv
```

Open the `data` folder in Finder to find `modeling_data.csv`.
Each row represents one building at one measurement time.
Repeating this command replaces the CSV export with a fresh copy; it does not
replace the database. The export does not update automatically.

## 5. Understand the main columns

| Column | Meaning |
| --- | --- |
| `timestamp_utc` | When demand was measured. All stored times use UTC. |
| `published_at_utc` | When that demand reading became available. |
| `building_id` | Which of the five buildings the row describes. |
| `demand_kw` | Instantaneous electricity demand in kilowatts; the quantity to predict. |
| `temperature_c` | Observed temperature in Celsius, not a future weather forecast. |
| `weather_received_at_utc` | When the observed weather became available to the API. |
| `quality` | The reading's quality label, such as `live` or `stale`. |
| `scorable` | `1` means eligible as an evaluation target; `0` means excluded. |

The export contains measurements, not finished 6-hour or 24-hour training
examples. Feature creation must respect publication times and use earlier dates
for training and later dates for testing. Keep quality flags; do not replace
missing target readings with invented values.

## If something goes wrong

- **“No such file or directory”:** repeat step 1 and check that you opened the
  project folder. If `.venv` is missing, complete step 2.
- **“Database does not exist”:** run `.venv/bin/energy-pipeline init`, then import
  history as described in step 3.
- **Data is older than expected:** collection only runs while a collector is
  running and the computer is awake and connected. An export is a saved snapshot.

Keep analysis outputs separate from the original database. Database files,
exports inside `data/`, and the local key file are excluded from Git.
