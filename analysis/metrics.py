"""Access layer for the analytical SQL queries.

Every calculation lives in database/queries/*.sql. The functions here only
run those files with bound date parameters and return DataFrames for the
dashboard, the site export and the tests.
"""

import sqlite3
from pathlib import Path

import pandas as pd

QUERIES_DIR = Path(__file__).resolve().parent.parent / "database" / "queries"


def run_query(
    connection: sqlite3.Connection, query_name: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """Execute a query file from database/queries with a date range.

    Args:
        connection: Open database connection.
        query_name: File name without the .sql extension.
        start_date: First date of the period, YYYY-MM-DD (inclusive).
        end_date: Last date of the period, YYYY-MM-DD (inclusive).

    Returns:
        Query result as a DataFrame.
    """
    sql = (QUERIES_DIR / f"{query_name}.sql").read_text()
    return pd.read_sql_query(
        sql, connection, params={"start_date": start_date, "end_date": end_date}
    )


def load_daily_returns(
    connection: sqlite3.Connection, start_date: str, end_date: str
) -> pd.DataFrame:
    """Daily returns per asset. Columns: ticker, date, daily_return."""
    return run_query(connection, "daily_returns", start_date, end_date)


def load_cumulative_returns(
    connection: sqlite3.Connection, start_date: str, end_date: str
) -> pd.DataFrame:
    """Cumulative return since the period start. Columns: ticker, date, cumulative_return."""
    return run_query(connection, "cumulative_returns", start_date, end_date)


def load_rolling_volatility(
    connection: sqlite3.Connection, start_date: str, end_date: str
) -> pd.DataFrame:
    """Annualised 20- and 60-observation volatility.

    Columns: ticker, date, volatility_20d, volatility_60d.
    """
    return run_query(connection, "rolling_volatility", start_date, end_date)


def load_maximum_drawdown(
    connection: sqlite3.Connection, start_date: str, end_date: str
) -> pd.DataFrame:
    """Maximum drawdown per asset.

    Columns: ticker, maximum_drawdown, peak_date, trough_date.
    """
    return run_query(connection, "maximum_drawdown", start_date, end_date)


def load_correlation_pairs(
    connection: sqlite3.Connection, start_date: str, end_date: str
) -> pd.DataFrame:
    """Correlation for each pair of assets, once per pair.

    Columns: ticker_x, ticker_y, observations, correlation.
    """
    return run_query(connection, "correlations", start_date, end_date)


def to_correlation_matrix(pairs: pd.DataFrame) -> pd.DataFrame:
    """Reshape correlation pairs into a symmetric matrix for the heatmap.

    This only rearranges values already computed in SQL: each pair is
    mirrored and the diagonal is set to 1.

    Args:
        pairs: Output of load_correlation_pairs().

    Returns:
        Square DataFrame indexed and labelled by ticker.
    """
    mirrored = pairs.rename(columns={"ticker_x": "ticker_y", "ticker_y": "ticker_x"})
    both_directions = pd.concat([pairs, mirrored], ignore_index=True)
    matrix = both_directions.pivot(index="ticker_x", columns="ticker_y", values="correlation")

    tickers = sorted(set(matrix.index) | set(matrix.columns))
    matrix = matrix.reindex(index=tickers, columns=tickers)
    for ticker in tickers:
        matrix.loc[ticker, ticker] = 1.0
    matrix.index.name = None
    matrix.columns.name = None
    return matrix
