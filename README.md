# marketlens-sql

SQL-based market data pipeline: API ingestion, relational storage, and quantitative analysis (returns, volatility, correlations) with a dashboard.

## Project status

Early development. The project setup, the SQLite database layer and the data ingestion pipeline are in place; analytical SQL is next.

The pipeline is being built in stages:

1. Project foundation *(done)*
2. Relational database schema (SQLite) *(done)*
3. Historical market data ingestion *(done)*
4. Analytical SQL: returns, volatility, correlations and drawdowns
5. Streamlit dashboard
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
