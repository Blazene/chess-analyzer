"""Plotly figures built from the dashboard's tables. No Streamlit and no database here."""

from html import escape
from textwrap import wrap

import pandas as pd
import plotly.graph_objects as go

OPENINGS_SHOWN = 10
PALETTES = {
    "dark": {
        "text": "#d6d3ce",
        "grid": "#38352f",
        "green": "#8ab85b",
        "on_green": "#161512",
        "amber": "#c6a16b",
        "surface": "#262421",
    },
    "light": {
        "text": "#45413c",
        "grid": "#dedad4",
        "green": "#527a32",
        "on_green": "#ffffff",
        "amber": "#98713e",
        "surface": "#ffffff",
    },
}


def _palette(theme: str | None) -> dict:
    """Follow the caller's Plotly template unless an explicit export theme was requested.

    Streamlit's template carries adaptive colors that its frontend resolves on theme changes.
    Reading the public template keeps these figures independent of Streamlit itself.
    """
    if theme is not None:
        return PALETTES[theme]
    colors = go.Figure().layout.template.layout.colorway or ("#8ab85b", "#c6a16b")
    return {
        "text": None,
        "grid": None,
        "surface": None,
        "green": colors[0],
        "amber": colors[1 % len(colors)],
    }


def _numbers(series: pd.Series) -> list[float | None]:
    """Plain floats for plotly. Missing values become None so a line breaks instead of bending."""
    return [None if pd.isna(value) else float(value) for value in series]


def _style(fig: go.Figure, title: str, y_title: str, theme: str | None) -> go.Figure:
    palette = _palette(theme)
    fig.update_layout(
        title={"text": title, "font": {"size": 15}, "x": 0},
        yaxis_title=y_title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Arial, sans-serif", "color": palette["text"], "size": 12},
        colorway=[palette["green"], palette["amber"]],
        hoverlabel={"bgcolor": palette["surface"], "font_color": palette["text"]},
        margin={"l": 12, "r": 20, "t": 55, "b": 12},
        height=340,
        bargap=0.5,
        showlegend=False,
        dragmode=False,
    )
    if theme is not None:
        fig.update_layout(template="plotly_dark" if theme == "dark" else "plotly_white")
    fig.update_xaxes(showgrid=False, title_text=None, automargin=True)
    fig.update_yaxes(gridcolor=palette["grid"], zeroline=False, automargin=True)
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
    *,
    theme: str | None = None,
) -> go.Figure:
    """A monthly line. Months with no games stay on the axis, and the line breaks there."""
    filled = fill_missing_months(frame)
    fig = go.Figure(
        go.Scatter(
            x=list(filled["Month"]),
            y=_numbers(filled[y]),
            mode="lines+markers",
            connectgaps=False,
            line={"color": _palette(theme)["green"], "width": 2.5},
            marker={"size": 6},
            hovertemplate=f"%{{x}}<br>%{{y:,.1f}} {escape(y_title)}<extra></extra>",
        )
    )
    fig.update_xaxes(type="category")
    if y_range is not None:
        fig.update_yaxes(range=list(y_range))
    return _style(fig, title, y_title, theme)


def bar_chart(
    frame: pd.DataFrame, x: str, y: str, title: str, y_title: str, *, theme: str | None = None
) -> go.Figure:
    """One bar per row, in the table's order."""
    color = _palette(theme)["amber" if y == "Blunder %" else "green"]
    fig = go.Figure(
        go.Bar(
            x=list(frame[x]),
            y=_numbers(frame[y]),
            marker_color=color,
            texttemplate="%{y:,.1f}" if "%" in y else "%{y:,.0f}",
            textposition="outside",
            cliponaxis=False,
            hovertemplate=f"%{{x}}<br>%{{y:,.1f}} {escape(y_title)}<extra></extra>",
        )
    )
    fig.update_yaxes(rangemode="tozero")
    if "%" in y:
        fig.update_yaxes(ticksuffix="%")
    if y == "Score %":
        fig.update_yaxes(range=[0, 100])
    return _style(fig, title, y_title, theme)


def openings_chart(
    frame: pd.DataFrame, top: int = OPENINGS_SHOWN, *, theme: str | None = None
) -> go.Figure:
    """Score per opening for the most played ones, with the 50% line for reference."""
    rows = frame.head(top).iloc[::-1]  # horizontal bars draw bottom-up, so most played ends on top
    labels = [
        f"{opening} ({color})"
        for opening, color in zip(rows["Opening"], rows["Color"], strict=True)
    ]
    palette = _palette(theme)
    fig = go.Figure(
        go.Bar(
            x=_numbers(rows["Score %"]),
            y=labels,
            orientation="h",
            marker_color=[
                palette["green" if score >= 50 else "amber"] for score in rows["Score %"]
            ],
            texttemplate="%{x:.1f}%",
            textposition="auto",
            hovertemplate="%{y}<br>Score: %{x:.1f}%<extra></extra>",
        )
    )
    _style(fig, f"Score in your {len(rows)} most played openings", "", theme)
    fig.update_xaxes(range=[0, 100], title_text="Score %", ticksuffix="%")
    fig.update_yaxes(
        showgrid=False,
        tickvals=labels,
        ticktext=["<br>".join(escape(line) for line in wrap(label, 26)) for label in labels],
    )
    fig.update_layout(height=max(340, len(rows) * 58 + 100), bargap=0.35)
    fig.add_vline(x=50, line_dash="dot", line_color=palette["text"] or "#9b968e", opacity=0.5)
    return fig
