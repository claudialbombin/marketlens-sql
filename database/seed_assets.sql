-- Initial asset universe.
--
-- This file is the single place where the tracked assets are defined; the
-- ingestion layer reads tickers from the assets table. To add or remove an
-- asset, edit this file and re-run the database initialisation.
--
-- Selection:
--   - S&P 500 as the market benchmark.
--   - Four large US equities from different sectors (technology,
--     financials, energy, healthcare), so correlations are not dominated
--     by a single industry.
--   - Bitcoin and Ether for a different volatility profile and a 7-day
--     trading calendar.
-- Everything is quoted in USD, so no currency conversion is needed.
--
-- ON CONFLICT makes the seed idempotent: running it again updates metadata
-- instead of failing or creating duplicates, and asset_id values stay stable.

INSERT INTO assets (ticker, name, asset_type, currency, exchange)
VALUES
    ('^GSPC',   'S&P 500',                 'index',          'USD', NULL),
    ('AAPL',    'Apple Inc.',              'equity',         'USD', 'NASDAQ'),
    ('JPM',     'JPMorgan Chase & Co.',    'equity',         'USD', 'NYSE'),
    ('XOM',     'Exxon Mobil Corporation', 'equity',         'USD', 'NYSE'),
    ('JNJ',     'Johnson & Johnson',       'equity',         'USD', 'NYSE'),
    ('BTC-USD', 'Bitcoin',                 'cryptocurrency', 'USD', NULL),
    ('ETH-USD', 'Ether',                   'cryptocurrency', 'USD', NULL)
ON CONFLICT (ticker) DO UPDATE SET
    name       = excluded.name,
    asset_type = excluded.asset_type,
    currency   = excluded.currency,
    exchange   = excluded.exchange;
