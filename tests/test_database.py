"""Tests for the database schema, constraints and initialisation."""

import sqlite3
from pathlib import Path

import pytest

from database import connection as db

SEEDED_TICKERS = {"^GSPC", "AAPL", "JPM", "XOM", "JNJ", "BTC-USD", "ETH-USD"}

VALID_PRICE = {
    "date": "2024-01-02",
    "open": 100.0,
    "high": 105.0,
    "low": 99.0,
    "close": 104.0,
    "adjusted_close": 103.5,
    "volume": 1_000_000,
}


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    """Provide an initialised database in a temporary directory."""
    conn = db.get_connection(tmp_path / "test.db")
    db.initialize_database(conn)
    yield conn
    conn.close()


def get_asset_id(conn: sqlite3.Connection, ticker: str) -> int:
    """Return the asset_id of a seeded ticker."""
    row = conn.execute("SELECT asset_id FROM assets WHERE ticker = ?", (ticker,))
    return row.fetchone()[0]


def insert_price(conn: sqlite3.Connection, asset_id: int, **overrides) -> None:
    """Insert one daily_prices row, starting from VALID_PRICE."""
    values = {**VALID_PRICE, **overrides}
    conn.execute(
        """
        INSERT INTO daily_prices
            (asset_id, date, open, high, low, close, adjusted_close, volume)
        VALUES
            (:asset_id, :date, :open, :high, :low, :close, :adjusted_close, :volume)
        """,
        {"asset_id": asset_id, **values},
    )


def test_initialisation_creates_tables_and_seeds_assets(connection):
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"assets", "daily_prices"} <= tables

    tickers = {row[0] for row in connection.execute("SELECT ticker FROM assets")}
    assert tickers == SEEDED_TICKERS


def test_initialisation_is_idempotent(connection):
    ids_before = dict(connection.execute("SELECT ticker, asset_id FROM assets"))

    db.initialize_database(connection)

    ids_after = dict(connection.execute("SELECT ticker, asset_id FROM assets"))
    assert ids_after == ids_before


def test_foreign_keys_are_enforced(connection):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_price(connection, asset_id=9999)


def test_duplicate_observation_is_rejected(connection):
    asset_id = get_asset_id(connection, "AAPL")
    insert_price(connection, asset_id)

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insert_price(connection, asset_id)


def test_same_date_for_different_assets_is_allowed(connection):
    insert_price(connection, get_asset_id(connection, "AAPL"))
    insert_price(connection, get_asset_id(connection, "JPM"))

    count = connection.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    assert count == 2


def test_asset_with_prices_cannot_be_deleted(connection):
    asset_id = get_asset_id(connection, "AAPL")
    insert_price(connection, asset_id)

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        connection.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))


@pytest.mark.parametrize("bad_date", ["2024/01/02", "2024-1-2", "2024-02-30", "not a date"])
def test_invalid_dates_are_rejected(connection, bad_date):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert_price(connection, get_asset_id(connection, "AAPL"), date=bad_date)


@pytest.mark.parametrize(
    "overrides",
    [
        {"adjusted_close": 0.0},
        {"close": -1.0},
        {"volume": -5},
        {"high": 98.0},  # below low
        {"low": 104.5},  # above close
    ],
)
def test_inconsistent_prices_are_rejected(connection, overrides):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert_price(connection, get_asset_id(connection, "AAPL"), **overrides)


def test_missing_adjusted_close_is_rejected(connection):
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        insert_price(connection, get_asset_id(connection, "AAPL"), adjusted_close=None)


def test_missing_volume_is_allowed(connection):
    insert_price(connection, get_asset_id(connection, "^GSPC"), volume=None)

    volume = connection.execute("SELECT volume FROM daily_prices").fetchone()[0]
    assert volume is None


def test_strict_typing_rejects_text_prices(connection):
    with pytest.raises(sqlite3.IntegrityError):
        insert_price(connection, get_asset_id(connection, "AAPL"), close="abc")


def test_invalid_asset_type_is_rejected(connection):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        connection.execute(
            "INSERT INTO assets (ticker, name, asset_type, currency) VALUES (?, ?, ?, ?)",
            ("GLD", "Gold ETF", "commodity", "USD"),
        )


def test_failed_initialisation_rolls_back(tmp_path, monkeypatch):
    broken_seed = tmp_path / "broken_seed.sql"
    broken_seed.write_text("INSERT INTO missing_table VALUES (1);")
    monkeypatch.setattr(db, "SEED_ASSETS_PATH", broken_seed)

    conn = db.get_connection(tmp_path / "test.db")
    with pytest.raises(sqlite3.OperationalError):
        db.initialize_database(conn)

    tables = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    conn.close()
    assert tables == []
