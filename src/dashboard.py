"""The Chess Analyzer dashboard. Run it with: uv run streamlit run src/dashboard.py

A thin page: queries and table shaping live in dashboard_data.py, charts in charts.py,
and what counts as "your games" in filters.py.
"""

from datetime import date
from pathlib import Path

import psycopg
import streamlit as st

import charts
import dashboard_data as data
from filters import Filters

st.set_page_config(page_title="Chess Analyzer", page_icon="♞", layout="wide")
st.html(Path(__file__).with_name("dashboard.css"))

COLOR_CHOICES = ("Both", "White", "Black")
SPEED_LABELS = {"ultraBullet": "Ultra bullet"}


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


def reset_filters(options: data.Options) -> None:
    st.session_state.filter_include_ai = False
    st.session_state.filter_color = "Both"
    st.session_state.filter_speeds = list(options.speeds)
    if options.first_day is not None and options.last_day is not None:
        st.session_state.filter_dates = (options.first_day, options.last_day)


def sidebar_filters(options: data.Options) -> tuple:
    """Draw the filter widgets. Returns the arguments of load(), with None meaning no filter."""
    st.sidebar.subheader("Filter games")
    choice = st.sidebar.selectbox("Your color", COLOR_CHOICES, key="filter_color")
    speeds = st.sidebar.multiselect(
        "Time control",
        options.speeds,
        default=options.speeds,
        format_func=lambda speed: SPEED_LABELS.get(speed, speed.capitalize()),
        key="filter_speeds",
    )

    start = end = None
    if options.first_day is not None and options.last_day is not None:
        picked = st.sidebar.date_input(
            "Dates (UTC)",
            value=(options.first_day, options.last_day),
            min_value=options.first_day,
            max_value=options.last_day,
            key="filter_dates",
        )
        # While the second date is still being picked the widget returns one date, so ignore it.
        if isinstance(picked, tuple) and len(picked) == 2:
            start, end = picked
        if (start, end) == (options.first_day, options.last_day):
            start = end = None

    include_ai = st.sidebar.checkbox(
        "Include games against the computer", value=False, key="filter_include_ai"
    )
    st.sidebar.button("Reset filters", on_click=reset_filters, args=(options,), width="stretch")
    color = None if choice == "Both" else choice.lower()
    chosen = None if set(speeds) == set(options.speeds) else tuple(speeds)
    return include_ai, color, chosen, start, end


def percent(share: float | None) -> str:
    return "-" if share is None else f"{share:.1%}"


def show(frame, empty_message: str) -> None:
    if frame.empty:
        st.info(empty_message)
    else:
        st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            column_config={
                "Score %": st.column_config.ProgressColumn(
                    "Score %", min_value=0, max_value=100, format="%.1f%%"
                ),
                "Blunder %": st.column_config.NumberColumn(format="%.1f%%"),
                "Lost on time % of losses": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )


def chart(figure, key: str) -> None:
    st.plotly_chart(
        figure,
        key=key,
        width="stretch",
        theme="streamlit",
        config={"displayModeBar": False, "scrollZoom": False},
    )


def results_summary(dashboard: data.Dashboard) -> None:
    """A compact, labelled result bar using the same filtered games as the headline score."""
    results = [
        ("win", "Wins", sum(s.wins for s in dashboard.speeds)),
        ("draw", "Draws", sum(s.draws for s in dashboard.speeds)),
        ("loss", "Losses", sum(s.losses for s in dashboard.speeds)),
    ]
    label = ", ".join(f"{count:,} {name.lower()}" for _, name, count in results)
    segments = "".join(
        f'<span class="result-{kind}" style="flex: {count}"></span>' for kind, _, count in results
    )
    legend = "".join(
        f'<div class="result-key"><span class="result-dot result-{kind}"></span>'
        f"<span>{name}</span><strong>{count:,}</strong>"
        f'<span class="share">{count / dashboard.games:.0%}</span></div>'
        for kind, name, count in results
    )
    st.html(f'<div class="result-bar" role="img" aria-label="{label}">{segments}</div>{legend}')


st.sidebar.markdown("### ♞ Chess Analyzer")
st.sidebar.caption("A closer look at your Lichess games.")
st.sidebar.divider()
if st.sidebar.button("Reload data", icon=":material/refresh:", width="stretch"):
    st.cache_data.clear()

st.title("Chess Analyzer")
st.caption("Find patterns in your play. Make your next game a little better.")

try:
    options = load_options()
    selected = sidebar_filters(options)
    dashboard = load(*selected)
except psycopg.OperationalError:
    st.error(
        "The database is temporarily unavailable. It may be waking up. "
        "Try Reload data again in a moment."
    )
    st.stop()

if dashboard.run is None:
    st.warning("No games analyzed yet. Accuracy insights appear after an analysis is uploaded.")
else:
    run = dashboard.run
    st.sidebar.divider()
    st.sidebar.markdown("**About this analysis**")
    st.sidebar.caption(f"{run.engine_name} · Depth {run.depth}")
    st.sidebar.caption(f"{run.games_analyzed:,} games analyzed in the saved dataset.")
st.sidebar.caption("Saved results · Cached for 5 minutes. Reload to fetch the latest saved data.")

include_ai, color, chosen_speeds, start, end = selected
scope = ["Both colors" if color is None else f"Playing {color}"]
scope.append(
    "All time controls"
    if chosen_speeds is None
    else ", ".join(SPEED_LABELS.get(s, s.capitalize()) for s in chosen_speeds) or "No time controls"
)
first, last = start or options.first_day, end or options.last_day
if first is not None and last is not None:
    scope.append(f"{first:%d %b %Y} – {last:%d %b %Y}")
scope.append("Including computer games" if include_ai else "Human opponents")
st.caption(" · ".join(scope))

with st.container(key="headline-metrics"):
    columns = st.columns(4)
    columns[0].metric(
        "Games", f"{dashboard.games:,}", border=True, help="Games matching your current filters."
    )
    columns[1].metric(
        "Score",
        percent(dashboard.score),
        border=True,
        help="Wins plus half of draws, divided by games.",
    )
    avg_loss = dashboard.avg_loss_cp
    columns[2].metric(
        "Avg loss per move",
        "-" if avg_loss is None else f"{avg_loss:.0f} cp",
        border=True,
        help="Average centipawn loss across analyzed moves. 100 cp = one pawn. Lower is better.",
    )
    columns[3].metric(
        "Blunder rate",
        percent(dashboard.blunder_rate),
        border=True,
        help="The share of your analyzed moves labelled a blunder. Lower is better.",
    )

if dashboard.games == 0:
    st.info(
        "No games match these filters. Try Reset filters or a wider date range."
        if options.speeds
        else "No games have been imported yet."
    )
    st.stop()

overview, openings, speeds, clock, trend = st.tabs(
    ["Overview", "Openings", "Time control", "Clock", "Trend"]
)

phases_table = data.phases_frame(dashboard.phases)
openings_table = data.openings_frame(dashboard.openings)
speeds_table = data.speeds_frame(dashboard.speeds, dashboard.speed_stats)
clock_table = data.clock_frame(dashboard.clock)
months_table = data.months_frame(dashboard.months, dashboard.month_stats)

with overview:
    st.subheader("The shape of your game")
    st.caption("See where points slip away, from the opening to the endgame.")
    accuracy, results = st.columns([1.65, 1], gap="medium")
    with accuracy, st.container(border=True):
        if not phases_table.empty:
            chart(
                charts.bar_chart(
                    phases_table,
                    "Phase",
                    "Avg loss (cp)",
                    "Average loss per move by phase",
                    "centipawns",
                ),
                "phase",
            )
        else:
            st.info("No analyzed moves yet.")
    with results, st.container(border=True):
        st.markdown("#### Game results")
        results_summary(dashboard)
        if dashboard.phases:
            costly = max(dashboard.phases, key=lambda phase: phase.avg_loss_cp)
            st.divider()
            st.markdown(f"**Highest average loss: {costly.phase.capitalize()}**")
            st.caption(f"{costly.avg_loss_cp:.0f} cp per move · {costly.moves:,} analyzed moves")
    with st.expander("View game phase data"):
        show(phases_table, "No analyzed moves yet.")

with openings:
    st.subheader("Your opening repertoire")
    st.caption(
        f"Opening families with at least {data.MIN_GAMES} games. The dotted line marks a 50% score."
    )
    if not openings_table.empty:
        with st.container(border=True):
            chart(charts.openings_chart(openings_table), "openings")
    else:
        st.info("No opening has enough games yet. Try widening your filters.")
    with st.expander("View opening data"):
        show(openings_table, "No opening has enough games yet.")

with speeds:
    st.subheader("Find your rhythm")
    st.caption("Compare your results across time controls. Score counts a draw as half a win.")
    if not speeds_table.empty:
        title = "Score by time control"
        with st.container(border=True):
            chart(
                charts.bar_chart(speeds_table, "Speed", "Score %", title, "score %"),
                "speeds",
            )
    with st.expander("View time control data"):
        show(speeds_table, "No games yet.")

with clock:
    st.subheader("Under time pressure")
    st.caption("Blunders by time left on your clock after each move. Lower is better.")
    if not clock_table.empty:
        title = "Blunder rate by time left"
        with st.container(border=True):
            chart(
                charts.bar_chart(clock_table, "Time left", "Blunder %", title, "blunder %"),
                "clock",
            )
    else:
        st.info("No moves with a recorded clock match these filters.")
    with st.expander("View clock data"):
        show(clock_table, "No moves with a recorded clock.")

with trend:
    st.subheader("Your progress, over time")
    st.caption("Monthly results in UTC. Months without games stay as gaps, not connecting lines.")
    if not months_table.empty:
        with st.container(border=True):
            chart(
                charts.line_chart(months_table, "Score %", "Score by month", "score %", (0, 100)),
                "trend-score",
            )
        rating, loss = st.columns(2, gap="medium")
        with rating, st.container(border=True):
            chart(
                charts.line_chart(months_table, "Avg rating", "Average rating", "rating"),
                "trend-rating",
            )
        with loss, st.container(border=True):
            chart(
                charts.line_chart(months_table, "Avg loss (cp)", "Average loss per move", "cp"),
                "trend-loss",
            )
    with st.expander("View monthly data"):
        show(months_table, "No games yet.")

st.divider()
st.caption(
    "Score = wins + ½ draws. Accuracy uses analyzed moves only. "
    "100 centipawns (cp) = one pawn. Lower loss and blunder rates are better."
)
