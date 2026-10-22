"""Plotly figures built from the dashboard's tables. No Streamlit and no database here."""

import pandas as pd
import plotly.graph_objects as go

TEMPLATE = "plotly_white"
OPENINGS_SHOWN = 10


def _numbers(series: pd.Series) -> list[float | None]:
    """Plain floats for plotly. Missing values become None so a line breaks instead of bending."""
    return [None if pd.isna(value) else float(value) for value in series]


def _style(fig: go.Figure, title: str, y_title: str) -> go.Figure:
    fig.update_layout(
        title=title,
        yaxis_title=y_title,
        template=TEMPLATE,
        margin={"l": 20, "r": 20, "t": 50, "b": 20},
    )
    return fig


def fill_missing_months(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar month from the first to the last, empty months as missing values."""
    if frame.empty:
        return frame
    periods = pd.period_range(frame["Month"].min(), frame["Month"].max(), freq="M")
    every_month = pd.DataFrame({"Month": [str(period) for period in periods]})
    return every_month.merge(frame, on="Month", how="left")


def line_chart(
    frame: pd.DataFrame,
    y: str,
    title: str,
    y_title: str,
    y_range: tuple[float, float] | None = None,
) -> go.Figure:
    """A monthly line. Months with no games stay on the axis, and the line breaks there."""
    filled = fill_missing_months(frame)
    fig = go.Figure(
        go.Scatter(
            x=list(filled["Month"]),
            y=_numbers(filled[y]),
            mode="lines+markers",
            connectgaps=False,
        )
    )
    fig.update_xaxes(type="category")
    if y_range is not None:
        fig.update_yaxes(range=list(y_range))
    return _style(fig, title, y_title)


def bar_chart(frame: pd.DataFrame, x: str, y: str, title: str, y_title: str) -> go.Figure:
    """One bar per row, in the table's order."""
    fig = go.Figure(go.Bar(x=list(frame[x]), y=_numbers(frame[y])))
    return _style(fig, title, y_title)


def openings_chart(frame: pd.DataFrame, top: int = OPENINGS_SHOWN) -> go.Figure:
    """Score per opening for the most played ones, with the 50% line for reference."""
    rows = frame.head(top).iloc[::-1]  # horizontal bars draw bottom-up, so most played ends on top
    labels = [
        f"{opening} ({color})"
        for opening, color in zip(rows["Opening"], rows["Color"], strict=True)
    ]
    fig = go.Figure(go.Bar(x=_numbers(rows["Score %"]), y=labels, orientation="h"))
    fig.update_xaxes(range=[0, 100], title_text="Score %")
    fig.add_vline(x=50, line_dash="dot")
    return _style(fig, f"Score in your {len(rows)} most played openings", "")
