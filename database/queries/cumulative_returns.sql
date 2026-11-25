-- Cumulative return of each asset since the start of the selected period.
--
--   CR_t = P_t / P_0 - 1
--
-- P_0 is the first adjusted close inside the period, so every asset starts
-- at 0 on its first available date. This equals compounding the daily
-- returns, prod(1 + R_i) - 1, because the intermediate prices cancel out.
--
-- The date filter is applied before FIRST_VALUE() on purpose: the base
-- price must be the first price of the period, not of the whole history.
--
-- Parameters: :start_date, :end_date (YYYY-MM-DD, inclusive).

WITH period_prices AS (
    SELECT
        asset_id,
        date,
        adjusted_close,
        FIRST_VALUE(adjusted_close) OVER (
            PARTITION BY asset_id
            ORDER BY date
        ) AS base_adjusted_close
    FROM daily_prices
    WHERE date BETWEEN :start_date AND :end_date
)

SELECT
    a.ticker,
    p.date,
    p.adjusted_close / p.base_adjusted_close - 1 AS cumulative_return
FROM period_prices AS p
JOIN assets AS a ON a.asset_id = p.asset_id
ORDER BY a.ticker, p.date;
