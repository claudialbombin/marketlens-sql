# marketlens-sql

SQL-based market data pipeline: API ingestion, relational storage, and quantitative analysis (returns, volatility, correlations) with a dashboard.

## Project status

Early development. The project setup and the SQLite database layer are in place; data ingestion is next.

The pipeline is being built in stages:

1. Project foundation *(done)*
2. Relational database schema (SQLite) *(done)*
3. Historical market data ingestion
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

## Running the tests

```bash
pytest
```

## Disclaimer

This is an educational and portfolio project. It works with historical, delayed data and is not an investment recommendation tool.

## License

MIT. See [LICENSE](LICENSE).
