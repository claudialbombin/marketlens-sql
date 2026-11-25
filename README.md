# marketlens-sql

SQL-based market data pipeline: API ingestion, relational storage, and quantitative analysis (returns, volatility, correlations) with a dashboard.

## Project status

Early development. The database, data ingestion, analytical SQL and Streamlit dashboard are in place; the static showcase is next.

The pipeline is being built in stages:

1. Project foundation *(done)*
2. Relational database schema (SQLite) *(done)*
3. Historical market data ingestion *(done)*
4. Analytical SQL: returns, volatility, correlations and drawdowns *(done)*
5. Streamlit dashboard *(done)*
6. Static showcase on GitHub Pages

Each section of this README is added when the corresponding component exists.

## Requirements

- Python 3.11 or later
- Git

## Installation

```bash
git clone https://github.com/claudialbombin/marketlens-sql.git
cd marketlens-sql
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Database

The SQLite database is built from SQL scripts only, without an ORM:

- [`database/schema.sql`](database/schema.sql): `assets` and `daily_prices` tables with primary keys, foreign keys and validation constraints.
- [`database/seed_assets.sql`](database/seed_assets.sql): the asset universe (S&P 500, AAPL, JPM, XOM, JNJ, BTC-USD, ETH-USD).

Only raw observations are stored; all metrics will be calculated in SQL at query time. The reasoning behind each design decision is in [`docs/database_schema.md`](docs/database_schema.md).

Requires SQLite 3.37 or later, which is bundled with recent Python versions. Check yours with:

```bash
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

## Downloading market data

```bash
python -m ingestion.update_database
```

This creates the database if needed and brings every asset up to date. It can be re-run at any time.

- **Source:** daily data from Yahoo Finance through [`yfinance`](https://github.com/ranaroussi/yfinance), from 2018-01-01. Both raw prices and adjusted closes (adjusted for splits and dividends) are stored.
- **Incremental updates:** only missing dates are downloaded. The last 5 stored days are downloaded again and compared; if Yahoo has changed their adjusted close (after a dividend or split), the asset's full history is reloaded so all stored prices share the same adjustment basis.
- **Validation:** rows with missing or non-positive prices, inconsistent high/low values, negative volume or duplicate dates are rejected and logged, never corrected.
- **Incomplete sessions:** the current day is never stored, because the session may still be open.
- **Errors:** network errors and rate limits are retried with exponential backoff. If one asset fails, the others are still updated and the command exits with a non-zero status.

Optional settings (database path, log level) can be overridden with the environment variables listed in [`.env.example`](.env.example). No API key is required.

## Analytical SQL

All metrics are calculated in SQL at query time, using window functions and CTEs. Each file in [`database/queries/`](database/queries/) takes a `:start_date` and `:end_date` parameter:

| Query | Metric |
|---|---|
| [`daily_returns.sql`](database/queries/daily_returns.sql) | $R_t = P_t / P_{t-1} - 1$ using `LAG()` |
| [`cumulative_returns.sql`](database/queries/cumulative_returns.sql) | Return since the start of the period, using `FIRST_VALUE()` |
| [`rolling_volatility.sql`](database/queries/rolling_volatility.sql) | Annualised 20- and 60-observation volatility (252 days for equities, 365 for crypto) |
| [`correlations.sql`](database/queries/correlations.sql) | Pearson correlation for every pair of assets, on common trading dates |
| [`maximum_drawdown.sql`](database/queries/maximum_drawdown.sql) | Largest peak-to-trough decline, with peak and trough dates |

SQLite has no `STDDEV` or `CORR` functions, so both are implemented explicitly from sums; the results are validated against pandas in the tests. Formulas, assumptions and the handling of different trading calendars are explained in [`docs/methodology.md`](docs/methodology.md).

Example: the maximum drawdown in 2025, run directly with the `sqlite3` CLI.

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

From Python, [`analysis/metrics.py`](analysis/metrics.py) runs the same files and returns pandas DataFrames.

## Dashboard

```bash
streamlit run dashboard/app.py
```

The dashboard reads directly from the SQLite database and runs the SQL files in `database/queries/`; it does not recalculate any metric in pandas. Run `python -m ingestion.update_database` first.

- **Filters:** asset type, assets and date range (the last year by default).
- **Overview:** latest available close and daily change per asset, and data coverage.
- **Performance:** cumulative returns compared across assets, and quoted or adjusted price history.
- **Risk:** rolling volatility (20 or 60 observations), maximum drawdown, and annualised return against volatility.
- **Correlation:** heatmap and pair table, computed on common trading dates.

## Running the tests

```bash
pytest
```

Tests use small synthetic datasets and never call the Yahoo Finance API.

## Limitations

- `yfinance` is an unofficial wrapper around Yahoo Finance's public endpoints, not a contractual data feed. Its output can change between versions (the version is pinned for this reason), and Yahoo's terms restrict the data to personal and research use.
- Yahoo enforces undocumented rate limits.
- Data is end-of-day and historical; nothing is real-time.
- Equities and the index follow the NYSE/NASDAQ calendar, while cryptocurrencies trade every day. Their dates do not align.

## Disclaimer

This is an educational and portfolio project. It works with historical, delayed data and is not an investment recommendation tool.

## License

MIT. See [LICENSE](LICENSE).
