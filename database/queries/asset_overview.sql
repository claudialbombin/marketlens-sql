-- Asset metadata with data coverage and the latest price up to :end_date.
--
-- latest_daily_change compares the last two observations on or before
-- :end_date, so it is the change of the last available session, not
-- necessarily of :end_date itself (which may be a weekend or holiday).
--
-- Coverage columns (first_date, last_date, observations) describe the full
-- stored history and ignore the selected period on purpose: they show what
-- data is available to choose from.
--
-- Parameters: :end_date (YYYY-MM-DD). :start_date is accepted but unused.

WITH coverage AS (
    SELECT
        asset_id,
        MIN(date) AS first_date,
        MAX(date) AS last_date,
        COUNT(*)  AS observations
    FROM daily_prices
    GROUP BY asset_id
),

ranked_prices AS (
    SELECT
        asset_id,
        date,
        close,
        adjusted_close,
        ROW_NUMBER() OVER (PARTITION BY asset_id ORDER BY date DESC) AS recency_rank,
        LEAD(adjusted_close) OVER (PARTITION BY asset_id ORDER BY date DESC) AS previous_adjusted_close
    FROM daily_prices
    WHERE date <= :end_date
)

SELECT
    a.ticker,
    a.name,
    a.asset_type,
    a.currency,
    a.exchange,
    c.first_date,
    c.last_date,
    c.observations,
    r.date                                           AS latest_date,
    r.close                                          AS latest_close,
    r.adjusted_close / r.previous_adjusted_close - 1 AS latest_daily_change
FROM assets AS a
LEFT JOIN coverage AS c ON c.asset_id = a.asset_id
LEFT JOIN ranked_prices AS r
    ON r.asset_id = a.asset_id
   AND r.recency_rank = 1
ORDER BY a.asset_type, a.ticker;
