"""Download missing daily prices for every asset and store them in SQLite.

Usage:
    python -m ingestion.update_database

For each asset in the assets table:
    - No stored prices: download the full history from HISTORY_START_DATE.
    - Stored prices: re-download from the last OVERLAP_OBSERVATIONS stored
      dates onward. If adjusted_close on those overlapping dates still
      matches, only the new dates are appended. If it changed (a dividend or
      split made Yahoo recalculate the adjusted history), the asset's full
      history is reloaded.

A failure for one asset is logged and the run continues with the next one.
"""

import logging
import sqlite3
import time

import pandas as pd

from config import settings
from database.connection import get_connection, initialize_database
from ingestion.data_validation import validate_prices
from ingestion.market_data import MarketDataError, download_daily_prices

logger = logging.getLogger(__name__)

INSERT_PRICES_SQL = """
    INSERT INTO daily_prices
        (asset_id, date, open, high, low, close, adjusted_close, volume)
    VALUES
        (:asset_id, :date, :open, :high, :low, :close, :adjusted_close, :volume)
"""


def load_assets(connection: sqlite3.Connection) -> list[tuple[int, str]]:
    """Return (asset_id, ticker) for every asset, ordered by asset_id."""
    rows = connection.execute("SELECT asset_id, ticker FROM assets ORDER BY asset_id")
    return rows.fetchall()


def load_overlap_window(connection: sqlite3.Connection, asset_id: int) -> pd.DataFrame:
    """Return the most recent stored dates and adjusted closes of one asset.

    Args:
        connection: Open database connection.
        asset_id: Asset to look up.

    Returns:
        DataFrame with columns date and adjusted_close, oldest first. Empty
        if the asset has no stored prices.
    """
    return pd.read_sql_query(
        """
        SELECT date, adjusted_close
        FROM (
            SELECT date, adjusted_close
            FROM daily_prices
            WHERE asset_id = :asset_id
            ORDER BY date DESC
            LIMIT :limit
        )
        ORDER BY date
        """,
        connection,
        params={"asset_id": asset_id, "limit": settings.OVERLAP_OBSERVATIONS},
    )


def adjustments_changed(stored: pd.DataFrame, downloaded: pd.DataFrame) -> bool:
    """Check whether the provider changed adjusted prices that are already stored.

    Args:
        stored: Stored date and adjusted_close values (the overlap window).
        downloaded: Freshly downloaded prices covering at least those dates.

    Returns:
        True if any stored date is missing from the download or its
        adjusted_close differs by more than ADJUSTMENT_TOLERANCE (relative).
    """
    merged = stored.merge(
        downloaded[["date", "adjusted_close"]],
        on="date",
        how="left",
        suffixes=("_stored", "_downloaded"),
    )
    if merged["adjusted_close_downloaded"].isna().any():
        return True

    relative_difference = (
        merged["adjusted_close_downloaded"] / merged["adjusted_close_stored"] - 1
    ).abs()
    return bool((relative_difference > settings.ADJUSTMENT_TOLERANCE).any())


def to_records(prices: pd.DataFrame, asset_id: int) -> list[dict]:
    """Convert validated prices to parameter dictionaries for executemany().

    Missing volume becomes None so that it is stored as NULL, not NaN.
    """
    rows = prices.astype(object).where(prices.notna(), None)
    records = rows.to_dict(orient="records")
    for record in records:
        record["asset_id"] = asset_id
        if record["volume"] is not None:
            record["volume"] = int(record["volume"])
    return records


def replace_history(connection: sqlite3.Connection, asset_id: int, prices: pd.DataFrame) -> None:
    """Replace every stored price of one asset in a single transaction."""
    with connection:
        connection.execute("DELETE FROM daily_prices WHERE asset_id = ?", (asset_id,))
        connection.executemany(INSERT_PRICES_SQL, to_records(prices, asset_id))


def append_prices(connection: sqlite3.Connection, asset_id: int, prices: pd.DataFrame) -> None:
    """Insert new prices of one asset in a single transaction.

    The (asset_id, date) primary key makes the insert fail rather than store
    a duplicate if a date is already present.
    """
    with connection:
        connection.executemany(INSERT_PRICES_SQL, to_records(prices, asset_id))


def update_asset(connection: sqlite3.Connection, asset_id: int, ticker: str) -> None:
    """Bring the stored history of one asset up to date.

    Args:
        connection: Open database connection.
        asset_id: Asset to update.
        ticker: Yahoo Finance symbol of the asset.

    Raises:
        MarketDataError: If the download fails after all retries.
    """
    stored = load_overlap_window(connection, asset_id)

    if stored.empty:
        prices = validate_prices(download_daily_prices(ticker, settings.HISTORY_START_DATE), ticker)
        if prices.empty:
            logger.warning("%s: no data returned, nothing stored", ticker)
            return
        replace_history(connection, asset_id, prices)
        logger.info("%s: initial load of %d rows", ticker, len(prices))
        return

    prices = validate_prices(download_daily_prices(ticker, stored["date"].iloc[0]), ticker)
    if prices.empty:
        logger.warning("%s: no data returned, stored history left unchanged", ticker)
        return

    if adjustments_changed(stored, prices):
        logger.info("%s: adjusted prices changed, reloading full history", ticker)
        full_history = validate_prices(
            download_daily_prices(ticker, settings.HISTORY_START_DATE), ticker
        )
        if full_history.empty:
            logger.warning("%s: reload returned no data, stored history left unchanged", ticker)
            return
        replace_history(connection, asset_id, full_history)
        logger.info("%s: reloaded %d rows", ticker, len(full_history))
        return

    last_stored_date = stored["date"].iloc[-1]
    new_prices = prices[prices["date"] > last_stored_date]
    if new_prices.empty:
        logger.info("%s: already up to date (%s)", ticker, last_stored_date)
        return
    append_prices(connection, asset_id, new_prices)
    logger.info("%s: appended %d rows up to %s", ticker, len(new_prices), new_prices["date"].iloc[-1])


def update_all_assets(connection: sqlite3.Connection) -> list[str]:
    """Update every asset, continuing after individual failures.

    Args:
        connection: Open database connection.

    Returns:
        Tickers that could not be updated.
    """
    failed_tickers = []
    for asset_id, ticker in load_assets(connection):
        try:
            update_asset(connection, asset_id, ticker)
        except (MarketDataError, sqlite3.Error):
            logger.exception("%s: update failed", ticker)
            failed_tickers.append(ticker)
        time.sleep(settings.REQUEST_PAUSE_SECONDS)
    return failed_tickers


def main() -> None:
    """Initialise the database if needed and update all assets."""
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    connection = get_connection()
    try:
        initialize_database(connection)
        failed_tickers = update_all_assets(connection)
    finally:
        connection.close()

    if failed_tickers:
        logger.error("Finished with failures: %s", ", ".join(failed_tickers))
        raise SystemExit(1)
    logger.info("All assets up to date")


if __name__ == "__main__":
    main()
