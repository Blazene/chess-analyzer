from datetime import date

from time_helpers import add_timed_game, mv

from dashboard_data import Options, load_dashboard, load_options
from db import get_or_create_run
from filters import Filters


def test_no_games_means_no_options(db):
    assert load_options(db) == Options([], None, None)


def test_time_controls_come_back_shortest_first(db):
    add_timed_game(db, speed="rapid")
    add_timed_game(db, speed="bullet")
    add_timed_game(db, speed="blitz")
    add_timed_game(db, speed="blitz")

    assert load_options(db).speeds == ["bullet", "blitz", "rapid"]


def test_the_date_range_is_in_utc_whatever_the_session_timezone(db):
    db.execute("SET LOCAL TIME ZONE 'Asia/Kolkata'")
    add_timed_game(db, played_at="2024-01-31 20:00+00")  # already February in Kolkata
    add_timed_game(db, played_at="2024-03-05 12:00+00")

    options = load_options(db)

    assert (options.first_day, options.last_day) == (date(2024, 1, 31), date(2024, 3, 5))


def test_filters_reach_every_query_in_the_dashboard(db):
    run_id = get_or_create_run(db, "Fake 1", 5)
    add_timed_game(db, run_id, color="white", moves=[mv(1, loss_cp=10), mv(3, loss_cp=10)])
    add_timed_game(db, run_id, color="black", moves=[mv(2, loss_cp=40)])

    dashboard = load_dashboard(db, Filters(color="black"))

    assert dashboard.games == 1
    assert dashboard.analyzed_moves == 1
    assert dashboard.avg_loss_cp == 40
    assert [s.key for s in dashboard.month_stats] == ["2024-01"]
