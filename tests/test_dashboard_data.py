import pandas as pd
from time_helpers import add_timed_game, mv

from dashboard_data import (
    Dashboard,
    RunInfo,
    clock_frame,
    latest_run,
    load_dashboard,
    months_frame,
    openings_frame,
    phases_frame,
    speeds_frame,
)
from db import get_or_create_run
from insights import OpeningRecord, PhaseStats
from time_insights import GroupStats, MonthResult, SpeedRecord


def run_for(db, depth=5):
    return get_or_create_run(db, "Fake 1", depth)


def analyzed_game(db, run_id, **kwargs):
    """A game of two white moves: 300 cp lost on a blunder, then 100 cp lost on a mistake."""
    moves = [mv(1, 500, 300, "blunder"), mv(3, 20000, 100, "mistake")]
    return add_timed_game(db, run_id, moves=moves, **kwargs)


def empty_dashboard(**overrides):
    parts = dict(
        run=None,
        openings=[],
        phases=[],
        speeds=[],
        speed_stats=[],
        clock=[],
        months=[],
        month_stats=[],
    )
    return Dashboard(**{**parts, **overrides})


# ---------- choosing the run ----------


def test_no_analysis_means_no_latest_run(db):
    assert latest_run(db) is None


def test_a_run_without_move_losses_is_not_the_latest_run(db):
    run_for(db)

    assert latest_run(db) is None


def test_latest_run_is_the_one_with_most_games_analyzed(db):
    small, large = run_for(db, 5), run_for(db, 6)
    analyzed_game(db, small)
    analyzed_game(db, large)
    analyzed_game(db, large)

    assert latest_run(db).run_id == large


def test_a_tie_goes_to_the_newest_run(db):
    older, newer = run_for(db, 5), run_for(db, 6)
    analyzed_game(db, older)
    analyzed_game(db, newer)

    assert latest_run(db).run_id == newer


def test_latest_run_describes_the_run(db):
    run_id = run_for(db, 7)
    analyzed_game(db, run_id)
    analyzed_game(db, run_id)

    assert latest_run(db) == RunInfo(run_id, "Fake 1", 7, 2)


# ---------- loading everything ----------


def test_without_analysis_results_load_but_accuracy_is_empty(db):
    add_timed_game(db)

    dashboard = load_dashboard(db, min_games=1)

    assert dashboard.run is None
    assert dashboard.games == 1
    assert len(dashboard.speeds) == 1
    assert len(dashboard.months) == 1
    assert [o.opening for o in dashboard.openings] == ["Unknown"]
    assert dashboard.phases == []
    assert dashboard.speed_stats == []
    assert dashboard.clock == []
    assert dashboard.month_stats == []


def test_with_analysis_every_section_is_filled(db):
    run_id = run_for(db)
    analyzed_game(db, run_id)

    dashboard = load_dashboard(db)

    assert dashboard.run == RunInfo(run_id, "Fake 1", 5, 1)
    assert dashboard.analyzed_moves == 2
    assert dashboard.avg_loss_cp == 200
    assert dashboard.blunder_rate == 0.5
    assert [s.key for s in dashboard.clock] == ["<10s", "3 min+"]
    assert len(dashboard.speed_stats) == 1
    assert len(dashboard.month_stats) == 1


def test_the_computer_is_excluded_unless_asked(db):
    add_timed_game(db, opponent_is_ai=True)

    assert load_dashboard(db).games == 0
    assert load_dashboard(db, include_ai=True).games == 1


def test_the_opening_minimum_is_passed_through(db):
    add_timed_game(db)

    assert load_dashboard(db).openings == []
    assert len(load_dashboard(db, min_games=1).openings) == 1


# ---------- headline numbers ----------


def test_headline_numbers():
    dashboard = empty_dashboard(
        speeds=[SpeedRecord("blitz", 4, 3, 0, 1, 0, 0)],
        phases=[PhaseStats("opening", 10, 1000, 2), PhaseStats("endgame", 10, 3000, 3)],
    )

    assert dashboard.games == 4
    assert dashboard.score == 0.75
    assert dashboard.analyzed_moves == 20
    assert dashboard.avg_loss_cp == 200
    assert dashboard.blunder_rate == 0.25


def test_headline_numbers_are_none_without_data():
    dashboard = empty_dashboard()

    assert dashboard.games == 0
    assert dashboard.analyzed_moves == 0
    assert dashboard.score is None
    assert dashboard.avg_loss_cp is None
    assert dashboard.blunder_rate is None


# ---------- tables ----------


def test_openings_frame_values():
    frame = openings_frame([OpeningRecord("white", "Italian Game", 4, 2, 1, 1)])

    assert frame.iloc[0].to_dict() == {
        "Color": "white",
        "Opening": "Italian Game",
        "Games": 4,
        "Wins": 2,
        "Draws": 1,
        "Losses": 1,
        "Score %": 62.5,
    }


def test_an_empty_openings_frame_keeps_its_columns():
    frame = openings_frame([])

    assert frame.empty
    assert list(frame.columns) == [
        "Color",
        "Opening",
        "Games",
        "Wins",
        "Draws",
        "Losses",
        "Score %",
    ]


def test_speeds_frame_joins_results_and_accuracy():
    frame = speeds_frame(
        [SpeedRecord("blitz", 10, 4, 0, 6, 3, 0)], [GroupStats("blitz", 100, 4000, 5)]
    )

    row = frame.iloc[0]
    assert row["Score %"] == 40.0
    assert row["Lost on time"] == 3
    assert row["Lost on time % of losses"] == 50.0
    assert row["Avg loss (cp)"] == 40
    assert row["Blunder %"] == 5.0


def test_a_speed_without_accuracy_has_missing_values():
    frame = speeds_frame([SpeedRecord("rapid", 2, 1, 0, 1, 0, 0)], [])

    row = frame.iloc[0]
    assert row["Games"] == 2
    assert pd.isna(row["Avg loss (cp)"])
    assert pd.isna(row["Blunder %"])


def test_clock_frame_values():
    frame = clock_frame([GroupStats("<10s", 200, 20000, 30)])

    assert frame.iloc[0].to_dict() == {
        "Time left": "<10s",
        "Your moves": 200,
        "Avg loss (cp)": 100,
        "Blunder %": 15.0,
    }


def test_months_frame_values():
    frame = months_frame(
        [MonthResult("2024-01", 4, 2, 1, 1, 3000, 3)], [GroupStats("2024-01", 10, 500, 1)]
    )

    row = frame.iloc[0]
    assert row["Score %"] == 62.5
    assert row["Avg rating"] == 1000
    assert row["Avg loss (cp)"] == 50
    assert row["Blunder %"] == 10.0


def test_a_month_without_rating_or_accuracy_has_missing_values():
    frame = months_frame([MonthResult("2024-02", 2, 0, 0, 2, 0, 0)], [])

    row = frame.iloc[0]
    assert row["Score %"] == 0.0
    assert pd.isna(row["Avg rating"])
    assert pd.isna(row["Avg loss (cp)"])


def test_phases_frame_values():
    frame = phases_frame([PhaseStats("endgame", 50, 5000, 10)])

    assert frame.iloc[0].to_dict() == {
        "Phase": "endgame",
        "Your moves": 50,
        "Avg loss (cp)": 100,
        "Blunder %": 20.0,
    }
