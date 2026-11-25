# Methodology

All metrics are calculated in SQL by the files in `database/queries/`. Nothing is stored: every query runs on `daily_prices` at request time, for a period given by `:start_date` and `:end_date` (inclusive, `YYYY-MM-DD`).

`analysis/metrics.py` runs these files and returns DataFrames. Its only pandas operation is reshaping correlation pairs into a matrix.

## General assumptions

- **Prices:** every metric uses `adjusted_close`, which is adjusted for splits and dividends, so returns include dividends and are not distorted by splits. Raw OHLC prices are never mixed into calculations.
- **Observations, not calendar days:** a "day" is the next stored observation of the asset. For equities and the index this is the next exchange trading day; for crypto it is the next calendar day.
- **Simple returns:** returns are simple percentage changes, not log returns, because they compound exactly into cumulative returns and are the convention in performance reporting.
- **No look-ahead:** every window looks only backwards in time.
- **Currency:** all assets are quoted in USD, so no conversion is needed.

## Daily returns

File: [`daily_returns.sql`](../database/queries/daily_returns.sql)

$$
R_t = \frac{P_t}{P_{t-1}} - 1
$$

`LAG(adjusted_close) OVER (PARTITION BY asset_id ORDER BY date)` provides $P_{t-1}$. The window runs over the full history before the date filter, so the first day of the period still has a return based on the last price before it.

The first observation of each asset has no previous price and is excluded.

## Cumulative returns

File: [`cumulative_returns.sql`](../database/queries/cumulative_returns.sql)

$$
CR_t = \frac{P_t}{P_0} - 1 = \prod_{i=1}^{t} (1 + R_i) - 1
$$

$P_0$ is the first price inside the selected period (`FIRST_VALUE()` after the date filter), so every asset starts at 0. Using the price ratio directly avoids accumulating rounding errors from multiplying many daily returns.

## Rolling volatility

File: [`rolling_volatility.sql`](../database/queries/rolling_volatility.sql)

Sample standard deviation of the last $n$ daily returns ($n = 20$ and $n = 60$), annualised:

$$
s^2 = \frac{\sum R^2 - \left(\sum R\right)^2 / n}{n - 1}
\qquad
\sigma_{\text{annual}} = s \sqrt{N}
$$

| Asset type | $N$ (observations per year) | Reason |
|---|---|---|
| Equity, index | 252 | Exchange trading days |
| Cryptocurrency | 365 | Trades every calendar day |

Implementation notes:

- SQLite has no `STDDEV` aggregate. The sums are window aggregates over `ROWS BETWEEN n-1 PRECEDING AND CURRENT ROW`. In PostgreSQL the same result is `STDDEV_SAMP(daily_return) OVER (...)`.
- The sample convention ($n - 1$) matches pandas `rolling().std()`.
- A value is NULL until the window contains exactly $n$ returns.
- `MAX(variance, 0)` prevents a tiny negative variance from floating-point rounding, which would make `SQRT()` return NULL.
- Windows are counted in observations. 20 observations cover about four weeks for an equity but under three weeks for crypto.

## Correlation

File: [`correlations.sql`](../database/queries/correlations.sql)

Pearson correlation of returns for every pair of assets:

$$
\rho_{xy} = \frac{n \sum xy - \sum x \sum y}{\sqrt{n \sum x^2 - \left(\sum x\right)^2}\;\sqrt{n \sum y^2 - \left(\sum y\right)^2}}
$$

**Different trading calendars.** Crypto trades every day; equities do not. Matching each asset's own daily returns by date would pair a Friday-to-Monday equity return (3 days) with a Sunday-to-Monday crypto return (1 day). The query therefore, for each pair:

1. keeps only the dates on which both assets have a price;
2. computes returns between consecutive common dates.

The weekend movement of crypto is then folded into its Monday return, and both returns always cover the same interval. For two equities the result is identical to using their ordinary daily returns.

Other rules:

- Each pair appears once. `to_correlation_matrix()` mirrors the pairs and sets the diagonal to 1.
- `observations` reports how many paired returns were used.
- Pairs with fewer than 3 returns, or with a constant price series (zero variance), return NULL.
- In PostgreSQL the final step is `CORR(return_x, return_y)`.

## Maximum drawdown

File: [`maximum_drawdown.sql`](../database/queries/maximum_drawdown.sql)

$$
\text{peak}_t = \max(P_0, \dots, P_t)
\qquad
DD_t = \frac{P_t}{\text{peak}_t} - 1
\qquad
\text{MDD} = \min_t DD_t
$$

- The running peak uses `MAX() OVER (... ROWS UNBOUNDED PRECEDING)` and starts at the first price of the selected period. A peak from before the period is ignored.
- The query also returns the peak date (the last date the price was at its running maximum) and the trough date.
- If the same drawdown occurs twice, the earliest trough is reported. An asset that only rises has a maximum drawdown of 0.

## Validation

`tests/test_metrics.py` checks every query on small datasets:

- hand-calculated examples (for example, prices 100 → 120 → 90 → 130 → 117 give a maximum drawdown of −25%);
- comparison with independent pandas calculations: `pct_change()`, `rolling().std()`, `corr()` and `cummax()`;
- edge cases: incomplete windows, constant prices, perfectly correlated series, mixed crypto/equity calendars, and periods starting after a historical peak.

On the real database (2024-01-01 to 2026-11-24), the SQL and pandas results for volatility and correlation agree to within $10^{-14}$.

## Reproducible example

The queries can be run directly with the `sqlite3` command-line tool after downloading data with `python -m ingestion.update_database`. String parameters need both kinds of quotes:

```text
$ sqlite3 -header -column data/marketlens.db
sqlite> .parameter set :start_date "'2025-01-01'"
sqlite> .parameter set :end_date "'2025-12-31'"
sqlite> .read database/queries/maximum_drawdown.sql
ticker   maximum_drawdown    peak_date   trough_date
-------  ------------------  ----------  -----------
AAPL     -0.302225803703724  2025-02-24  2025-04-08
BTC-USD  -0.321469804846144  2025-10-06  2025-11-22
ETH-USD  -0.600783880546594  2025-01-06  2025-04-08
JNJ      -0.127250962626998  2025-03-10  2025-05-14
JPM      -0.24423922585472   2025-02-18  2025-04-04
XOM      -0.160534296596031  2025-04-01  2025-04-10
^GSPC    -0.18902206184284   2025-02-19  2025-04-08
```

The output above was produced with data downloaded on 2026-11-25. Values can change slightly after Yahoo Finance revises adjusted prices.
