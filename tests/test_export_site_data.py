"""Tests for the static site data export."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from database.connection import get_connection, initialize_database
from scripts.export_site_data import PERIODS, export_site_data

RAW_PRICE_KEYS = {"open", "high", "low", "close", "adjusted_close", "volume"}


@pytest.fixture
def connection(tmp_path: Path):
    """Database with two years of synthetic prices for two assets."""
    conn = get_connection(tmp_path / "export.db")
    initialize_database(conn)
    rng = np.random.default_rng(0)
    rows = []
    for ticker, dates in [
        ("AAPL", pd.bdate_range("2023-01-02", "2024-12-31")),
        ("BTC-USD", pd.date_range("2023-01-01", "2024-12-31")),
    ]:
        asset_id = conn.execute("SELECT asset_id FROM assets WHERE ticker = ?", (ticker,)).fetchone()[0]
        prices = 100 * np.cumprod(1 + rng.normal(0, 0.02, len(dates)))
        for date, price in zip(dates.strftime("%Y-%m-%d"), prices):
            rows.append((asset_id, date, price, price, price, price, price, 1000))
    with conn:
        conn.executemany("INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    yield conn
    conn.close()


def collect_keys(value) -> set[str]:
    """Return every dictionary key found anywhere in a JSON structure."""
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys |= collect_keys(child)
        return keys
    if isinstance(value, list):
        keys = set()
        for child in value:
            keys |= collect_keys(child)
        return keys
    return set()


def test_export_writes_meta_and_one_file_per_period(connection, tmp_path):
    output_dir = tmp_path / "site_data"
    export_site_data(connection, output_dir)

    written = {path.name for path in output_dir.iterdir()}
    assert written == {"meta.json"} | {f"{key}.json" for key in PERIODS}

    meta = json.loads((output_dir / "meta.json").read_text())
    assert meta["snapshot_date"] == "2024-12-31"
    assert [asset["ticker"] for asset in meta["assets"]] == ["BTC-USD", "AAPL"]


def test_one_year_period_starts_one_year_before_snapshot(connection, tmp_path):
    export_site_data(connection, tmp_path)

    period = json.loads((tmp_path / "1y.json").read_text())
    assert period["start_date"] == "2023-12-31"
    assert period["cumulative_return"]["AAPL"][0][1] == 0.0


def test_export_contains_no_raw_prices(connection, tmp_path):
    export_site_data(connection, tmp_path)

    for path in tmp_path.glob("*.json"):
        assert not collect_keys(json.loads(path.read_text())) & RAW_PRICE_KEYS, path.name


def test_volatility_series_skip_incomplete_windows(connection, tmp_path):
    export_site_data(connection, tmp_path)

    period = json.loads((tmp_path / "max.json").read_text())
    values = [value for _, value in period["volatility_60d"]["AAPL"]]
    assert values and None not in values


def test_empty_database_is_rejected(tmp_path):
    conn = get_connection(tmp_path / "empty.db")
    initialize_database(conn)

    with pytest.raises(ValueError):
        export_site_data(conn, tmp_path / "out")
    conn.close()
