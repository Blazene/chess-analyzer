import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from pathlib import Path

import psycopg
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import dashboard_data
from filters import Filters
from insights import OpeningRecord, PhaseStats
from time_insights import GroupStats, MonthResult, SpeedRecord

SCRIPT = str(Path(__file__).resolve().parent.parent / "src" / "dashboard.py")

SPEEDS_ONLY = dashboard_data.Options(["blitz", "rapid"], None, None)
WITH_DATES = dashboard_data.Options(["blitz", "rapid"], date(2024, 1, 1), date(2024, 3, 1))


@pytest.fixture(autouse=True)
def fresh_cache():
    """The page caches its data, so every test starts with an empty cache."""
    st.cache_data.clear()


def sample() -> dashboard_data.Dashboard:
    return dashboard_data.Dashboard(
        run=dashboard_data.RunInfo(1, "Stockfish 19", 14, 10),
        openings=[OpeningRecord("white", "Italian Game", 10, 6, 0, 4)],
        phases=[PhaseStats("opening", 100, 5000, 5)],
        speeds=[SpeedRecord("blitz", 10, 6, 0, 4, 1, 0)],
        speed_stats=[GroupStats("blitz", 100, 5000, 5)],
        clock=[GroupStats("<10s", 20, 3000, 4)],
        months=[MonthResult("2024-01", 10, 6, 0, 4, 10000, 10)],
        month_stats=[GroupStats("2024-01", 100, 5000, 5)],
    )


def empty() -> dashboard_data.Dashboard:
    return dashboard_data.Dashboard(
        run=None,
        openings=[],
        phases=[],
        speeds=[],
        speed_stats=[],
        clock=[],
        months=[],
        month_stats=[],
    )


def serve(monkeypatch, dashboard, options=SPEEDS_ONLY, calls=None):
    """Make the page read `dashboard` and `options` instead of a real database."""

    def fake_load(conn, filters=None, min_games=10):
        if calls is not None:
            calls.append(filters)
        return dashboard

    monkeypatch.setattr("db.connect", lambda url: nullcontext())
    monkeypatch.setattr(dashboard_data, "load_dashboard", fake_load)
    monkeypatch.setattr(dashboard_data, "load_options", lambda conn: options)


def test_the_page_shows_a_title_metrics_tables_and_charts(monkeypatch):
    serve(monkeypatch, sample())

    at = AppTest.from_file(SCRIPT).run()

    assert not at.exception
    assert at.title[0].value == "Chess Analyzer"
    assert len(at.tabs) == 5
    assert len(at.metric) == 4
    assert len(at.dataframe) == 5
    assert len(at.get("plotly_chart")) == 7


def test_the_headline_metrics_show_the_dashboard_numbers(monkeypatch):
    serve(monkeypatch, sample())

    at = AppTest.from_file(SCRIPT).run()

    assert [m.value for m in at.metric] == ["10", "60.0%", "50 cp", "5.0%"]


def test_without_analysis_the_page_warns_and_shows_no_tables(monkeypatch):
    serve(monkeypatch, empty(), dashboard_data.Options([], None, None))

    at = AppTest.from_file(SCRIPT).run()

    assert not at.exception
    assert len(at.warning) == 1
    assert len(at.dataframe) == 0
    assert [m.value for m in at.metric] == ["0", "-", "-", "-"]


def test_an_unreachable_database_shows_an_error_not_a_crash(monkeypatch):
    def refuse(url):
        raise psycopg.OperationalError("down")

    monkeypatch.setattr("db.connect", refuse)

    at = AppTest.from_file(SCRIPT).run()

    assert not at.exception
    assert len(at.error) == 1
    assert len(at.metric) == 0


def test_no_filters_are_applied_by_default(monkeypatch):
    calls = []
    serve(monkeypatch, sample(), WITH_DATES, calls)

    AppTest.from_file(SCRIPT).run()

    assert calls == [Filters()]


def test_the_checkbox_reaches_the_loader(monkeypatch):
    calls = []
    serve(monkeypatch, sample(), calls=calls)

    at = AppTest.from_file(SCRIPT).run()
    at.sidebar.checkbox[0].check().run()

    assert [c.include_ai for c in calls] == [False, True]


def test_the_color_choice_reaches_the_loader(monkeypatch):
    calls = []
    serve(monkeypatch, sample(), calls=calls)

    at = AppTest.from_file(SCRIPT).run()
    at.sidebar.selectbox[0].select("Black").run()

    assert [c.color for c in calls] == [None, "black"]


def test_unselecting_a_time_control_reaches_the_loader(monkeypatch):
    calls = []
    serve(monkeypatch, sample(), calls=calls)

    at = AppTest.from_file(SCRIPT).run()
    at.sidebar.multiselect[0].unselect("rapid").run()

    assert [c.speeds for c in calls] == [None, ("blitz",)]


def test_the_result_summary_uses_the_same_games_as_the_headline_metrics(monkeypatch):
    serve(monkeypatch, sample())

    at = AppTest.from_file(SCRIPT).run()
    html = "\n".join(node.proto.body for node in at.get("html"))

    assert 'aria-label="6 wins, 0 draws, 4 losses"' in html
    assert '<span class="share">60%</span>' in html
    assert '<span class="share">0%</span>' in html
    assert '<span class="share">40%</span>' in html


def test_the_highest_loss_phase_is_derived_from_the_filtered_analysis(monkeypatch):
    dashboard = replace(
        sample(),
        phases=[PhaseStats("opening", 100, 5000, 5), PhaseStats("endgame", 20, 3000, 3)],
    )
    serve(monkeypatch, dashboard)

    at = AppTest.from_file(SCRIPT).run()

    assert "**Highest average loss: Endgame**" in [item.value for item in at.markdown]
    assert "150 cp per move · 20 analyzed moves" in [item.value for item in at.caption]


def test_reset_filters_restores_every_default_including_the_date_range(monkeypatch):
    serve(monkeypatch, sample(), WITH_DATES)
    at = AppTest.from_file(SCRIPT).run()
    at.sidebar.selectbox[0].select("Black")
    at.sidebar.multiselect[0].unselect("rapid")
    at.sidebar.checkbox[0].check()
    at.sidebar.date_input[0].set_value((date(2024, 2, 1), date(2024, 2, 20)))
    at.run()

    next(button for button in at.sidebar.button if button.label == "Reset filters").click().run()

    assert not at.exception
    assert at.sidebar.selectbox[0].value == "Both"
    assert at.sidebar.multiselect[0].value == ["blitz", "rapid"]
    assert at.sidebar.checkbox[0].value is False
    assert at.sidebar.date_input[0].value == (WITH_DATES.first_day, WITH_DATES.last_day)


def test_reset_filters_also_works_without_dates(monkeypatch):
    serve(monkeypatch, sample())
    at = AppTest.from_file(SCRIPT).run()
    at.sidebar.selectbox[0].select("White").run()

    next(button for button in at.sidebar.button if button.label == "Reset filters").click().run()

    assert not at.exception
    assert at.sidebar.selectbox[0].value == "Both"


def test_active_filters_are_visible_above_the_metrics(monkeypatch):
    serve(monkeypatch, sample(), WITH_DATES)
    at = AppTest.from_file(SCRIPT).run()
    at.sidebar.selectbox[0].select("Black")
    at.sidebar.multiselect[0].unselect("rapid")
    at.sidebar.checkbox[0].check()
    at.sidebar.date_input[0].set_value((date(2024, 2, 1), date(2024, 2, 20)))
    at.run()

    assert "Playing black · Blitz · 01 Feb 2024 – 20 Feb 2024 · Including computer games" in [
        item.value for item in at.caption
    ]


def test_no_matching_games_has_a_recoverable_empty_state(monkeypatch):
    serve(monkeypatch, replace(empty(), run=sample().run))

    at = AppTest.from_file(SCRIPT).run()

    assert not at.exception
    assert any("Reset filters" in item.value for item in at.info)
    assert not at.get("plotly_chart")
    assert [m.value for m in at.metric] == ["0", "-", "-", "-"]


def test_games_without_analysis_still_show_results_and_trends(monkeypatch):
    dashboard = replace(sample(), run=None, phases=[], speed_stats=[], clock=[], month_stats=[])
    serve(monkeypatch, dashboard)

    at = AppTest.from_file(SCRIPT).run()

    assert not at.exception
    assert [m.value for m in at.metric] == ["10", "60.0%", "-", "-"]
    assert len(at.get("plotly_chart")) == 5
    assert not any("Highest average loss" in item.value for item in at.markdown)


def test_clearing_all_time_controls_does_not_mean_all_time_controls(monkeypatch):
    calls = []
    serve(monkeypatch, sample(), calls=calls)
    at = AppTest.from_file(SCRIPT).run()

    at.sidebar.multiselect[0].set_value([]).run()

    assert not at.exception
    assert calls[-1].speeds == ()
    assert any("No time controls" in item.value for item in at.caption)


def test_reload_discards_the_cached_dashboard_and_options(monkeypatch):
    calls = []
    serve(monkeypatch, sample(), calls=calls)
    at = AppTest.from_file(SCRIPT).run()

    next(button for button in at.sidebar.button if button.label == "Reload data").click().run()

    assert not at.exception
    assert calls == [Filters(), Filters()]


def test_charts_follow_native_theme_changes_without_needing_a_python_rerun(monkeypatch):
    serve(monkeypatch, sample())

    at = AppTest.from_file(SCRIPT).run()

    for node in at.get("plotly_chart"):
        assert node.proto.theme == "streamlit"
        layout = json.loads(node.proto.spec)["layout"]
        assert "color" not in layout["font"]
        assert "gridcolor" not in layout["yaxis"]
