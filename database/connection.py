"""SQLite connection handling and database initialisation."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DATABASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DATABASE_DIR / "schema.sql"
SEED_ASSETS_PATH = DATABASE_DIR / "seed_assets.sql"
DEFAULT_DATABASE_PATH = DATABASE_DIR.parent / "data" / "marketlens.db"

# STRICT tables need 3.37; SQRT() for volatility needs 3.35.
MINIMUM_SQLITE_VERSION = (3, 37, 0)


def get_connection(database_path: Path = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with foreign key enforcement enabled.

    Args:
        database_path: Location of the database file. It is created if it
            does not exist yet.

    Returns:
        An open connection. The caller is responsible for closing it.

    Raises:
        RuntimeError: If the SQLite library bundled with Python is too old.
    """
    if sqlite3.sqlite_version_info < MINIMUM_SQLITE_VERSION:
        required = ".".join(str(part) for part in MINIMUM_SQLITE_VERSION)
        raise RuntimeError(
            f"SQLite {required}+ is required, found {sqlite3.sqlite_version}."
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    # SQLite does not enforce foreign keys unless this is set on every
    # connection; it cannot be stored in the schema file.
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create the schema and load the asset universe in one transaction.

    Safe to run repeatedly: tables are created only if missing and the seed
    updates existing assets instead of duplicating them.

    Args:
        connection: Open connection returned by get_connection().

    Raises:
        sqlite3.Error: If any statement fails. Nothing is applied in that case.
    """
    script = SCHEMA_PATH.read_text() + "\n" + SEED_ASSETS_PATH.read_text()

    # executescript() runs each statement in autocommit mode by default, so
    # an explicit BEGIN/COMMIT is needed to make the whole script atomic.
    try:
        connection.executescript(f"BEGIN;\n{script}\nCOMMIT;")
    except sqlite3.Error:
        connection.rollback()
        logger.exception("Database initialisation failed; changes rolled back")
        raise

    asset_count = connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    logger.info("Database initialised with %d assets", asset_count)
