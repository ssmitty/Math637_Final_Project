"""Commands for local database initialization, import, and inspection."""

import argparse
import logging
from pathlib import Path
import sqlite3

from database.storage import initialize, summary
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
        else:
            for key, value in summary(args.database).items():
                LOGGER.info("%s: %s", key, value)
    except (OSError, ValueError, sqlite3.Error) as error:
        LOGGER.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
