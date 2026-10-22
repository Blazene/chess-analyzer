"""The Chess Analyzer dashboard. Run it with: uv run streamlit run src/dashboard.py

A thin page: queries and table shaping live in dashboard_data.py, charts in charts.py,
and what counts as "your games" in filters.py.
"""

from datetime import date

import psycopg
import streamlit as st

import charts
import dashboard_data as data
from filters import Filters

st.set_page_config(page_title="Chess Analyzer", layout="wide")

COLOR_CHOICES = ("Both", "White", "Black")


@st.cache_data(ttl=300, show_spinner="Reading your games...")
def load(
    include_ai: bool,
    color: str | None,
    speeds: tuple[str, ...] | None,
    start: date | None,
    end: date | None,
) -> data.Dashboard:
    """A fresh connection per load (nothing long-lived to go stale), cached for 5 minutes."""
    from config import DATABASE_URL
    from db import connect

    filters = Filters(include_ai=include_ai, color=color, speeds=speeds, start=start, end=end)
    with connect(DATABASE_URL) as conn:
        return data.load_dashboard(conn, filters)


@st.cache_data(ttl=300)
def load_options() -> data.Options:
    from config import DATABASE_URL
    from db import connect

    with connect(DATABASE_URL) as conn:
        return data.load_options(conn)


def sidebar_filters(options: data.Options) -> tuple:
    """Draw the filter widgets. Returns the arguments of load(), with None meaning no filter."""
    include_ai = st.sidebar.checkbox("Include games against the computer", value=False)
    choice = st.sidebar.selectbox("Your color", COLOR_CHOICES)
    speeds = st.sidebar.multiselect("Time control", options.speeds, default=options.speeds)

    start = end = None
    if options.first_day is not None and options.last_day is not None:
        picked = st.sidebar.date_input(
            "Dates (UTC)",
            value=(options.first_day, options.last_day),
            min_value=options.first_day,
            max_value=options.last_day,
        )
        # While the second date is still being picked the widget returns one date, so ignore it.
        if isinstance(picked, tuple) and len(picked) == 2:
            start, end = picked
        if (start, end) == (options.first_day, options.last_day):
            start = end = None

    color = None if choice == "Both" else choice.lower()
    chosen = None if set(speeds) == set(options.speeds) else tuple(speeds)
    return include_ai, color, chosen, start, end


def percent(share: float | None) -> str:
    return "-" if share is None else f"{share:.1%}"


def show(frame, empty_message: str) -> None:
    if frame.empty:
        st.info(empty_message)
    else:
        st.dataframe(frame, hide_index=True)


def chart(figure, key: str) -> None:
    st.plotly_chart(figure, key=key)


st.title("Chess Analyzer")

if st.sidebar.button("Reload data"):
    st.cache_data.clear()

try:
    options = load_options()
    dashboard = load(*sidebar_filters(options))
except psycopg.OperationalError:
    st.error("Cannot reach the database. Is Docker running, and is DATABASE_URL correct?")
    st.stop()

if dashboard.run is None:
    st.warning("No games analyzed yet. Run: uv run python src/batch.py --workers 6")
else:
    run = dashboard.run
    st.caption(f"{run.engine_name}, depth {run.depth} - {run.games_analyzed:,} games analyzed")

columns = st.columns(4)
columns[0].metric("Games", f"{dashboard.games:,}")
columns[1].metric("Score", percent(dashboard.score))
avg_loss = dashboard.avg_loss_cp
columns[2].metric("Avg loss per move", "-" if avg_loss is None else f"{avg_loss:.0f} cp")
columns[3].metric("Blunder rate", percent(dashboard.blunder_rate))

overview, openings, speeds, clock, trend = st.tabs(
    ["Overview", "Openings", "Time control", "Clock", "Trend"]
)

phases_table = data.phases_frame(dashboard.phases)
openings_table = data.openings_frame(dashboard.openings)
speeds_table = data.speeds_frame(dashboard.speeds, dashboard.speed_stats)
clock_table = data.clock_frame(dashboard.clock)
months_table = data.months_frame(dashboard.months, dashboard.month_stats)

with overview:
    st.subheader("Your moves by game phase")
    show(phases_table, "No analyzed moves yet.")
    if not phases_table.empty:
        title = "Average loss per move by phase"
        chart(
            charts.bar_chart(phases_table, "Phase", "Avg loss (cp)", title, "centipawns"), "phase"
        )

with openings:
    st.caption(f"Opening families with at least {data.MIN_GAMES} games. Score = wins + half draws.")
    show(openings_table, "No opening has enough games yet.")
    if not openings_table.empty:
        chart(charts.openings_chart(openings_table), "openings")

with speeds:
    show(speeds_table, "No games yet.")
    if not speeds_table.empty:
        title = "Score by time control"
        chart(charts.bar_chart(speeds_table, "Speed", "Score %", title, "score %"), "speeds")

with clock:
    st.caption("Your moves grouped by the time left on your clock after the move.")
    show(clock_table, "No moves with a recorded clock.")
    if not clock_table.empty:
        title = "Blunder rate by time left"
        chart(charts.bar_chart(clock_table, "Time left", "Blunder %", title, "blunder %"), "clock")

with trend:
    st.caption("By month (UTC). A month with no games is a gap in the line.")
    show(months_table, "No games yet.")
    if not months_table.empty:
        score = charts.line_chart(months_table, "Score %", "Score by month", "score %", (0, 100))
        rating = charts.line_chart(months_table, "Avg rating", "Average rating", "rating")
        loss = charts.line_chart(months_table, "Avg loss (cp)", "Average loss per move", "cp")
        chart(score, "trend-score")
        chart(rating, "trend-rating")
        chart(loss, "trend-loss")
