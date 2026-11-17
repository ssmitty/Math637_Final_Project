"""Commands for local database initialization, import, and inspection."""

import argparse
import logging
import os
from pathlib import Path
import sqlite3

from database.collection import collection_summary
from database.storage import connect, initialize, summary
from energy_pipeline.api import ApiClient, ApiError
from energy_pipeline.collector import run_collection
from energy_pipeline.history import import_history

LOGGER = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, default=Path("data/energy.sqlite3"),
        help="Database path (default: data/energy.sqlite3 relative to current folder)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create database and apply pending migrations")
    importer = commands.add_parser(
        "import-history", help="Import historical CSV or JSON"
    )
    importer.add_argument("source", type=Path)
    commands.add_parser("status", help="Show stored coverage and record counts")
    collector = commands.add_parser("collect", help="Collect demand and weather data")
    collector.add_argument("--loop", action="store_true", help="Poll until stopped")
    collector.add_argument("--interval", type=float, default=900,
                           help="Seconds between cycles (default: 900; minimum: 60)")
    collector.add_argument("--max-pages", type=int, default=100,
                           help="Maximum demand pages per cycle (default: 100)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.command == "init":
            initialize(args.database)
            LOGGER.info("Database ready: %s", args.database.resolve())
        elif args.command == "import-history":
            result = import_history(args.source, args.database)
            LOGGER.info(
                "Imported %s timestamps; %s new, %s already stored",
                result.timestamps, result.inserted, result.duplicates,
            )
        elif args.command == "collect":
            client = ApiClient(os.environ.get("ENERGY_API_KEY", ""))
            run_collection(
                args.database, client, loop=args.loop,
                interval=args.interval, max_pages=args.max_pages,
            )
        else:
            result = summary(args.database)
            with connect(args.database) as connection:
                result.update(collection_summary(connection))
            for key, value in result.items():
                LOGGER.info("%s: %s", key, value)
    except (OSError, ValueError, sqlite3.Error, ApiError) as error:
        LOGGER.error("%s", error)
        return 1
    except KeyboardInterrupt:
        LOGGER.info("Collection stopped; saved pages will resume next time")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
