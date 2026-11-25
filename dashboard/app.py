"""Streamlit dashboard for the marketlens-sql database.

Run from the project root:
    streamlit run dashboard/app.py

Every number shown here comes from the SQL files in database/queries/,
executed through analysis.metrics. The dashboard only filters, reshapes and
plots those results.
"""

import datetime as dt
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# `streamlit run` puts dashboard/ on sys.path, not the project root, so the
# project packages would not be importable otherwise.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis import metrics  # noqa: E402
from config import settings  # noqa: E402
from database.connection import get_connection  # noqa: E402

DEFAULT_LOOKBACK_DAYS = 365


@st.cache_data(ttl="10m", show_spinner=False)
def load(query_name: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Run one analytical query and cache the result.

    A new connection is opened per call because SQLite connections cannot be
    shared across the threads Streamlit uses for each session.

    Args:
        query_name: File name in database/queries without the extension.
        start_date: First date of the period, YYYY-MM-DD.
        end_date: Last date of the period, YYYY-MM-DD.

    Returns:
        Query result as a DataFrame.
    """
    connection = get_connection(settings.DATABASE_PATH)
    try:
        return metrics.run_query(connection, query_name, start_date, end_date)
    finally:
        connection.close()


def select_filters(overview: pd.DataFrame) -> tuple[list[str], dt.date, dt.date]:
    """Draw the sidebar filters and return the selected assets and period."""
    st.sidebar.header("Filters")

    asset_types = sorted(overview["asset_type"].unique())
    selected_types = st.sidebar.multiselect("Asset type", asset_types, default=asset_types)
    available = overview[overview["asset_type"].isin(selected_types)]

    labels = dict(zip(overview["ticker"], overview["ticker"] + " · " + overview["name"]))
    tickers = st.sidebar.multiselect(
        "Assets",
        list(available["ticker"]),
        default=list(available["ticker"]),
        format_func=labels.get,
    )

    first_date = dt.date.fromisoformat(overview["first_date"].min())
    last_date = dt.date.fromisoformat(overview["last_date"].max())
    default_start = max(first_date, last_date - dt.timedelta(days=DEFAULT_LOOKBACK_DAYS))
    period = st.sidebar.date_input(
        "Period",
        value=(default_start, last_date),
        min_value=first_date,
        max_value=last_date,
    )
    # While the user is picking the second date, date_input returns one value.
    if len(period) != 2:
        st.sidebar.info("Select an end date.")
        st.stop()

    st.sidebar.caption(
        f"Data from Yahoo Finance, {first_date:%d %b %Y} to {last_date:%d %b %Y}. "
        "End-of-day historical data, not real-time."
    )
    return tickers, period[0], period[1]


def line_chart(data: pd.DataFrame, value: str, title: str, percent: bool) -> alt.Chart:
    """Build a multi-asset line chart from a long-format DataFrame."""
    axis_format = ".0%" if percent else ",.2f"
    tooltip_format = ".2%" if percent else ",.2f"
    return (
        alt.Chart(data)
        .mark_line(strokeWidth=1.5)
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y(f"{value}:Q", title=title, axis=alt.Axis(format=axis_format)),
            color=alt.Color("ticker:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip("ticker:N", title="Asset"),
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip(f"{value}:Q", title=title, format=tooltip_format),
            ],
        )
        .properties(height=380)
    )


def show_overview(overview: pd.DataFrame, tickers: list[str], end_date: dt.date) -> None:
    """Market overview: asset list, coverage and latest prices."""
    st.subheader("Latest available prices")
    st.caption(
        f"Last observation on or before {end_date:%d %b %Y}. "
        "Prices are quoted closes; the change uses adjusted closes."
    )

    selected = overview[overview["ticker"].isin(tickers)]
    columns = st.columns(min(len(selected), 4))
    for position, row in enumerate(selected.itertuples()):
        change = row.latest_daily_change
        columns[position % len(columns)].metric(
            label=f"{row.ticker} · {row.latest_date}",
            value=f"{row.latest_close:,.2f} {row.currency}",
            delta=None if pd.isna(change) else f"{change:.2%}",
        )

    st.subheader("Assets")
    st.dataframe(
        selected[
            ["ticker", "name", "asset_type", "currency", "exchange",
             "first_date", "last_date", "observations"]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "ticker": "Ticker",
            "name": "Name",
            "asset_type": "Type",
            "currency": "Currency",
            "exchange": "Exchange",
            "first_date": "First date",
            "last_date": "Last date",
            "observations": "Observations",
        },
    )


def show_performance(tickers: list[str], start: str, end: str) -> None:
    """Price performance: cumulative returns and price history."""
    cumulative = load("cumulative_returns", start, end)
    cumulative = cumulative[cumulative["ticker"].isin(tickers)]

    st.subheader("Cumulative return")
    st.caption(
        "Growth since each asset's first observation in the period, from adjusted "
        "closes (dividends reinvested). Puts assets with very different prices on one scale."
    )
    st.altair_chart(
        line_chart(cumulative, "cumulative_return", "Cumulative return", percent=True),
        width="stretch",
    )

    st.subheader("Price history")
    prices = load("price_history", start, end)
    ticker = st.selectbox("Asset", tickers, key="price_asset")
    price_type = st.segmented_control(
        "Price", ["Adjusted close", "Close"], default="Adjusted close", key="price_type"
    )
    column = "close" if price_type == "Close" else "adjusted_close"
    st.altair_chart(
        line_chart(prices[prices["ticker"] == ticker], column, price_type or "Adjusted close", percent=False),
        width="stretch",
    )


def show_risk(tickers: list[str], start: str, end: str) -> None:
    """Risk analysis: rolling volatility, drawdowns and risk/return profile."""
    st.subheader("Rolling volatility")
    window = st.segmented_control(
        "Window", ["20 observations", "60 observations"], default="20 observations", key="window"
    )
    column = "volatility_60d" if window == "60 observations" else "volatility_20d"
    volatility = load("rolling_volatility", start, end)
    volatility = volatility[volatility["ticker"].isin(tickers)].dropna(subset=[column])
    st.caption(
        "Annualised standard deviation of daily returns: ×√252 for equities and the index, "
        "×√365 for crypto, which trades every day."
    )
    st.altair_chart(
        line_chart(volatility, column, "Annualised volatility", percent=True),
        width="stretch",
    )

    profile = load("risk_profile", start, end).merge(
        load("maximum_drawdown", start, end), on="ticker", how="left"
    )
    profile = profile[profile["ticker"].isin(tickers)]

    left, right = st.columns(2)
    with left:
        st.subheader("Maximum drawdown")
        st.caption("Largest fall from a previous peak within the period.")
        bars = (
            alt.Chart(profile)
            .mark_bar()
            .encode(
                x=alt.X("maximum_drawdown:Q", title=None, axis=alt.Axis(format=".0%")),
                y=alt.Y("ticker:N", title=None, sort="x"),
                color=alt.Color("ticker:N", legend=None),
                tooltip=[
                    alt.Tooltip("ticker:N", title="Asset"),
                    alt.Tooltip("maximum_drawdown:Q", title="Drawdown", format=".2%"),
                    alt.Tooltip("peak_date:N", title="Peak"),
                    alt.Tooltip("trough_date:N", title="Trough"),
                ],
            )
            .properties(height=300)
        )
        st.altair_chart(bars, width="stretch")

    with right:
        st.subheader("Risk and return")
        st.caption("Annualised return against annualised volatility over the period.")
        points = (
            alt.Chart(profile)
            .mark_circle(size=120)
            .encode(
                x=alt.X("annualised_volatility:Q", title="Volatility", axis=alt.Axis(format=".0%")),
                y=alt.Y("annualised_return:Q", title="Return", axis=alt.Axis(format=".0%")),
                color=alt.Color("ticker:N", legend=None),
                tooltip=[
                    alt.Tooltip("ticker:N", title="Asset"),
                    alt.Tooltip("annualised_return:Q", title="Return", format=".2%"),
                    alt.Tooltip("annualised_volatility:Q", title="Volatility", format=".2%"),
                ],
            )
        )
        labels = points.mark_text(align="left", dx=9).encode(text="ticker:N")
        st.altair_chart((points + labels).properties(height=300), width="stretch")

    st.dataframe(
        profile[
            ["ticker", "observations", "total_return", "annualised_return",
             "annualised_volatility", "maximum_drawdown", "peak_date", "trough_date"]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "ticker": "Ticker",
            "observations": "Returns",
            "total_return": st.column_config.NumberColumn("Total return", format="percent"),
            "annualised_return": st.column_config.NumberColumn("Annualised return", format="percent"),
            "annualised_volatility": st.column_config.NumberColumn("Annualised volatility", format="percent"),
            "maximum_drawdown": st.column_config.NumberColumn("Max drawdown", format="percent"),
            "peak_date": "Peak",
            "trough_date": "Trough",
        },
    )


def show_correlation(tickers: list[str], start: str, end: str) -> None:
    """Correlation analysis: heatmap and pair table."""
    if len(tickers) < 2:
        st.info("Select at least two assets to compare correlations.")
        return

    pairs = load("correlations", start, end)
    pairs = pairs[pairs["ticker_x"].isin(tickers) & pairs["ticker_y"].isin(tickers)]
    matrix = metrics.to_correlation_matrix(pairs)

    st.subheader("Correlation of daily returns")
    st.caption(
        "Pearson correlation. Each pair uses only the dates on which both assets traded, "
        "so crypto weekend moves are folded into the following equity session."
    )
    cells = (
        matrix.rename_axis("ticker_x")
        .reset_index()
        .melt(id_vars="ticker_x", var_name="ticker_y", value_name="correlation")
    )
    base = alt.Chart(cells).encode(
        x=alt.X("ticker_x:N", title=None, sort=list(matrix.index)),
        y=alt.Y("ticker_y:N", title=None, sort=list(matrix.index)),
    )
    heatmap = base.mark_rect().encode(
        color=alt.Color(
            "correlation:Q",
            title="ρ",
            scale=alt.Scale(scheme="redblue", domain=[-1, 1]),
        ),
        tooltip=[
            alt.Tooltip("ticker_x:N", title="Asset"),
            alt.Tooltip("ticker_y:N", title="Asset"),
            alt.Tooltip("correlation:Q", title="Correlation", format=".2f"),
        ],
    )
    values = base.mark_text(fontSize=13).encode(
        text=alt.Text("correlation:Q", format=".2f"),
        color=alt.condition(
            "abs(datum.correlation) > 0.6", alt.value("white"), alt.value("black")
        ),
    )
    st.altair_chart((heatmap + values).properties(height=420), width="stretch")

    st.dataframe(
        pairs.sort_values("correlation", ascending=False),
        hide_index=True,
        width="stretch",
        column_config={
            "ticker_x": "Asset 1",
            "ticker_y": "Asset 2",
            "observations": "Paired returns",
            "correlation": st.column_config.NumberColumn("Correlation", format="%.3f"),
        },
    )


def main() -> None:
    """Build the page."""
    st.set_page_config(page_title="marketlens-sql", layout="wide")
    st.title("marketlens-sql")
    st.caption(
        "Historical market data analysed with SQL. Educational project, "
        "not investment advice."
    )

    if not settings.DATABASE_PATH.exists():
        st.warning("No database found. Run `python -m ingestion.update_database` first.")
        st.stop()

    today = dt.date.today().isoformat()
    overview = load("asset_overview", today, today)
    if overview["observations"].isna().all():
        st.warning("The database has no prices yet. Run `python -m ingestion.update_database`.")
        st.stop()
    overview = overview.dropna(subset=["observations"])

    tickers, start_date, end_date = select_filters(overview)
    if not tickers:
        st.info("Select at least one asset.")
        st.stop()
    start, end = start_date.isoformat(), end_date.isoformat()

    overview_at_end = load("asset_overview", start, end)
    overview_tab, performance_tab, risk_tab, correlation_tab = st.tabs(
        ["Overview", "Performance", "Risk", "Correlation"]
    )
    with overview_tab:
        show_overview(overview_at_end.dropna(subset=["latest_date"]), tickers, end_date)
    with performance_tab:
        show_performance(tickers, start, end)
    with risk_tab:
        show_risk(tickers, start, end)
    with correlation_tab:
        show_correlation(tickers, start, end)


main()
