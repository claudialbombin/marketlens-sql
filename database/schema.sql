-- Relational schema for marketlens-sql.
--
-- Only raw observations are stored. Every derived metric (returns,
-- volatility, correlation, drawdown) is calculated at query time by the
-- files in database/queries/.
--
-- Requires SQLite 3.37+ for STRICT tables. Foreign key enforcement is a
-- per-connection setting and is enabled in database/connection.py.

-- One row per tradable instrument. Metadata lives here only once, and
-- daily_prices references it through asset_id.
CREATE TABLE IF NOT EXISTS assets (
    asset_id   INTEGER PRIMARY KEY,
    ticker     TEXT    NOT NULL UNIQUE,
    name       TEXT    NOT NULL,
    asset_type TEXT    NOT NULL
        CHECK (asset_type IN ('equity', 'index', 'cryptocurrency')),
    -- ISO 4217 code, e.g. 'USD'.
    currency   TEXT    NOT NULL
        CHECK (length(currency) = 3 AND currency = upper(currency)),
    -- NULL when there is no single listing exchange (indices, crypto).
    exchange   TEXT
) STRICT;

-- One row per asset and trading date.
--
-- The primary key is (asset_id, date) rather than (date, asset_id): every
-- analytical query partitions by asset and orders by date, so this column
-- order lets SQLite read each asset's history directly from the primary
-- key without an extra index.
--
-- WITHOUT ROWID stores rows physically in primary-key order and avoids a
-- separate hidden rowid index.
CREATE TABLE IF NOT EXISTS daily_prices (
    asset_id       INTEGER NOT NULL
        REFERENCES assets (asset_id) ON DELETE RESTRICT,
    -- Exchange-local trading date (UTC calendar date for crypto).
    -- date(date) = date rejects both wrong formats and impossible dates
    -- such as 2024-02-30.
    date           TEXT    NOT NULL
        CHECK (date(date) IS NOT NULL AND date(date) = date),
    -- open/high/low/close are raw prices; adjusted_close is adjusted for
    -- splits and dividends and is the only column used for returns.
    open           REAL    NOT NULL CHECK (open > 0),
    high           REAL    NOT NULL CHECK (high > 0),
    low            REAL    NOT NULL CHECK (low > 0),
    close          REAL    NOT NULL CHECK (close > 0),
    adjusted_close REAL    NOT NULL CHECK (adjusted_close > 0),
    -- NULL when the provider has no meaningful volume (e.g. indices).
    volume         INTEGER CHECK (volume >= 0),
    PRIMARY KEY (asset_id, date),
    CHECK (low <= open AND low <= close AND high >= open AND high >= close)
) STRICT, WITHOUT ROWID;
