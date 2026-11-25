-- Raw and adjusted closing prices of every asset within a period.
--
-- close is the quoted price (what the market showed that day);
-- adjusted_close is adjusted for splits and dividends and is the one used
-- for every return calculation.
--
-- Parameters: :start_date, :end_date (YYYY-MM-DD, inclusive).

SELECT
    a.ticker,
    p.date,
    p.close,
    p.adjusted_close
FROM daily_prices AS p
JOIN assets AS a ON a.asset_id = p.asset_id
WHERE p.date BETWEEN :start_date AND :end_date
ORDER BY a.ticker, p.date;
