-- Annualised rolling volatility over 20 and 60 observations.
--
-- SQLite has no STDDEV aggregate, so the sample standard deviation over a
-- window of n returns is built from running sums:
--
--   s^2 = (sum(R^2) - sum(R)^2 / n) / (n - 1)
--   annualised volatility = s * sqrt(periods_per_year)
--
-- periods_per_year is 252 for equities and indices (exchange trading days)
-- and 365 for cryptocurrencies (they trade every calendar day).
--
-- A value is only reported when the window holds exactly n returns, so the
-- first 19 (or 59) observations of each asset are NULL.
--
-- Windows are computed over the full history and filtered afterwards: a
-- value on :start_date uses the returns before it, which is past data and
-- introduces no look-ahead bias.
--
-- PostgreSQL equivalent: STDDEV_SAMP(daily_return) OVER (...).
--
-- Parameters: :start_date, :end_date (YYYY-MM-DD, inclusive).

WITH prices_with_previous AS (
    SELECT
        asset_id,
        date,
        adjusted_close,
        LAG(adjusted_close) OVER (
            PARTITION BY asset_id
            ORDER BY date
        ) AS previous_adjusted_close
    FROM daily_prices
),

daily_returns AS (
    SELECT
        asset_id,
        date,
        adjusted_close / previous_adjusted_close - 1 AS daily_return
    FROM prices_with_previous
    WHERE previous_adjusted_close IS NOT NULL
),

window_sums AS (
    SELECT
        asset_id,
        date,
        COUNT(daily_return)                   OVER window_20 AS count_20,
        SUM(daily_return)                     OVER window_20 AS sum_20,
        SUM(daily_return * daily_return)      OVER window_20 AS sum_squares_20,
        COUNT(daily_return)                   OVER window_60 AS count_60,
        SUM(daily_return)                     OVER window_60 AS sum_60,
        SUM(daily_return * daily_return)      OVER window_60 AS sum_squares_60
    FROM daily_returns
    WINDOW
        window_20 AS (PARTITION BY asset_id ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        window_60 AS (PARTITION BY asset_id ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
),

sample_variances AS (
    -- MAX(..., 0) guards against tiny negative values caused by floating
    -- point rounding when the returns in a window are almost constant.
    SELECT
        asset_id,
        date,
        CASE WHEN count_20 = 20
            THEN MAX((sum_squares_20 - sum_20 * sum_20 / 20) / 19, 0)
        END AS variance_20,
        CASE WHEN count_60 = 60
            THEN MAX((sum_squares_60 - sum_60 * sum_60 / 60) / 59, 0)
        END AS variance_60
    FROM window_sums
),

annualisation AS (
    SELECT
        asset_id,
        ticker,
        CASE asset_type WHEN 'cryptocurrency' THEN 365 ELSE 252 END AS periods_per_year
    FROM assets
)

SELECT
    an.ticker,
    v.date,
    SQRT(v.variance_20 * an.periods_per_year) AS volatility_20d,
    SQRT(v.variance_60 * an.periods_per_year) AS volatility_60d
FROM sample_variances AS v
JOIN annualisation AS an ON an.asset_id = v.asset_id
WHERE v.date BETWEEN :start_date AND :end_date
ORDER BY an.ticker, v.date;
