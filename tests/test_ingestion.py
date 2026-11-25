"""Tests for downloading, validating and storing market data.

The Yahoo Finance API is never called: downloads are replaced with small
synthetic DataFrames so results are reproducible.
"""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from config import settings
from database.connection import get_connection, initialize_database
from ingestion import market_data, update_database
from ingestion.data_validation import find_invalid_rows, validate_prices


def make_prices(dates: list[str], adjusted_closes: list[float]) -> pd.DataFrame:
    """Build a valid price table in the daily_prices layout."""
    return pd.DataFrame(
        {
            "date": dates,
            "open": [100.0] * len(dates),
            "high": [110.0] * len(dates),
            "low": [90.0] * len(dates),
            "close": [105.0] * len(dates),
            "adjusted_close": adjusted_closes,
            "volume": [1000] * len(dates),
        }
    )


def make_yfinance_history(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Build a DataFrame shaped like yfinance Ticker.history(auto_adjust=False)."""
    rows = len(index)
    return pd.DataFrame(
        {
            "Open": [100.0] * rows,
            "High": [110.0] * rows,
            "Low": [90.0] * rows,
            "Close": [105.0] * rows,
            "Adj Close": [104.0] * rows,
            "Volume": [1000] * rows,
        },
        index=index,
    )


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Remove pauses and backoff delays so tests run instantly."""
    monkeypatch.setattr(settings, "REQUEST_PAUSE_SECONDS", 0)
    monkeypatch.setattr(settings, "RETRY_BASE_DELAY_SECONDS", 0)


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    """Provide an initialised database in a temporary directory."""
    conn = get_connection(tmp_path / "test.db")
    initialize_database(conn)
    yield conn
    conn.close()


@pytest.fixture
def fake_provider(monkeypatch):
    """Replace downloads with a dict of ticker -> price table.

    Each call returns the rows on or after the requested start date, like
    the real API. Requested start dates are recorded per ticker.
    """
    data: dict[str, pd.DataFrame] = {}
    requests: dict[str, list[str]] = {}

    def fake_download(ticker: str, start_date: str) -> pd.DataFrame:
        requests.setdefault(ticker, []).append(start_date)
        if ticker not in data:
            return make_prices([], [])
        prices = data[ticker]
        return prices[prices["date"] >= start_date].reset_index(drop=True)

    monkeypatch.setattr(update_database, "download_daily_prices", fake_download)
    return data, requests


def stored_prices(conn: sqlite3.Connection, ticker: str) -> list[tuple[str, float]]:
    """Return (date, adjusted_close) rows stored for a ticker."""
    return conn.execute(
        """
        SELECT p.date, p.adjusted_close
        FROM daily_prices AS p
        JOIN assets AS a ON a.asset_id = p.asset_id
        WHERE a.ticker = ?
        ORDER BY p.date
        """,
        (ticker,),
    ).fetchall()


def get_asset_id(conn: sqlite3.Connection, ticker: str) -> int:
    """Return the asset_id of a seeded ticker."""
    return conn.execute("SELECT asset_id FROM assets WHERE ticker = ?", (ticker,)).fetchone()[0]


# --- market_data ---------------------------------------------------------


def test_equity_dates_keep_exchange_calendar_day():
    # Midnight in New York is 05:00 UTC; the stored date must stay the same day.
    index = pd.DatetimeIndex(["2024-03-01", "2024-03-04"]).tz_localize("America/New_York")
    prices = market_data.to_price_table(make_yfinance_history(index))

    assert prices["date"].tolist() == ["2024-03-01", "2024-03-04"]
    assert list(prices.columns) == [
        "date", "open", "high", "low", "close", "adjusted_close", "volume",
    ]


def test_current_session_is_dropped():
    today = pd.Timestamp.now(tz="UTC").normalize()
    index = pd.DatetimeIndex([today - pd.Timedelta(days=1), today])
    prices = market_data.to_price_table(make_yfinance_history(index))

    assert prices["date"].tolist() == [(today - pd.Timedelta(days=1)).strftime("%Y-%m-%d")]


def test_empty_history_returns_empty_table():
    prices = market_data.to_price_table(pd.DataFrame())

    assert prices.empty
    assert "adjusted_close" in prices.columns


def test_download_retries_transient_errors(monkeypatch):
    calls = []
    index = pd.DatetimeIndex(["2024-03-01"]).tz_localize("UTC")

    class FlakyTicker:
        def __init__(self, ticker):
            pass

        def history(self, **kwargs):
            calls.append(kwargs)
            if len(calls) < 3:
                raise ConnectionError("temporary network failure")
            return make_yfinance_history(index)

    monkeypatch.setattr(market_data.yf, "Ticker", FlakyTicker)
    prices = market_data.download_daily_prices("AAPL", "2024-03-01")

    assert len(calls) == 3
    assert len(prices) == 1
    assert calls[0]["auto_adjust"] is False


def test_download_gives_up_after_max_retries(monkeypatch):
    class BrokenTicker:
        def __init__(self, ticker):
            pass

        def history(self, **kwargs):
            raise ConnectionError("network down")

    monkeypatch.setattr(market_data.yf, "Ticker", BrokenTicker)

    with pytest.raises(market_data.MarketDataError):
        market_data.download_daily_prices("AAPL", "2024-03-01")


# --- data_validation -----------------------------------------------------


def test_valid_rows_pass_validation():
    prices = make_prices(["2024-01-02", "2024-01-03"], [100.0, 101.0])

    assert len(validate_prices(prices, "TEST")) == 2


@pytest.mark.parametrize(
    "column, value, expected_reason",
    [
        ("adjusted_close", None, "missing price"),
        ("close", 0.0, "non-positive price"),
        ("high", 95.0, "low/high inconsistent with open/close"),
        ("low", 106.0, "low/high inconsistent with open/close"),
        ("volume", -1, "negative volume"),
    ],
)
def test_invalid_rows_are_rejected(column, value, expected_reason):
    prices = make_prices(["2024-01-02", "2024-01-03"], [100.0, 101.0])
    prices.loc[1, column] = value

    assert find_invalid_rows(prices)[1] == expected_reason
    assert validate_prices(prices, "TEST")["date"].tolist() == ["2024-01-02"]


def test_duplicate_dates_are_rejected():
    prices = make_prices(["2024-01-02", "2024-01-02", "2024-01-03"], [100.0, 100.5, 101.0])

    assert validate_prices(prices, "TEST")["date"].tolist() == ["2024-01-03"]


def test_missing_volume_is_valid():
    prices = make_prices(["2024-01-02"], [100.0])
    prices["volume"] = [None]

    assert len(validate_prices(prices, "TEST")) == 1


# --- update_database -----------------------------------------------------


def test_initial_load_stores_full_history(connection, fake_provider):
    data, requests = fake_provider
    data["AAPL"] = make_prices(["2024-01-02", "2024-01-03"], [100.0, 101.0])

    update_database.update_asset(connection, get_asset_id(connection, "AAPL"), "AAPL")

    assert stored_prices(connection, "AAPL") == [("2024-01-02", 100.0), ("2024-01-03", 101.0)]
    assert requests["AAPL"] == [settings.HISTORY_START_DATE]


def test_rerun_without_new_data_creates_no_duplicates(connection, fake_provider):
    data, _ = fake_provider
    data["AAPL"] = make_prices(["2024-01-02", "2024-01-03"], [100.0, 101.0])
    asset_id = get_asset_id(connection, "AAPL")

    update_database.update_asset(connection, asset_id, "AAPL")
    update_database.update_asset(connection, asset_id, "AAPL")

    assert len(stored_prices(connection, "AAPL")) == 2


def test_incremental_update_only_requests_overlap_and_appends_new_dates(
    connection, fake_provider, monkeypatch
):
    monkeypatch.setattr(settings, "OVERLAP_OBSERVATIONS", 2)
    data, requests = fake_provider
    asset_id = get_asset_id(connection, "AAPL")

    data["AAPL"] = make_prices(["2024-01-02", "2024-01-03", "2024-01-04"], [100.0, 101.0, 102.0])
    update_database.update_asset(connection, asset_id, "AAPL")

    data["AAPL"] = make_prices(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], [100.0, 101.0, 102.0, 103.0]
    )
    update_database.update_asset(connection, asset_id, "AAPL")

    # The second request starts at the oldest date of the 2-row overlap window.
    assert requests["AAPL"] == [settings.HISTORY_START_DATE, "2024-01-03"]
    assert stored_prices(connection, "AAPL")[-1] == ("2024-01-05", 103.0)
    assert len(stored_prices(connection, "AAPL")) == 4


def test_changed_adjusted_prices_trigger_full_reload(connection, fake_provider):
    data, requests = fake_provider
    asset_id = get_asset_id(connection, "AAPL")

    data["AAPL"] = make_prices(["2024-01-02", "2024-01-03"], [100.0, 101.0])
    update_database.update_asset(connection, asset_id, "AAPL")

    # A dividend makes Yahoo scale the whole adjusted history down by 1%.
    data["AAPL"] = make_prices(["2024-01-02", "2024-01-03", "2024-01-04"], [99.0, 99.99, 102.0])
    update_database.update_asset(connection, asset_id, "AAPL")

    assert stored_prices(connection, "AAPL") == [
        ("2024-01-02", 99.0),
        ("2024-01-03", 99.99),
        ("2024-01-04", 102.0),
    ]
    assert requests["AAPL"][-1] == settings.HISTORY_START_DATE


def test_rounding_noise_does_not_trigger_reload(connection, fake_provider):
    data, requests = fake_provider
    asset_id = get_asset_id(connection, "AAPL")

    data["AAPL"] = make_prices(["2024-01-02", "2024-01-03"], [100.0, 101.0])
    update_database.update_asset(connection, asset_id, "AAPL")

    data["AAPL"] = make_prices(
        ["2024-01-02", "2024-01-03", "2024-01-04"], [100.000001, 101.0, 102.0]
    )
    update_database.update_asset(connection, asset_id, "AAPL")

    assert len(requests["AAPL"]) == 2
    assert stored_prices(connection, "AAPL")[0] == ("2024-01-02", 100.0)


def test_empty_download_leaves_existing_history_untouched(connection, fake_provider):
    data, _ = fake_provider
    asset_id = get_asset_id(connection, "AAPL")

    data["AAPL"] = make_prices(["2024-01-02"], [100.0])
    update_database.update_asset(connection, asset_id, "AAPL")
    del data["AAPL"]
    update_database.update_asset(connection, asset_id, "AAPL")

    assert stored_prices(connection, "AAPL") == [("2024-01-02", 100.0)]


def test_missing_volume_is_stored_as_null(connection, fake_provider):
    data, _ = fake_provider
    prices = make_prices(["2024-01-02"], [100.0])
    prices["volume"] = [None]
    data["^GSPC"] = prices

    update_database.update_asset(connection, get_asset_id(connection, "^GSPC"), "^GSPC")

    assert connection.execute("SELECT volume FROM daily_prices").fetchone()[0] is None


def test_one_failing_asset_does_not_stop_the_others(connection, monkeypatch):
    def fake_download(ticker: str, start_date: str) -> pd.DataFrame:
        if ticker == "AAPL":
            raise market_data.MarketDataError("AAPL: download failed")
        return make_prices(["2024-01-02"], [100.0])

    monkeypatch.setattr(update_database, "download_daily_prices", fake_download)

    failed = update_database.update_all_assets(connection)

    assert failed == ["AAPL"]
    stored_assets = connection.execute(
        "SELECT COUNT(DISTINCT asset_id) FROM daily_prices"
    ).fetchone()[0]
    assert stored_assets == 6
