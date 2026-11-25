-- Daily simple returns per asset.
--
--   R_t = P_t / P_{t-1} - 1,   P = adjusted_close
--
-- P_{t-1} is the previous stored observation of the same asset: the
-- previous trading day for equities and indices, the previous calendar day
-- for crypto. If a row was rejected during ingestion, the return spans the
-- gap.
--
-- LAG() runs over the full history before the date filter is applied, so
-- the first day of the selected period still gets a return based on the
-- last price before :start_date.
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
)

SELECT
    a.ticker,
    p.date,
    p.adjusted_close / p.previous_adjusted_close - 1 AS daily_return
FROM prices_with_previous AS p
JOIN assets AS a ON a.asset_id = p.asset_id
WHERE p.previous_adjusted_close IS NOT NULL
  AND p.date BETWEEN :start_date AND :end_date
ORDER BY a.ticker, p.date;
