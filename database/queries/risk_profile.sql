-- Return and volatility of each asset over the whole selected period.
--
--   total_return          = P_last / P_first - 1
--   annualised_return     = (1 + total_return)^(N / n) - 1
--   annualised_volatility = s * sqrt(N)
--
-- n is the number of daily returns in the period, s their sample standard
-- deviation, and N the observations per year (252 for equities and
-- indices, 365 for crypto). Annualising by observation count keeps equities
-- and crypto comparable even though they have different calendars.
--
-- Returns are computed only from prices inside the period, so the first
-- day has no return; this matches cumulative_returns.sql, which starts at 0
-- on the first day.
--
-- Assets with fewer than 2 returns in the period get NULL statistics.
--
-- Parameters: :start_date, :end_date (YYYY-MM-DD, inclusive).

WITH period_returns AS (
    SELECT
        asset_id,
        date,
        adjusted_close,
        adjusted_close / LAG(adjusted_close) OVER (
            PARTITION BY asset_id
            ORDER BY date
        ) - 1 AS daily_return,
        FIRST_VALUE(adjusted_close) OVER asset_history AS first_adjusted_close,
        LAST_VALUE(adjusted_close) OVER asset_history  AS last_adjusted_close
    FROM daily_prices
    WHERE date BETWEEN :start_date AND :end_date
    WINDOW asset_history AS (
        PARTITION BY asset_id
        ORDER BY date
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    )
),

return_sums AS (
    SELECT
        asset_id,
        COUNT(daily_return)              AS n,
        SUM(daily_return)                AS sum_returns,
        SUM(daily_return * daily_return) AS sum_squares,
        MAX(first_adjusted_close)        AS first_adjusted_close,
        MAX(last_adjusted_close)         AS last_adjusted_close
    FROM period_returns
    GROUP BY asset_id
),

statistics AS (
    SELECT
        s.asset_id,
        s.n,
        s.last_adjusted_close / s.first_adjusted_close - 1 AS total_return,
        CASE WHEN s.n >= 2
            THEN MAX((s.sum_squares - s.sum_returns * s.sum_returns / s.n) / (s.n - 1), 0)
        END AS variance,
        CASE a.asset_type WHEN 'cryptocurrency' THEN 365 ELSE 252 END AS periods_per_year
    FROM return_sums AS s
    JOIN assets AS a ON a.asset_id = s.asset_id
)

SELECT
    a.ticker,
    st.n AS observations,
    st.total_return,
    CASE WHEN st.n >= 2
        THEN POWER(1 + st.total_return, 1.0 * st.periods_per_year / st.n) - 1
    END AS annualised_return,
    SQRT(st.variance * st.periods_per_year) AS annualised_volatility
FROM statistics AS st
JOIN assets AS a ON a.asset_id = st.asset_id
ORDER BY a.ticker;
