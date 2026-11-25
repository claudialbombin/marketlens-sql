"""Smoke tests for the Streamlit dashboard using Streamlit's AppTest.

The app runs against a small synthetic database, so no network access or
downloaded data is needed.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from config import settings
from database.connection import get_connection, initialize_database

APP_PATH = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")


@pytest.fixture
def database(tmp_path: Path, monkeypatch) -> Path:
    """Create a database with 90 days of synthetic prices for three assets."""
    database_path = tmp_path / "dashboard.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", database_path)
    st.cache_data.clear()

    connection = get_connection(database_path)
    initialize_database(connection)
    rng = np.random.default_rng(0)
    calendar_days = pd.date_range("2024-01-01", periods=90)
    business_days = pd.bdate_range("2024-01-01", "2024-03-30")

    rows = []
    for ticker, dates in [("AAPL", business_days), ("JPM", business_days), ("BTC-USD", calendar_days)]:
        asset_id = connection.execute(
            "SELECT asset_id FROM assets WHERE ticker = ?", (ticker,)
        ).fetchone()[0]
        prices = 100 * np.cumprod(1 + rng.normal(0, 0.02, len(dates)))
        for date, price in zip(dates.strftime("%Y-%m-%d"), prices):
            rows.append((asset_id, date, price, price, price, price, price, 1000))

    with connection:
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
    connection.close()
    return database_path


def run_app() -> AppTest:
    """Run the dashboard script once and return the test handle."""
    return AppTest.from_file(APP_PATH, default_timeout=30).run()


def test_dashboard_renders_all_sections(database):
    app = run_app()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Overview", "Performance", "Risk", "Correlation"]
    # Only assets with prices are offered and shown.
    assert sorted(app.sidebar.multiselect[1].value) == ["AAPL", "BTC-USD", "JPM"]
    assert len(app.metric) == 3


def test_charts_have_reading_guides_and_summaries(database):
    app = run_app()

    labels = [expander.label for expander in app.expander]
    assert "New to finance? Start here" in labels
    assert labels.count("How to read this chart") == 6
    summaries = [text.value for text in app.markdown if text.value.startswith("**In this period:**")]
    assert len(summaries) == 5


def test_correlation_needs_two_assets(database):
    app = run_app()
    app.sidebar.multiselect[1].set_value(["AAPL"]).run()

    assert not app.exception
    assert any("at least two assets" in info.value for info in app.info)


def test_changing_period_and_window_does_not_fail(database):
    app = run_app()
    app.sidebar.date_input[0].set_value((pd.Timestamp("2024-02-01"), pd.Timestamp("2024-03-15"))).run()
    app.segmented_control(key="window").set_value("60 observations").run()

    assert not app.exception


def test_missing_database_shows_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_path / "missing.db")
    st.cache_data.clear()

    app = run_app()

    assert not app.exception
    assert "update_database" in app.warning[0].value
