-- Maximum drawdown of each asset within the selected period.
--
--   peak_t     = max(P_0, ..., P_t)
--   drawdown_t = P_t / peak_t - 1
--   maximum drawdown = min(drawdown_t)
--
-- The running peak only looks backwards (ROWS UNBOUNDED PRECEDING), so no
-- future price is used. The peak starts at the first price of the period,
-- because the date filter is applied before the window functions.
--
-- Returned per asset: the maximum drawdown, the date of the peak it was
-- measured from and the trough date. An asset that never falls below its
-- running peak has a maximum drawdown of 0. If the same drawdown occurs
-- twice, the earliest trough is reported.
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

running_peaks AS (
    SELECT
        asset_id,
        date,
        adjusted_close,
        MAX(adjusted_close) OVER (
            PARTITION BY asset_id
            ORDER BY date
            ROWS UNBOUNDED PRECEDING
        ) AS running_peak
    FROM period_prices
),

drawdowns AS (
    SELECT
        asset_id,
        date,
        adjusted_close / running_peak - 1 AS drawdown,
        -- The current peak date is the latest date so far on which the
        -- price was at its running maximum.
        MAX(CASE WHEN adjusted_close = running_peak THEN date END) OVER (
            PARTITION BY asset_id
            ORDER BY date
            ROWS UNBOUNDED PRECEDING
        ) AS peak_date
    FROM running_peaks
),

ranked_drawdowns AS (
    SELECT
        asset_id,
        date,
        drawdown,
        peak_date,
        ROW_NUMBER() OVER (
            PARTITION BY asset_id
            ORDER BY drawdown, date
        ) AS drawdown_rank
    FROM drawdowns
)

SELECT
    a.ticker,
    r.drawdown  AS maximum_drawdown,
    r.peak_date,
    r.date      AS trough_date
FROM ranked_drawdowns AS r
JOIN assets AS a ON a.asset_id = r.asset_id
WHERE r.drawdown_rank = 1
ORDER BY a.ticker;
