import pytest
from time_helpers import add_timed_game, mv

from db import get_or_create_run
from time_insights import (
    GroupStats,
    MonthResult,
    SpeedRecord,
    clock_accuracy,
    monthly_accuracy,
    monthly_results,
    speed_accuracy,
    speed_results,
)


def run_for(db, depth=5):
    return get_or_create_run(db, "Fake 1", depth)


def add_many(db, count, **kwargs):
    for _ in range(count):
        add_timed_game(db, **kwargs)


def by_key(stats):
    return {s.key: s for s in stats}


# ---------- results by time control ----------


def test_speed_results_count_wins_draws_and_losses_per_speed(db):
    add_many(db, 2, speed="blitz", result="win")
    add_timed_game(db, speed="blitz", result="loss")
    add_timed_game(db, speed="rapid", result="draw")

    records = speed_results(db)

    assert [(r.speed, r.games, r.wins, r.draws, r.losses) for r in records] == [
        ("blitz", 3, 2, 0, 1),
        ("rapid", 1, 0, 1, 0),
    ]


def test_time_wins_and_losses_are_counted_separately(db):
    add_many(db, 2, result="loss", status="outoftime")
    add_timed_game(db, result="loss", status="mate")
    add_timed_game(db, result="win", status="outoftime")
    add_timed_game(db, result="win", status="resign")

    (record,) = speed_results(db)

    assert (record.lost_on_time, record.won_on_time, record.losses) == (2, 1, 3)


def test_flag_loss_rate_is_the_share_of_losses_that_were_on_time():
    assert SpeedRecord("blitz", 10, 4, 0, 6, 3, 0).flag_loss_rate == 0.5


def test_flag_loss_rate_without_losses_is_none():
    assert SpeedRecord("blitz", 2, 2, 0, 0, 0, 0).flag_loss_rate is None


def test_a_draw_counts_as_half_a_win_in_the_speed_score():
    assert SpeedRecord("blitz", 4, 2, 1, 1, 0, 0).score == pytest.approx(0.625)


def test_games_against_the_computer_are_excluded_from_speed_results_unless_asked(db):
    add_timed_game(db)
    add_timed_game(db, opponent_is_ai=True)

    assert speed_results(db)[0].games == 1
    assert speed_results(db, include_ai=True)[0].games == 2


def test_no_games_gives_no_speed_rows(db):
    assert speed_results(db) == []


# ---------- accuracy by time control ----------


def test_speed_accuracy_counts_only_your_moves_per_speed(db):
    run_id = run_for(db)
    add_timed_game(
        db,
        run_id,
        color="white",
        speed="blitz",
        moves=[mv(1, loss_cp=10), mv(2, loss_cp=900, label="blunder"), mv(3, loss_cp=30)],
    )
    add_timed_game(
        db,
        run_id,
        color="black",
        speed="rapid",
        moves=[mv(1, loss_cp=900, label="blunder"), mv(2, loss_cp=50, label="mistake")],
    )

    stats = by_key(speed_accuracy(db, run_id))

    blitz, rapid = stats["blitz"], stats["rapid"]
    assert (blitz.moves, blitz.total_loss_cp, blitz.blunders) == (2, 40, 0)
    assert (rapid.moves, rapid.total_loss_cp, rapid.blunders) == (1, 50, 0)


def test_speed_accuracy_ignores_another_analysis_run(db):
    run_a, run_b = run_for(db, 5), run_for(db, 6)
    add_timed_game(db, run_a, moves=[mv(1)])

    assert speed_accuracy(db, run_b) == []


# ---------- accuracy by time left ----------


@pytest.mark.parametrize(
    "clock_cs, bucket",
    [
        (999, "<10s"),
        (1000, "10-30s"),
        (2999, "10-30s"),
        (3000, "30-60s"),
        (5999, "30-60s"),
        (6000, "1-3 min"),
        (17999, "1-3 min"),
        (18000, "3 min+"),
    ],
)
def test_clock_bucket_edges(db, clock_cs, bucket):
    run_id = run_for(db)
    add_timed_game(db, run_id, moves=[mv(1, clock_cs)])

    assert [s.key for s in clock_accuracy(db, run_id)] == [bucket]


def test_moves_without_a_clock_are_left_out(db):
    run_id = run_for(db)
    add_timed_game(db, run_id, moves=[mv(1, None), mv(3, 500)])

    (stats,) = clock_accuracy(db, run_id)

    assert (stats.key, stats.moves) == ("<10s", 1)


def test_clock_stats_add_up_loss_and_blunders(db):
    run_id = run_for(db)
    add_timed_game(
        db,
        run_id,
        moves=[mv(1, 500, 300, "blunder"), mv(3, 600, 100, "mistake"), mv(5, 700), mv(7, 800)],
    )

    (stats,) = clock_accuracy(db, run_id)

    assert (stats.moves, stats.total_loss_cp, stats.blunders) == (4, 400, 1)
    assert stats.avg_loss_cp == 100
    assert stats.blunder_rate == 0.25


def test_clock_buckets_come_back_shortest_first_and_empty_ones_are_left_out(db):
    run_id = run_for(db)
    add_timed_game(db, run_id, moves=[mv(1, 20000), mv(3, 500), mv(5, 7000)])

    assert [s.key for s in clock_accuracy(db, run_id)] == ["<10s", "1-3 min", "3 min+"]


def test_clock_stats_can_be_limited_to_one_speed(db):
    run_id = run_for(db)
    add_timed_game(db, run_id, speed="blitz", moves=[mv(1, 500)])
    add_timed_game(db, run_id, speed="rapid", moves=[mv(1, 500), mv(3, 500)])

    assert clock_accuracy(db, run_id, speed="rapid")[0].moves == 2
    assert clock_accuracy(db, run_id)[0].moves == 3


def test_clock_stats_count_only_your_moves(db):
    run_id = run_for(db)
    add_timed_game(
        db,
        run_id,
        color="black",
        moves=[mv(1, 500), mv(2, 20000), mv(3, 500), mv(4, 20000)],
    )

    stats = clock_accuracy(db, run_id)

    assert [(s.key, s.moves) for s in stats] == [("3 min+", 2)]


def test_clock_stats_exclude_the_computer_unless_asked(db):
    run_id = run_for(db)
    add_timed_game(db, run_id, opponent_is_ai=True, moves=[mv(1, 500)])

    assert clock_accuracy(db, run_id) == []
    assert clock_accuracy(db, run_id, include_ai=True)[0].moves == 1


# ---------- trends by month ----------


def test_games_are_grouped_by_month(db):
    add_timed_game(db, played_at="2024-01-10 12:00+00", result="win")
    add_timed_game(db, played_at="2024-01-20 12:00+00", result="loss")
    add_timed_game(db, played_at="2024-02-05 12:00+00", result="draw")

    records = monthly_results(db)

    assert [(r.month, r.games, r.wins, r.draws, r.losses) for r in records] == [
        ("2024-01", 2, 1, 0, 1),
        ("2024-02", 1, 0, 1, 0),
    ]


def test_months_are_cut_in_utc_whatever_the_session_timezone(db):
    db.execute("SET LOCAL TIME ZONE 'Asia/Kolkata'")
    add_timed_game(db, played_at="2024-01-31 20:00+00")  # already February in Kolkata

    assert [r.month for r in monthly_results(db)] == ["2024-01"]


def test_a_month_without_games_is_not_listed(db):
    add_timed_game(db, played_at="2024-01-10 12:00+00")
    add_timed_game(db, played_at="2024-03-10 12:00+00")

    assert [r.month for r in monthly_results(db)] == ["2024-01", "2024-03"]


def test_average_rating_ignores_games_without_a_rating(db):
    add_timed_game(db, rating=1000)
    add_timed_game(db, rating=1200)
    add_timed_game(db)

    (record,) = monthly_results(db)

    assert record.avg_rating == 1100


def test_a_month_without_ratings_has_no_average_rating(db):
    add_timed_game(db)

    assert monthly_results(db)[0].avg_rating is None


def test_month_score_counts_draws_as_half_a_win():
    assert MonthResult("2024-01", 4, 2, 1, 1, 0, 0).score == pytest.approx(0.625)


def test_monthly_results_exclude_the_computer_unless_asked(db):
    add_timed_game(db, opponent_is_ai=True)

    assert monthly_results(db) == []
    assert monthly_results(db, include_ai=True)[0].games == 1


def test_monthly_accuracy_counts_your_moves_by_month(db):
    run_id = run_for(db)
    add_timed_game(
        db,
        run_id,
        played_at="2024-01-10 12:00+00",
        moves=[mv(1, loss_cp=100), mv(2, loss_cp=999), mv(3, loss_cp=300, label="blunder")],
    )
    add_timed_game(db, run_id, played_at="2024-02-10 12:00+00", moves=[mv(1)])

    stats = by_key(monthly_accuracy(db, run_id))

    january = stats["2024-01"]
    assert (january.moves, january.total_loss_cp, january.blunders) == (2, 400, 1)
    assert stats["2024-02"].moves == 1
    assert list(stats) == ["2024-01", "2024-02"]


def test_a_game_without_analysis_has_results_but_no_accuracy(db):
    run_id = run_for(db)
    add_timed_game(db, played_at="2024-01-10 12:00+00")

    assert len(monthly_results(db)) == 1
    assert monthly_accuracy(db, run_id) == []


# ---------- shared statistics ----------


def test_group_stats_average_and_blunder_rate():
    stats = GroupStats("x", 4, 400, 1)

    assert stats.avg_loss_cp == 100
    assert stats.blunder_rate == 0.25
