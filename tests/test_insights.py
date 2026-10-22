import pytest
from insights_helpers import FEN_SEVEN, FEN_SIX, add_scored_game, mv

from db import get_or_create_run
from filters import Filters
from insights import OpeningRecord, opening_win_rates, phase_accuracy


def run_for(db, depth=5):
    return get_or_create_run(db, "Fake 1", depth)


def add_many(db, count, **kwargs):
    for _ in range(count):
        add_scored_game(db, **kwargs)


def stats_by_phase(db, run_id, **kwargs):
    return {s.phase: s for s in phase_accuracy(db, run_id, **kwargs)}


# ---------- opening win rates ----------


def test_a_record_counts_wins_draws_and_losses(db):
    add_many(db, 2, result="win")
    add_scored_game(db, result="draw")
    add_scored_game(db, result="loss")

    records = opening_win_rates(db, min_games=1)

    assert records == [OpeningRecord("white", "Italian Game", 4, 2, 1, 1)]


def test_a_draw_counts_as_half_a_win_in_the_score(db):
    add_many(db, 2, result="win")
    add_scored_game(db, result="draw")
    add_scored_game(db, result="loss")

    (record,) = opening_win_rates(db, min_games=1)

    assert record.score == pytest.approx(0.625)


def test_variations_are_grouped_into_one_family(db):
    add_scored_game(db, opening="Sicilian Defense: Najdorf Variation")
    add_scored_game(db, opening="Sicilian Defense: Dragon Variation")
    add_scored_game(db, opening="Sicilian Defense")

    records = opening_win_rates(db, min_games=1)

    assert [(r.opening, r.games) for r in records] == [("Sicilian Defense", 3)]


def test_the_same_opening_as_white_and_black_is_listed_separately(db):
    add_scored_game(db, color="white", result="win")
    add_scored_game(db, color="black", result="loss")

    records = opening_win_rates(db, min_games=1)

    assert sorted((r.color, r.wins, r.losses) for r in records) == [
        ("black", 0, 1),
        ("white", 1, 0),
    ]


def test_rare_openings_are_hidden_by_the_minimum(db):
    add_many(db, 3, opening="Italian Game")
    add_scored_game(db, opening="Vienna Game")

    records = opening_win_rates(db, min_games=3)

    assert [r.opening for r in records] == ["Italian Game"]


def test_openings_are_listed_most_played_first(db):
    add_scored_game(db, opening="Vienna Game")
    add_many(db, 2, opening="Italian Game")

    records = opening_win_rates(db, min_games=1)

    assert [r.opening for r in records] == ["Italian Game", "Vienna Game"]


def test_a_missing_opening_is_listed_as_unknown(db):
    add_scored_game(db, opening=None)

    records = opening_win_rates(db, min_games=1)

    assert [r.opening for r in records] == ["Unknown"]


def test_games_against_the_computer_are_excluded_unless_asked(db):
    add_scored_game(db)
    add_scored_game(db, opponent_is_ai=True)

    assert opening_win_rates(db, min_games=1)[0].games == 1
    assert opening_win_rates(db, min_games=1, filters=Filters(include_ai=True))[0].games == 2


def test_no_games_gives_no_records(db):
    assert opening_win_rates(db, min_games=1) == []


# ---------- accuracy by phase ----------


def test_only_your_own_moves_are_counted(db):
    run_id = run_for(db)
    add_scored_game(db, run_id, color="white", moves=[mv(1, 10), mv(2, 1000, "blunder"), mv(3, 20)])
    add_scored_game(
        db,
        run_id,
        color="black",
        moves=[mv(1, 500, "blunder"), mv(2, 30), mv(3, 500, "blunder"), mv(4, 40)],
    )

    (opening,) = phase_accuracy(db, run_id)

    assert (opening.phase, opening.moves, opening.total_loss_cp, opening.blunders) == (
        "opening",
        4,
        100,
        0,
    )


def test_the_opening_ends_after_ply_twenty(db):
    run_id = run_for(db)
    add_scored_game(db, run_id, color="black", moves=[mv(20, 10), mv(22, 20)])

    stats = stats_by_phase(db, run_id)

    assert (stats["opening"].moves, stats["opening"].total_loss_cp) == (1, 10)
    assert (stats["middlegame"].moves, stats["middlegame"].total_loss_cp) == (1, 20)


def test_the_endgame_starts_at_six_pieces(db):
    run_id = run_for(db)
    add_scored_game(db, run_id, moves=[mv(31, 10, fen=FEN_SIX), mv(33, 20, fen=FEN_SEVEN)])

    stats = stats_by_phase(db, run_id)

    assert stats["endgame"].total_loss_cp == 10
    assert stats["middlegame"].total_loss_cp == 20


def test_early_moves_stay_in_the_opening_even_with_few_pieces(db):
    run_id = run_for(db)
    add_scored_game(db, run_id, moves=[mv(5, 10, fen=FEN_SIX)])

    assert [s.phase for s in phase_accuracy(db, run_id)] == ["opening"]


def test_average_loss_and_blunder_rate(db):
    run_id = run_for(db)
    add_scored_game(
        db,
        run_id,
        moves=[mv(1, 0), mv(3, 300, "blunder"), mv(5, 100, "mistake"), mv(7, 0)],
    )

    (stats,) = phase_accuracy(db, run_id)

    assert stats.avg_loss_cp == 100
    assert stats.blunder_rate == 0.25


def test_phases_come_back_in_game_order_and_missing_ones_are_left_out(db):
    run_id = run_for(db)
    add_scored_game(db, run_id, moves=[mv(41, 10, fen=FEN_SIX), mv(1, 10)])

    assert [s.phase for s in phase_accuracy(db, run_id)] == ["opening", "endgame"]


def test_games_against_the_computer_are_left_out_of_phase_stats_unless_asked(db):
    run_id = run_for(db)
    add_scored_game(db, run_id, opponent_is_ai=True, moves=[mv(1, 10)])

    assert phase_accuracy(db, run_id) == []
    assert phase_accuracy(db, run_id, filters=Filters(include_ai=True))[0].moves == 1


def test_another_analysis_run_is_ignored(db):
    run_a, run_b = run_for(db, 5), run_for(db, 6)
    add_scored_game(db, run_a, moves=[mv(1, 10)])

    assert phase_accuracy(db, run_b) == []


def test_the_phase_boundaries_can_be_changed(db):
    run_id = run_for(db)
    add_scored_game(db, run_id, moves=[mv(3, 10)])

    assert phase_accuracy(db, run_id, opening_plies=2)[0].phase == "middlegame"
    assert phase_accuracy(db, run_id, opening_plies=2, endgame_pieces=14)[0].phase == "endgame"
