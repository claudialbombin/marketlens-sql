"""Export a snapshot of the analytical results for the static showcase site.

Usage:
    python -m scripts.export_site_data

Writes JSON files to site/data/:
    meta.json        assets, periods and snapshot date
    <period>.json    metrics for one period (1y, 3y, max)

Only derived metrics are exported (returns, volatility, drawdowns,
correlations). Raw Yahoo Finance prices are not republished.
"""

import datetime as dt
import json
import logging
import math
import sqlite3
from pathlib import Path

import pandas as pd

from analysis import metrics
from config import settings
from database.connection import get_connection

logger = logging.getLogger(__name__)

OUTPUT_DIR = settings.PROJECT_ROOT / "site" / "data"

# Period key -> (label, years back from the snapshot date). None = full history.
PERIODS = {
    "1y": ("1 year", 1),
    "3y": ("3 years", 3),
    "max": ("Since 2018", None),
}

# Four decimals of a return (0.01 bp) are far below what a chart can show
# and keep the files small.
DECIMALS = 4


def clean_number(value: float) -> float | None:
    """Round a float for JSON output, turning NaN into null."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(float(value), DECIMALS)


def to_series(data: pd.DataFrame, value_column: str) -> dict[str, list]:
    """Group a long-format result into {ticker: [[date, value], ...]}.

    Rows with a NULL value (for example, before a volatility window is full)
    are left out.
    """
    series = {}
    for ticker, rows in data.dropna(subset=[value_column]).groupby("ticker"):
        points = []
        for date, value in zip(rows["date"], rows[value_column]):
            points.append([date, clean_number(value)])
        series[ticker] = points
    return series


def to_rows(data: pd.DataFrame) -> list[dict]:
    """Convert a small result table to a list of JSON-safe dictionaries."""
    rows = []
    for record in data.to_dict(orient="records"):
        clean = {}
        for key, value in record.items():
            clean[key] = clean_number(value) if isinstance(value, float) else value
        rows.append(clean)
    return rows


def period_start(snapshot_date: dt.date, years: int | None) -> str:
    """Return the first date of a period ending on the snapshot date."""
    if years is None:
        return settings.HISTORY_START_DATE
    return snapshot_date.replace(year=snapshot_date.year - years).isoformat()


def build_period(connection: sqlite3.Connection, start: str, end: str) -> dict:
    """Collect every metric shown on the site for one period."""
    volatility = metrics.run_query(connection, "rolling_volatility", start, end)
    risk = metrics.run_query(connection, "risk_profile", start, end).merge(
        metrics.run_query(connection, "maximum_drawdown", start, end), on="ticker", how="left"
    )
    return {
        "start_date": start,
        "end_date": end,
        "cumulative_return": to_series(
            metrics.run_query(connection, "cumulative_returns", start, end), "cumulative_return"
        ),
        "volatility_20d": to_series(volatility, "volatility_20d"),
        "volatility_60d": to_series(volatility, "volatility_60d"),
        "risk_profile": to_rows(risk),
        "correlations": to_rows(metrics.run_query(connection, "correlations", start, end)),
    }


def write_json(path: Path, content: dict) -> None:
    """Write compact JSON; allow_nan=False guarantees valid JSON output."""
    path.write_text(json.dumps(content, separators=(",", ":"), allow_nan=False))
    logger.info("Wrote %s (%.0f KB)", path, path.stat().st_size / 1024)


def export_site_data(connection: sqlite3.Connection, output_dir: Path) -> None:
    """Export metadata and one file per period.

    Args:
        connection: Open database connection with downloaded prices.
        output_dir: Directory that receives the JSON files.

    Raises:
        ValueError: If the database contains no prices.
    """
    last_date = connection.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0]
    if last_date is None:
        raise ValueError("The database has no prices; run the ingestion first.")
    snapshot_date = dt.date.fromisoformat(last_date)

    assets = metrics.run_query(connection, "asset_overview", last_date, last_date)
    assets = assets.dropna(subset=["observations"])

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "meta.json",
        {
            "snapshot_date": last_date,
            "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "assets": to_rows(assets[["ticker", "name", "asset_type", "first_date", "last_date"]]),
            "periods": [{"key": key, "label": label} for key, (label, _) in PERIODS.items()],
        },
    )
    for key, (_, years) in PERIODS.items():
        start = period_start(snapshot_date, years)
        write_json(output_dir / f"{key}.json", build_period(connection, start, last_date))


def main() -> None:
    """Export the site data from the configured database."""
    logging.basicConfig(level=settings.LOG_LEVEL, format="%(levelname)s %(message)s")
    connection = get_connection(settings.DATABASE_PATH)
    try:
        export_site_data(connection, OUTPUT_DIR)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
