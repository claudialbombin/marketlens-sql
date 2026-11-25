"""Validation of downloaded prices before they are written to the database.

The rules mirror the CHECK constraints in database/schema.sql. Checking them
here first means one bad row is logged and dropped instead of making the
whole insert transaction fail.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

PRICE_COLUMNS = ["open", "high", "low", "close", "adjusted_close"]


def find_invalid_rows(prices: pd.DataFrame) -> pd.Series:
    """Label each row with the first rule it breaks.

    Args:
        prices: DataFrame in the daily_prices layout produced by
            ingestion.market_data.to_price_table().

    Returns:
        Series aligned with prices, holding a short reason for invalid rows
        and None for valid ones.
    """
    reasons = pd.Series(None, index=prices.index, dtype=object)

    # Checked in order of severity; a row keeps only its first reason.
    rules = [
        ("missing price", prices[PRICE_COLUMNS].isna().any(axis=1)),
        ("non-positive price", (prices[PRICE_COLUMNS] <= 0).any(axis=1)),
        (
            "low/high inconsistent with open/close",
            (prices["low"] > prices[["open", "close"]].min(axis=1))
            | (prices["high"] < prices[["open", "close"]].max(axis=1)),
        ),
        ("negative volume", prices["volume"] < 0),
        ("duplicate date", prices["date"].duplicated(keep=False)),
    ]
    for reason, is_broken in rules:
        reasons[is_broken & reasons.isna()] = reason
    return reasons


def validate_prices(prices: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Drop invalid rows and log how many were rejected and why.

    Invalid rows are rejected rather than corrected: guessing a missing or
    inconsistent price would introduce data the provider never reported.

    Args:
        prices: DataFrame in the daily_prices layout.
        ticker: Ticker the data belongs to, used in log messages.

    Returns:
        A copy of prices containing only valid rows.
    """
    reasons = find_invalid_rows(prices)
    rejected = reasons.notna()

    for reason, count in reasons[rejected].value_counts().items():
        logger.warning("%s: rejected %d rows (%s)", ticker, count, reason)

    return prices[~rejected].reset_index(drop=True)
