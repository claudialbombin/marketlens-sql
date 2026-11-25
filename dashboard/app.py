"""Streamlit dashboard for the marketlens-sql database.

Run from the project root:
    streamlit run dashboard/app.py

Every number shown here comes from the SQL files in database/queries/,
executed through analysis.metrics. The dashboard only filters, reshapes and
plots those results. The plain-language summaries under each chart only pick
out the highest and lowest of those values.
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

GLOSSARY = """
**Return**: how much an investment gained or lost, as a percentage. +25% means that
100 dollars became 125. Prices are adjusted for dividends and splits, so dividends are
counted as if they had been reinvested.

**Volatility**: how much the price jumps around from one day to the next, scaled to a
full year. Higher volatility means a bumpier ride and a wider range of possible outcomes.
It says nothing about whether the price went up or down.

**Drawdown**: the fall from the highest price reached so far to a later low. The
maximum drawdown is the worst of these falls: what someone who bought at the top would
have lost at the worst moment.

**Correlation**: whether two assets tend to rise and fall on the same days, from −1
(always opposite) through 0 (unrelated) to +1 (always together).

**The assets**: the S&P 500 is an index of the 500 largest US companies and acts as the
benchmark for "the market". Apple (technology), JPMorgan Chase (banking), Exxon Mobil
(oil and gas) and Johnson & Johnson (healthcare) are single companies from different
sectors. Bitcoin and Ether are cryptocurrencies, which trade every day including weekends.
"""


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


def explain(how_to_read: str, summary: str | None = None) -> None:
    """Show a collapsible reading guide and, when available, a data summary."""
    with st.expander("How to read this chart"):
        st.markdown(how_to_read)
    if summary:
        st.markdown(f"**In this period:** {summary}")


def describe_extremes(data: pd.DataFrame, column: str, fmt: str) -> tuple[str, str] | None:
    """Return 'TICKER (value)' for the highest and lowest value of a column."""
    valid = data.dropna(subset=[column])
    if len(valid) < 2:
        return None
    highest = valid.loc[valid[column].idxmax()]
    lowest = valid.loc[valid[column].idxmin()]
    return (
        f"{highest['ticker']} ({highest[column]:{fmt}})",
        f"{lowest['ticker']} ({lowest[column]:{fmt}})",
    )


def correlation_strength(value: float) -> str:
    """Describe a correlation coefficient in words."""
    size = abs(value)
    if size < 0.2:
        return "were almost unrelated"
    degree = "weakly" if size < 0.5 else "clearly" if size < 0.75 else "very closely"
    return f"moved {degree} together" if value > 0 else f"moved {degree} in opposite directions"


def show_overview(overview: pd.DataFrame, tickers: list[str], end_date: dt.date) -> None:
    """Market overview: asset list, coverage and latest prices."""
    with st.expander("New to finance? Start here", expanded=True):
        st.markdown(GLOSSARY)
        st.markdown(
            "Use the filters in the sidebar to choose assets and a period. Every tab "
            "recalculates its figures for your selection, and each chart has a "
            "*How to read this chart* note."
        )

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
    st.caption(
        "The small coloured figure is the change from the previous trading session: "
        "green for a rise, red for a fall."
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
            "observations": st.column_config.NumberColumn(
                "Observations", help="Number of daily prices stored for the asset."
            ),
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
    final = cumulative.sort_values("date").groupby("ticker", as_index=False).last()
    extremes = describe_extremes(final, "cumulative_return", "+.1%")
    explain(
        "Each line answers the question *if I had invested at the start of the period, how "
        "much would I have gained or lost by this date?* A line at +50% means 100 dollars "
        "had become 150; a line at −20% means they had shrunk to 80. Lines above the "
        "S&P 500 did better than the market over the same days. Hover over the chart to "
        "read exact values.",
        f"{extremes[0]} did best and {extremes[1]} did worst." if extremes else None,
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
    explain(
        "This is the price itself rather than the percentage change. **Adjusted close** "
        "corrects past prices for dividends and stock splits, so that the line reflects what "
        "an investor actually earned; it is the price used in every calculation. **Close** "
        "is the price that was actually quoted on each day. The two differ most for "
        "companies that pay large dividends, such as XOM or JNJ."
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
    latest = volatility.sort_values("date").groupby("ticker", as_index=False).last()
    extremes = describe_extremes(latest, column, ".1%")
    explain(
        "Each point measures how much the price moved during the previous 20 (or 60) "
        "trading days, expressed per year. As a rough guide, a volatility of 20% means "
        "that a typical year ends within about 20% above or below the average outcome. "
        "When a line jumps, the market was going through a stressful period, such as the "
        "start of the pandemic in March 2020. The 20-observation window reacts quickly; "
        "the 60-observation window is smoother. The line starts once the window is full.",
        f"at the end of the period, {extremes[0]} was the most volatile and "
        f"{extremes[1]} the calmest." if extremes else None,
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
        worst = describe_extremes(profile, "maximum_drawdown", ".1%")
        explain(
            "The longer the bar, the deeper the worst fall. −30% means that, at the worst "
            "moment, 100 dollars invested at the peak were worth 70. Losses are harder to "
            "undo than they look: after a 50% fall the price has to double to recover. "
            "Hover over a bar to see the dates of the peak and the low.",
            f"the deepest fall was {worst[1]} and the mildest {worst[0]}." if worst else None,
        )

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
        returns = describe_extremes(profile, "annualised_return", "+.1%")
        risk = describe_extremes(profile, "annualised_volatility", ".1%")
        explain(
            "Each dot is one asset. Further right means a bumpier ride; higher up means a "
            "better yearly return. Dots towards the top left earned more for each unit of "
            "risk taken. An index spread over 500 companies usually sits furthest to the "
            "left, because the ups and downs of single companies partly cancel out.",
            f"highest yearly return: {returns[0]}; lowest volatility: {risk[1]}."
            if returns and risk else None,
        )

    st.dataframe(
        profile[
            ["ticker", "observations", "total_return", "annualised_return",
             "annualised_volatility", "maximum_drawdown", "peak_date", "trough_date"]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "ticker": "Ticker",
            "observations": st.column_config.NumberColumn(
                "Returns", help="Number of daily returns in the period."
            ),
            "total_return": st.column_config.NumberColumn(
                "Total return", format="percent", help="Gain or loss over the whole period."
            ),
            "annualised_return": st.column_config.NumberColumn(
                "Annualised return",
                format="percent",
                help="The steady yearly rate that would give the same total return. "
                "Over periods shorter than a year it is an extrapolation.",
            ),
            "annualised_volatility": st.column_config.NumberColumn(
                "Annualised volatility",
                format="percent",
                help="Volatility of daily returns over the whole period, scaled to a year.",
            ),
            "maximum_drawdown": st.column_config.NumberColumn(
                "Max drawdown", format="percent", help="Worst fall from a previous high."
            ),
            "peak_date": st.column_config.TextColumn("Peak", help="Date of the high before the worst fall."),
            "trough_date": st.column_config.TextColumn("Trough", help="Date of the lowest point of that fall."),
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
    valid = pairs.dropna(subset=["correlation"])
    summary = None
    if not valid.empty:
        strongest = valid.loc[valid["correlation"].idxmax()]
        weakest = valid.loc[valid["correlation"].idxmin()]
        summary = (
            f"{strongest['ticker_x']} and {strongest['ticker_y']} "
            f"{correlation_strength(strongest['correlation'])} ({strongest['correlation']:.2f})"
        )
        if len(valid) > 1:
            summary += (
                f"; at the other end, {weakest['ticker_x']} and {weakest['ticker_y']} "
                f"{correlation_strength(weakest['correlation'])} ({weakest['correlation']:.2f})"
            )
        summary += "."
    explain(
        "Find one asset on each axis: the cell where they meet says how closely their daily "
        "movements are linked. Blue cells move together, red cells tend to move in opposite "
        "directions, and pale cells are largely unrelated. The diagonal is always 1, because "
        "every asset moves exactly with itself.\n\n"
        "**Why it matters:** combining assets that do not move together makes a portfolio's "
        "ups and downs smaller, because a fall in one is often offset by another. This is the "
        "idea behind diversification. Correlation measures how often assets move together, "
        "not how much they gain.",
        summary,
    )

    st.dataframe(
        pairs.sort_values("correlation", ascending=False),
        hide_index=True,
        width="stretch",
        column_config={
            "ticker_x": "Asset 1",
            "ticker_y": "Asset 2",
            "observations": st.column_config.NumberColumn(
                "Paired returns", help="Number of dates on which both assets traded."
            ),
            "correlation": st.column_config.NumberColumn(
                "Correlation", format="%.3f", help="From −1 (opposite) to +1 (together)."
            ),
        },
    )


def main() -> None:
    """Build the page."""
    st.set_page_config(page_title="marketlens-sql", layout="wide")
    st.title("marketlens-sql")
    st.caption(
        "Historical market data analysed with SQL. Past performance does not indicate "
        "future results. Educational project, not investment advice."
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
