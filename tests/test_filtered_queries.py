from datetime import date

from time_helpers import add_timed_game, mv

from db import get_or_create_run
from filters import Filters
from insights import opening_win_rates, phase_accuracy
from time_insights import (
    clock_accuracy,
    monthly_accuracy,
    monthly_results,
    speed_accuracy,
    speed_results,
)


def run_for(db):
    return get_or_create_run(db, "Fake 1", 5)


def total_games(records):
    return sum(r.games for r in records)


def test_openings_can_be_limited_to_one_color(db):
    add_timed_game(db, color="white")
    add_timed_game(db, color="black")

    records = opening_win_rates(db, Filters(color="white"), min_games=1)

    assert [(r.color, r.games) for r in records] == [("white", 1)]


def test_openings_can_be_limited_to_some_time_controls(db):
    add_timed_game(db, speed="blitz")
    add_timed_game(db, speed="rapid")

    records = opening_win_rates(db, Filters(speeds=("rapid",)), min_games=1)

    assert total_games(records) == 1


def test_the_date_range_includes_both_ends_and_counts_days_in_utc(db):
    db.execute("SET LOCAL TIME ZONE 'Asia/Kolkata'")
    add_timed_game(db, played_at="2024-01-31 20:00+00")
    add_timed_game(db, played_at="2024-02-01 00:30+00")

    january_31 = Filters(start=date(2024, 1, 31), end=date(2024, 1, 31))
    february_1 = Filters(start=date(2024, 2, 1), end=date(2024, 2, 1))

    assert total_games(opening_win_rates(db, january_31, min_games=1)) == 1
    assert total_games(opening_win_rates(db, february_1, min_games=1)) == 1


def test_phase_stats_count_only_your_moves_in_the_chosen_color(db):
    run_id = run_for(db)
    add_timed_game(
        db,
        run_id,
        color="white",
        moves=[mv(1, loss_cp=100), mv(2, loss_cp=900, label="blunder"), mv(3, loss_cp=50)],
    )
    add_timed_game(
        db,
        run_id,
        color="black",
        moves=[
            mv(1, loss_cp=500, label="blunder"),
            mv(2, loss_cp=30),
            mv(3, loss_cp=500, label="blunder"),
            mv(4, loss_cp=40),
        ],
    )

    (stats,) = phase_accuracy(db, run_id, Filters(color="black"))

    assert (stats.moves, stats.total_loss_cp, stats.blunders) == (2, 70, 0)


def test_phase_stats_can_be_limited_to_a_time_control(db):
    run_id = run_for(db)
    add_timed_game(db, run_id, speed="blitz", moves=[mv(1, loss_cp=10)])
    add_timed_game(db, run_id, speed="rapid", moves=[mv(1, loss_cp=30)])

    (stats,) = phase_accuracy(db, run_id, Filters(speeds=("rapid",)))

    assert (stats.moves, stats.total_loss_cp) == (1, 30)


def test_speed_results_can_be_limited_to_some_time_controls(db):
    add_timed_game(db, speed="blitz")
    add_timed_game(db, speed="rapid")

    records = speed_results(db, Filters(speeds=("blitz",)))

    assert [(r.speed, r.games) for r in records] == [("blitz", 1)]


def test_speed_accuracy_can_be_limited_to_one_color(db):
    run_id = run_for(db)
    add_timed_game(db, run_id, color="white", moves=[mv(1, loss_cp=10)])
    add_timed_game(db, run_id, color="black", moves=[mv(2, loss_cp=70)])

    (stats,) = speed_accuracy(db, run_id, Filters(color="black"))

    assert (stats.moves, stats.total_loss_cp) == (1, 70)


def test_clock_stats_can_be_limited_to_a_date_range(db):
    run_id = run_for(db)
    add_timed_game(db, run_id, played_at="2024-01-10 12:00+00", moves=[mv(1, 500)])
    add_timed_game(db, run_id, played_at="2024-03-10 12:00+00", moves=[mv(1, 20000)])

    stats = clock_accuracy(db, run_id, Filters(start=date(2024, 2, 1)))

    assert [s.key for s in stats] == ["3 min+"]


def test_monthly_results_can_be_limited_to_one_color(db):
    add_timed_game(db, color="white", played_at="2024-01-10 12:00+00")
    add_timed_game(db, color="black", played_at="2024-02-10 12:00+00")

    records = monthly_results(db, Filters(color="black"))

    assert [r.month for r in records] == ["2024-02"]


def test_monthly_accuracy_can_be_limited_to_a_time_control(db):
    run_id = run_for(db)
    add_timed_game(db, run_id, speed="blitz", played_at="2024-01-10 12:00+00", moves=[mv(1)])
    add_timed_game(db, run_id, speed="rapid", played_at="2024-02-10 12:00+00", moves=[mv(1)])

    stats = monthly_accuracy(db, run_id, Filters(speeds=("rapid",)))

    assert [s.key for s in stats] == ["2024-02"]


def test_all_filters_together_keep_only_the_game_that_matches_every_one(db):
    add_timed_game(db, color="white", speed="blitz", played_at="2024-01-10 12:00+00")
    add_timed_game(db, color="black", speed="blitz", played_at="2024-01-10 12:00+00")
    add_timed_game(db, color="white", speed="rapid", played_at="2024-01-10 12:00+00")
    add_timed_game(db, color="white", speed="blitz", played_at="2024-03-10 12:00+00")
    everything = Filters(
        color="white", speeds=("blitz",), start=date(2024, 1, 1), end=date(2024, 2, 1)
    )

    records = speed_results(db, everything)

    assert [(r.speed, r.games) for r in records] == [("blitz", 1)]


def test_an_empty_time_control_selection_matches_nothing(db):
    add_timed_game(db)

    assert opening_win_rates(db, Filters(speeds=()), min_games=1) == []
