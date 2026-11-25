"""Historical daily price download from Yahoo Finance through yfinance."""

import logging
import time

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from config import settings

logger = logging.getLogger(__name__)

# Mapping from yfinance column names to the daily_prices schema.
COLUMN_NAMES = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adjusted_close",
    "Volume": "volume",
}

# Rate limits and network failures (curl_cffi errors subclass OSError) are
# transient and worth retrying. An unknown ticker is not: yfinance returns an
# empty DataFrame for it, which is handled by the caller.
RETRYABLE_ERRORS = (YFRateLimitError, OSError)


class MarketDataError(Exception):
    """Raised when a ticker cannot be downloaded after all retries."""


def download_daily_prices(ticker: str, start_date: str) -> pd.DataFrame:
    """Download daily OHLCV data for one ticker, retrying transient failures.

    Args:
        ticker: Yahoo Finance symbol, e.g. "AAPL" or "BTC-USD".
        start_date: First date to request, in YYYY-MM-DD format.

    Returns:
        DataFrame with columns date, open, high, low, close, adjusted_close
        and volume. Empty if the provider returned no data.

    Raises:
        MarketDataError: If every attempt fails with a transient error.
    """
    attempt = 1
    while True:
        try:
            # auto_adjust=False keeps raw OHLC and returns "Adj Close"
            # separately; the default would overwrite OHLC with adjusted values.
            history = yf.Ticker(ticker).history(
                start=start_date, interval="1d", auto_adjust=False, actions=False
            )
            return to_price_table(history)
        except RETRYABLE_ERRORS as error:
            if attempt >= settings.MAX_RETRIES:
                raise MarketDataError(
                    f"{ticker}: download failed after {attempt} attempts"
                ) from error
            # Exponential backoff: 2s, 4s, 8s, ... with the default settings.
            delay = settings.RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1)
            logger.warning(
                "%s: attempt %d failed (%s), retrying in %.0fs", ticker, attempt, error, delay
            )
            time.sleep(delay)
            attempt += 1


def to_price_table(history: pd.DataFrame) -> pd.DataFrame:
    """Convert a yfinance history DataFrame to the daily_prices layout.

    Rows for the current day are removed, because the session may still be
    open and the bar incomplete. "Today" is evaluated in the time zone of the
    returned index (the exchange's for equities, UTC for crypto).

    Args:
        history: Output of yfinance Ticker.history() with auto_adjust=False.

    Returns:
        DataFrame with a date column (YYYY-MM-DD strings) and price columns.
    """
    if history.empty:
        return pd.DataFrame(columns=["date", *COLUMN_NAMES.values()])

    # Format the index in its own time zone. Converting equity timestamps to
    # UTC first could move them to a different calendar day.
    dates = history.index.strftime("%Y-%m-%d")
    today = pd.Timestamp.now(tz=history.index.tz).strftime("%Y-%m-%d")

    prices = history[list(COLUMN_NAMES)].rename(columns=COLUMN_NAMES)
    prices.insert(0, "date", dates)
    prices = prices[prices["date"] < today]
    return prices.reset_index(drop=True)
