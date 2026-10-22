from contextlib import nullcontext
from pathlib import Path

import psycopg
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import dashboard_data
from insights import OpeningRecord, PhaseStats
from time_insights import GroupStats, MonthResult, SpeedRecord

SCRIPT = str(Path(__file__).resolve().parent.parent / "src" / "dashboard.py")


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


def serve(monkeypatch, dashboard, calls=None):
    """Make the page read `dashboard` instead of a real database."""

    def fake_load(conn, include_ai=False, min_games=10):
        if calls is not None:
            calls.append(include_ai)
        return dashboard

    monkeypatch.setattr("db.connect", lambda url: nullcontext())
    monkeypatch.setattr(dashboard_data, "load_dashboard", fake_load)


def test_the_page_shows_a_title_metrics_and_five_tables(monkeypatch):
    serve(monkeypatch, sample())

    at = AppTest.from_file(SCRIPT).run()

    assert not at.exception
    assert at.title[0].value == "Chess Analyzer"
    assert len(at.tabs) == 5
    assert len(at.metric) == 4
    assert len(at.dataframe) == 5


def test_the_headline_metrics_show_the_dashboard_numbers(monkeypatch):
    serve(monkeypatch, sample())

    at = AppTest.from_file(SCRIPT).run()

    assert [m.value for m in at.metric] == ["10", "60.0%", "50 cp", "5.0%"]


def test_without_analysis_the_page_warns_and_shows_no_tables(monkeypatch):
    serve(monkeypatch, empty())

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


def test_the_checkbox_reaches_the_loader(monkeypatch):
    calls = []
    serve(monkeypatch, sample(), calls)

    at = AppTest.from_file(SCRIPT).run()
    at.sidebar.checkbox[0].check().run()

    assert calls == [False, True]
