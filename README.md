# marketlens-sql

SQL-based market data pipeline: API ingestion, relational storage, and quantitative analysis (returns, volatility, correlations) with a dashboard.

## Project status

The database, data ingestion, analytical SQL, Streamlit dashboard and static showcase are in place.

The pipeline is being built in stages:

1. Project foundation *(done)*
2. Relational database schema (SQLite) *(done)*
3. Historical market data ingestion *(done)*
4. Analytical SQL: returns, volatility, correlations and drawdowns *(done)*
5. Streamlit dashboard *(done)*
6. Static showcase on GitHub Pages *(done)*

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

## Reading the results

No finance background is needed to follow the dashboard or the showcase. This section explains what each metric means in plain language, with figures from the data snapshot up to 24 Nov 2026.

### The assets

| Ticker | Asset | Why it is included |
|---|---|---|
| `^GSPC` | S&P 500 | An index of the 500 largest US companies. It is the benchmark: "the market" that the other assets are compared with. |
| `AAPL` | Apple | Technology |
| `JPM` | JPMorgan Chase | Banking |
| `XOM` | Exxon Mobil | Oil and gas |
| `JNJ` | Johnson & Johnson | Healthcare |
| `BTC-USD` | Bitcoin | Cryptocurrency, priced in US dollars and traded every day |
| `ETH-USD` | Ether | Cryptocurrency, priced in US dollars and traded every day |

The four companies come from different sectors so that they react differently to the same news.

### Return: how much was gained or lost

A return of +25% means that 100 dollars became 125. All returns use prices adjusted for dividends and splits, so dividends count as if they had been reinvested.

The cumulative return chart starts every asset at 0% on the first day of the selected period. Each line then shows what an investment made on that day would have gained or lost by any later date. Lines above the S&P 500 beat the market over those dates.

*Example:* over the year to 24 Nov 2026, Exxon Mobil returned +40.1%, the S&P 500 +7.4% and Ether −43.2%.

### Volatility: how bumpy the ride was

Volatility measures how much the price moves from one day to the next, scaled to a year. It says nothing about direction: a price that rises steadily has low volatility, and one that swings up and down has high volatility even if it ends where it started.

As a rough guide, a volatility of 20% means that a typical year ends within about 20% above or below the average outcome. The rolling volatility chart recalculates it every day over the previous 20 or 60 observations, so spikes mark stressful periods such as March 2020.

*Example:* over the same year, the S&P 500 had a volatility of 15.0%, Apple about 25% and Ether 60.7%. Spreading money over 500 companies cancels out much of the movement of any single one.

### Maximum drawdown: the worst fall

A drawdown is the fall from the highest price reached so far to a later low. The maximum drawdown is the worst of these falls in the period: what someone who bought at the top would have lost at the worst moment.

Losses are harder to recover from than they look. After a 50% fall, the price has to double (+100%) to get back to where it was.

*Example:* since 2018, the S&P 500's worst fall was −33.9%, from 19 Feb 2020 to 23 Mar 2020, at the start of the pandemic. Ether's was −94.0% in 2018.

### Return against volatility

The scatter chart puts annualised volatility on the horizontal axis and annualised return on the vertical axis. Assets in the top left earned more for each unit of risk; assets in the bottom right took more risk and earned less.

The annualised return is the steady yearly rate that would produce the same total return. Over periods shorter than a year, it extrapolates a few weeks of performance to a full year and should be read with care.

### Correlation: do two assets move together?

Correlation goes from −1 to +1:

- close to **+1**: the two assets usually rise and fall on the same days;
- close to **0**: their daily movements are unrelated;
- close to **−1**: when one rises, the other tends to fall.

Combining assets with low correlation makes a portfolio's ups and downs smaller, because a fall in one is often offset by another. This is the idea behind diversification. Correlation says how often two assets move together, not how much either of them gains.

*Example:* over the year to 24 Nov 2026, Bitcoin and Ether had a correlation of 0.91. The S&P 500 and Exxon Mobil had −0.29: in that year, the oil company tended slightly to move against the rest of the market.

### In the dashboard and the showcase

Every chart has a short *How to read this chart* note and a summary of what the data shows for the selected period and assets, for example which asset did best and which pair is most closely linked. The summaries only select the highest and lowest values returned by the SQL queries; they do not calculate anything new.

Past performance does not indicate future results.

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

The Overview tab opens with a short glossary of the terms used, and each chart has a *How to read this chart* note and a plain-language summary of the selected data.

## Static showcase

A read-only summary of the results is published with GitHub Pages: **https://claudialbombin.github.io/marketlens-sql/**

GitHub Pages can only serve static files, so the page works on a snapshot:

1. `python -m scripts.export_site_data` runs the SQL queries and writes JSON files to `site/data/` (one per period: 1 year, 3 years, since 2018).
2. The JSON files are committed. The page shows the snapshot date.
3. `.github/workflows/pages.yml` publishes the `site/` folder whenever it changes on `main`.

The page is plain HTML, CSS and JavaScript with hand-drawn SVG charts; there is no build step. Only derived metrics are exported, never raw prices.

To preview it locally:

```bash
python -m http.server -d site
```

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
