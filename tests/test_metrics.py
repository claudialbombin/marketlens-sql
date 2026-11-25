"""Tests for the analytical SQL queries.

Small controlled datasets are inserted into a temporary database. Results
are checked against hand calculations and against independent pandas
calculations.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis import metrics
from database.connection import get_connection, initialize_database

FULL_RANGE = ("1900-01-01", "2100-12-31")


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    """Provide an initialised, empty-prices database."""
    conn = get_connection(tmp_path / "test.db")
    initialize_database(conn)
    yield conn
    conn.close()


def insert_series(conn: sqlite3.Connection, ticker: str, prices: pd.Series) -> None:
    """Store a date-indexed series of adjusted closes for a seeded ticker."""
    asset_id = conn.execute("SELECT asset_id FROM assets WHERE ticker = ?", (ticker,)).fetchone()[0]
    rows = [
        (asset_id, date, price, price, price, price, price, 1000)
        for date, price in prices.items()
    ]
    with conn:
        conn.executemany(
            """
            INSERT INTO daily_prices
                (asset_id, date, open, high, low, close, adjusted_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def random_walk(dates: pd.DatetimeIndex, seed: int) -> pd.Series:
    """Generate a reproducible price path indexed by YYYY-MM-DD strings."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0005, 0.02, len(dates))
    prices = 100 * np.cumprod(1 + returns)
    return pd.Series(prices, index=dates.strftime("%Y-%m-%d"))


# --- daily returns -------------------------------------------------------


def test_daily_returns_match_hand_calculation(connection):
    insert_series(
        connection, "AAPL", pd.Series([100.0, 110.0, 99.0], index=["2024-01-02", "2024-01-03", "2024-01-04"])
    )

    returns = metrics.load_daily_returns(connection, *FULL_RANGE)

    assert returns["date"].tolist() == ["2024-01-03", "2024-01-04"]
    assert returns["daily_return"].tolist() == pytest.approx([0.10, -0.10])


def test_first_return_in_period_uses_price_before_start(connection):
    insert_series(
        connection, "AAPL", pd.Series([100.0, 110.0, 121.0], index=["2024-01-02", "2024-01-03", "2024-01-04"])
    )

    returns = metrics.load_daily_returns(connection, "2024-01-03", "2024-01-04")

    assert returns["daily_return"].tolist() == pytest.approx([0.10, 0.10])


# --- cumulative returns --------------------------------------------------


def test_cumulative_return_starts_at_zero_on_period_start(connection):
    insert_series(
        connection,
        "AAPL",
        pd.Series([50.0, 100.0, 110.0, 99.0], index=["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
    )

    cumulative = metrics.load_cumulative_returns(connection, "2024-01-02", "2024-01-04")

    assert cumulative["cumulative_return"].tolist() == pytest.approx([0.0, 0.10, -0.01])


def test_cumulative_return_equals_compounded_daily_returns(connection):
    prices = random_walk(pd.bdate_range("2024-01-01", periods=50), seed=1)
    insert_series(connection, "AAPL", prices)

    cumulative = metrics.load_cumulative_returns(connection, *FULL_RANGE)
    compounded = (1 + prices.pct_change().fillna(0)).cumprod() - 1

    assert cumulative["cumulative_return"].to_numpy() == pytest.approx(compounded.to_numpy())


# --- rolling volatility --------------------------------------------------


@pytest.mark.parametrize("ticker, periods_per_year", [("AAPL", 252), ("BTC-USD", 365)])
def test_rolling_volatility_matches_pandas(connection, ticker, periods_per_year):
    prices = random_walk(pd.date_range("2024-01-01", periods=120), seed=2)
    insert_series(connection, ticker, prices)

    volatility = metrics.load_rolling_volatility(connection, *FULL_RANGE)
    returns = prices.pct_change().dropna()
    expected_20 = returns.rolling(20).std() * np.sqrt(periods_per_year)
    expected_60 = returns.rolling(60).std() * np.sqrt(periods_per_year)

    np.testing.assert_allclose(volatility["volatility_20d"], expected_20.to_numpy(), rtol=1e-9)
    np.testing.assert_allclose(volatility["volatility_60d"], expected_60.to_numpy(), rtol=1e-9)


def test_volatility_is_null_until_window_is_full(connection):
    prices = random_walk(pd.bdate_range("2024-01-01", periods=30), seed=3)
    insert_series(connection, "AAPL", prices)

    volatility = metrics.load_rolling_volatility(connection, *FULL_RANGE)

    # 29 returns: the 20-day value first appears on the 20th return.
    assert volatility["volatility_20d"].isna().sum() == 19
    assert volatility["volatility_60d"].isna().all()


def test_constant_prices_have_zero_volatility(connection):
    dates = pd.bdate_range("2024-01-01", periods=25).strftime("%Y-%m-%d")
    insert_series(connection, "AAPL", pd.Series(100.0, index=dates))

    volatility = metrics.load_rolling_volatility(connection, *FULL_RANGE)

    assert volatility["volatility_20d"].dropna().tolist() == pytest.approx([0.0] * 5)


# --- correlations --------------------------------------------------------


def test_correlation_between_equities_matches_pandas(connection):
    dates = pd.bdate_range("2024-01-01", periods=80)
    aapl = random_walk(dates, seed=4)
    jpm = random_walk(dates, seed=5)
    insert_series(connection, "AAPL", aapl)
    insert_series(connection, "JPM", jpm)

    pairs = metrics.load_correlation_pairs(connection, *FULL_RANGE)
    expected = aapl.pct_change().corr(jpm.pct_change())

    assert len(pairs) == 1
    assert pairs.loc[0, "observations"] == 79
    assert pairs.loc[0, "correlation"] == pytest.approx(expected)


def test_correlation_with_crypto_uses_common_dates_only(connection):
    calendar_days = pd.date_range("2024-01-01", periods=100)
    business_days = pd.bdate_range("2024-01-01", "2024-04-09")
    btc = random_walk(calendar_days, seed=6)
    aapl = random_walk(business_days, seed=7)
    insert_series(connection, "BTC-USD", btc)
    insert_series(connection, "AAPL", aapl)

    pairs = metrics.load_correlation_pairs(connection, *FULL_RANGE)

    # Independent calculation: align prices on common dates first, then
    # compute returns, so weekend crypto moves are folded into Monday.
    aligned = pd.concat([aapl, btc], axis=1, join="inner").pct_change().dropna()
    assert pairs.loc[0, "observations"] == len(aligned)
    assert pairs.loc[0, "correlation"] == pytest.approx(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))


def test_perfectly_correlated_series(connection):
    dates = pd.bdate_range("2024-01-01", periods=30)
    prices = random_walk(dates, seed=8)
    insert_series(connection, "AAPL", prices)
    insert_series(connection, "JPM", prices * 3)

    pairs = metrics.load_correlation_pairs(connection, *FULL_RANGE)

    assert pairs.loc[0, "correlation"] == pytest.approx(1.0)


def test_constant_series_has_null_correlation(connection):
    dates = pd.bdate_range("2024-01-01", periods=30)
    insert_series(connection, "AAPL", random_walk(dates, seed=9))
    insert_series(connection, "JPM", pd.Series(100.0, index=dates.strftime("%Y-%m-%d")))

    pairs = metrics.load_correlation_pairs(connection, *FULL_RANGE)

    assert pd.isna(pairs.loc[0, "correlation"])


def test_correlation_matrix_is_symmetric_with_unit_diagonal(connection):
    dates = pd.bdate_range("2024-01-01", periods=40)
    for seed, ticker in enumerate(["AAPL", "JPM", "XOM"]):
        insert_series(connection, ticker, random_walk(dates, seed=seed))

    matrix = metrics.to_correlation_matrix(metrics.load_correlation_pairs(connection, *FULL_RANGE))

    assert list(matrix.index) == ["AAPL", "JPM", "XOM"]
    np.testing.assert_allclose(matrix.to_numpy(), matrix.to_numpy().T)
    np.testing.assert_allclose(np.diag(matrix.to_numpy()), 1.0)


# --- maximum drawdown ----------------------------------------------------


def test_maximum_drawdown_matches_hand_calculation(connection):
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    insert_series(connection, "AAPL", pd.Series([100.0, 120.0, 90.0, 130.0, 117.0], index=dates))

    drawdown = metrics.load_maximum_drawdown(connection, *FULL_RANGE)

    # Worst fall: 120 -> 90 = -25%. The later 130 -> 117 is only -10%.
    assert drawdown.loc[0, "maximum_drawdown"] == pytest.approx(-0.25)
    assert drawdown.loc[0, "peak_date"] == "2024-01-02"
    assert drawdown.loc[0, "trough_date"] == "2024-01-03"


def test_maximum_drawdown_matches_pandas(connection):
    prices = random_walk(pd.bdate_range("2024-01-01", periods=200), seed=10)
    insert_series(connection, "AAPL", prices)

    drawdown = metrics.load_maximum_drawdown(connection, *FULL_RANGE)
    expected = (prices / prices.cummax() - 1).min()

    assert drawdown.loc[0, "maximum_drawdown"] == pytest.approx(expected)


def test_drawdown_peak_is_limited_to_selected_period(connection):
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
    insert_series(connection, "AAPL", pd.Series([200.0, 100.0, 110.0, 99.0], index=dates))

    drawdown = metrics.load_maximum_drawdown(connection, "2024-01-02", "2024-01-04")

    # The 200 peak is outside the period; the worst fall inside it is 110 -> 99.
    assert drawdown.loc[0, "maximum_drawdown"] == pytest.approx(-0.10)
    assert drawdown.loc[0, "peak_date"] == "2024-01-03"


def test_rising_prices_have_zero_drawdown(connection):
    dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    insert_series(connection, "AAPL", pd.Series([100.0, 101.0, 102.0], index=dates))

    drawdown = metrics.load_maximum_drawdown(connection, *FULL_RANGE)

    assert drawdown.loc[0, "maximum_drawdown"] == pytest.approx(0.0)


# --- dashboard support queries -------------------------------------------


@pytest.mark.parametrize("ticker, periods_per_year", [("AAPL", 252), ("BTC-USD", 365)])
def test_risk_profile_matches_pandas(connection, ticker, periods_per_year):
    prices = random_walk(pd.date_range("2024-01-01", periods=100), seed=11)
    insert_series(connection, ticker, prices)

    profile = metrics.run_query(connection, "risk_profile", *FULL_RANGE).iloc[0]
    returns = prices.pct_change().dropna()
    total_return = prices.iloc[-1] / prices.iloc[0] - 1

    assert profile["observations"] == len(returns)
    assert profile["total_return"] == pytest.approx(total_return)
    assert profile["annualised_return"] == pytest.approx(
        (1 + total_return) ** (periods_per_year / len(returns)) - 1
    )
    assert profile["annualised_volatility"] == pytest.approx(returns.std() * np.sqrt(periods_per_year))


def test_asset_overview_uses_last_price_on_or_before_end_date(connection):
    dates = ["2024-01-04", "2024-01-05", "2024-01-08"]
    insert_series(connection, "AAPL", pd.Series([100.0, 102.0, 110.0], index=dates))

    # 2024-01-06 is a Saturday: the latest observation is Friday 2024-01-05.
    overview = metrics.run_query(connection, "asset_overview", "2024-01-01", "2024-01-06")
    aapl = overview.set_index("ticker").loc["AAPL"]

    assert aapl["latest_date"] == "2024-01-05"
    assert aapl["latest_daily_change"] == pytest.approx(0.02)
    assert aapl["last_date"] == "2024-01-08"
    assert pd.isna(overview.set_index("ticker").loc["JPM", "latest_date"])
