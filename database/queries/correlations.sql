-- Pearson correlation of daily returns for every pair of assets.
--
-- Different trading calendars: equities trade on exchange days, crypto
-- every day. Pairing each asset's own daily returns by date would compare a
-- 3-day equity return (Friday to Monday) with a 1-day crypto return
-- (Sunday to Monday). Instead, for each pair:
--
--   1. keep only the dates on which BOTH assets have a price;
--   2. compute returns between consecutive common dates.
--
-- Both returns in a pair then always cover the same interval. For two
-- equities this is identical to their ordinary daily returns.
--
-- SQLite has no CORR aggregate, so the coefficient is computed from sums
-- over the n paired returns:
--
--   rho = (n*Sxy - Sx*Sy) / (sqrt(n*Sxx - Sx^2) * sqrt(n*Syy - Sy^2))
--
-- Each pair appears once (asset_x < asset_y). The first common date in the
-- period has no previous price, so a pair with k common dates yields k - 1
-- returns. Pairs with fewer than 3 returns, or with a constant series, get
-- NULL.
--
-- PostgreSQL equivalent of the final step: CORR(return_x, return_y).
--
-- Parameters: :start_date, :end_date (YYYY-MM-DD, inclusive).

WITH period_prices AS (
    SELECT
        asset_id,
        date,
        adjusted_close
    FROM daily_prices
    WHERE date BETWEEN :start_date AND :end_date
),

common_dates AS (
    SELECT
        x.asset_id       AS asset_x,
        y.asset_id       AS asset_y,
        x.date,
        x.adjusted_close AS price_x,
        y.adjusted_close AS price_y
    FROM period_prices AS x
    JOIN period_prices AS y
        ON y.date = x.date
       AND y.asset_id > x.asset_id
),

pair_returns AS (
    SELECT
        asset_x,
        asset_y,
        price_x / LAG(price_x) OVER pair_window - 1 AS return_x,
        price_y / LAG(price_y) OVER pair_window - 1 AS return_y
    FROM common_dates
    WINDOW pair_window AS (PARTITION BY asset_x, asset_y ORDER BY date)
),

pair_sums AS (
    SELECT
        asset_x,
        asset_y,
        COUNT(*)                   AS n,
        SUM(return_x)              AS sum_x,
        SUM(return_y)              AS sum_y,
        SUM(return_x * return_x)   AS sum_xx,
        SUM(return_y * return_y)   AS sum_yy,
        SUM(return_x * return_y)   AS sum_xy
    FROM pair_returns
    WHERE return_x IS NOT NULL
    GROUP BY asset_x, asset_y
)

SELECT
    ax.ticker AS ticker_x,
    ay.ticker AS ticker_y,
    s.n       AS observations,
    CASE WHEN s.n >= 3 THEN
        (s.n * s.sum_xy - s.sum_x * s.sum_y)
        / NULLIF(
            SQRT(MAX(s.n * s.sum_xx - s.sum_x * s.sum_x, 0))
            * SQRT(MAX(s.n * s.sum_yy - s.sum_y * s.sum_y, 0)),
            0
        )
    END AS correlation
FROM pair_sums AS s
JOIN assets AS ax ON ax.asset_id = s.asset_x
JOIN assets AS ay ON ay.asset_id = s.asset_y
ORDER BY ticker_x, ticker_y;
