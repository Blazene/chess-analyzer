"""The Chess Analyzer dashboard. Run it with: uv run streamlit run src/dashboard.py

A thin page: all queries and table shaping live in dashboard_data.py.
"""

import psycopg
import streamlit as st

import dashboard_data as data

st.set_page_config(page_title="Chess Analyzer", layout="wide")


@st.cache_data(ttl=300, show_spinner="Reading your games...")
def load(include_ai: bool) -> data.Dashboard:
    """A fresh connection per load (nothing long-lived to go stale), cached for 5 minutes."""
    from config import DATABASE_URL
    from db import connect

    with connect(DATABASE_URL) as conn:
        return data.load_dashboard(conn, include_ai)


def percent(share: float | None) -> str:
    return "-" if share is None else f"{share:.1%}"


def show(frame, empty_message: str) -> None:
    if frame.empty:
        st.info(empty_message)
    else:
        st.dataframe(frame, hide_index=True)


st.title("Chess Analyzer")

include_ai = st.sidebar.checkbox("Include games against the computer", value=False)
if st.sidebar.button("Reload data"):
    st.cache_data.clear()

try:
    dashboard = load(include_ai)
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

with overview:
    st.subheader("Your moves by game phase")
    show(data.phases_frame(dashboard.phases), "No analyzed moves yet.")

with openings:
    st.caption(f"Opening families with at least {data.MIN_GAMES} games. Score = wins + half draws.")
    show(data.openings_frame(dashboard.openings), "No opening has enough games yet.")

with speeds:
    show(data.speeds_frame(dashboard.speeds, dashboard.speed_stats), "No games yet.")

with clock:
    st.caption("Your moves grouped by the time left on your clock after the move.")
    show(data.clock_frame(dashboard.clock), "No moves with a recorded clock.")

with trend:
    st.caption("By month (UTC). Months with no games are not listed.")
    show(data.months_frame(dashboard.months, dashboard.month_stats), "No games yet.")
