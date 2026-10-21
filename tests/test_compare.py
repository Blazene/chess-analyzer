import pytest
from analysis_helpers import FakeEngine, add_game
from psycopg.types.json import Jsonb

from batch import analyze_games
from compare import (
    Comparison,
    check_integrity,
    compare_game,
    lichess_cp,
    lichess_label,
    run_comparison,
)
from db import comparison_data, get_or_create_run, integrity_rows


def run_for(db):
    return get_or_create_run(db, "Fake 1", 5)


def game_with_analysis(db, analysis):
    game_id = add_game(db)
    db.execute("UPDATE games SET lichess_analysis = %s WHERE id = %s", (Jsonb(analysis), game_id))
    return game_id


# ---------- reading Lichess entries ----------


def test_lichess_centipawns_pass_through():
    assert lichess_cp({"eval": 120}) == 120


def test_lichess_centipawns_are_capped():
    assert lichess_cp({"eval": 4000}) == 1000
    assert lichess_cp({"eval": -4000}) == -1000


@pytest.mark.parametrize("mate, expected", [(3, 1000), (-7, -1000)])
def test_lichess_mate_becomes_the_cap(mate, expected):
    assert lichess_cp({"mate": mate}) == expected


def test_lichess_mate_in_zero_has_no_score():
    assert lichess_cp({"mate": 0}) is None


def test_lichess_entry_without_a_score_has_none():
    assert lichess_cp({"best": "e2e4"}) is None


def test_lichess_judgment_is_lowercased():
    assert lichess_label({"eval": 10, "judgment": {"name": "Blunder"}}) == "blunder"


def test_lichess_entry_without_judgment_is_ok():
    assert lichess_label({"eval": 10}) == "ok"


# ---------- comparing one game ----------


def test_differences_are_counted_per_position():
    c = Comparison()

    compare_game(c, {1: 100, 2: -50}, {1: "ok", 2: "ok"}, [{"eval": 120}, {"eval": -30}])

    assert (c.games, c.positions, c.abs_diff_total, c.mean_abs_diff) == (1, 2, 40, 20.0)
    assert (c.sign_checked, c.sign_agree) == (1, 1)  # ply 2: Lichess is under 50 cp


def test_opposite_sides_ahead_are_a_sign_disagreement():
    c = Comparison()

    compare_game(c, {1: 200}, {1: "ok"}, [{"eval": -200}])

    assert (c.sign_checked, c.sign_agree, c.sign_rate) == (1, 0, 0.0)


def test_a_mate_against_a_capped_score_agrees():
    c = Comparison()

    compare_game(c, {1: 1000}, {1: "ok"}, [{"mate": 3}])

    assert c.abs_diff_total == 0
    assert (c.sign_checked, c.sign_agree) == (1, 1)


def test_a_list_of_the_wrong_length_is_skipped_and_counted():
    c = Comparison()

    compare_game(c, {1: 10, 2: 10}, {1: "ok", 2: "ok"}, [{"eval": 1}, {"eval": 2}, {"eval": 3}])

    assert (c.skipped_shape, c.games, c.positions) == (1, 0, 0)


def test_labels_are_tallied_as_ours_against_theirs():
    c = Comparison()

    compare_game(c, {1: 0}, {1: "blunder"}, [{"eval": 0, "judgment": {"name": "Mistake"}}])

    assert c.labels[("blunder", "mistake")] == 1


def test_a_position_we_could_not_score_still_counts_its_label():
    c = Comparison()

    compare_game(c, {1: 10}, {1: "ok", 2: "ok"}, [{"eval": 10}, {"mate": 0}])

    assert c.positions == 1  # ply 2 has no score on either side
    assert sum(c.labels.values()) == 2


def test_averages_without_positions_are_none():
    c = Comparison()

    assert c.mean_abs_diff is None
    assert c.sign_rate is None


# ---------- integrity check ----------


@pytest.mark.parametrize("evals", [4, 5])
def test_a_game_that_ended_or_not_has_a_valid_evaluation_count(evals):
    assert check_integrity([("aaaa0001", 4, evals, 4)]) == (0, [])


def test_a_missing_loss_row_is_a_problem():
    unanalyzed, problems = check_integrity([("aaaa0001", 4, 5, 3)])

    assert unanalyzed == 0
    assert problems == ["aaaa0001: 4 moves but 3 loss rows"]


def test_a_wrong_evaluation_count_is_a_problem():
    _, problems = check_integrity([("aaaa0001", 4, 2, 4)])

    assert problems == ["aaaa0001: 4 moves but 2 evaluations"]


def test_games_without_results_are_counted_not_flagged():
    assert check_integrity([("aaaa0001", 4, 0, 0), ("bbbb0001", 4, 4, 4)]) == (1, [])


# ---------- database queries ----------


def test_integrity_rows_describe_an_analyzed_game(db):
    add_game(db)
    analyze_games(db, FakeEngine(), run_for(db), 5)

    assert integrity_rows(db, run_for(db)) == [("abcd1234", 4, 4, 4)]


def test_integrity_rows_show_an_unanalyzed_game_as_zeros(db):
    add_game(db)

    assert integrity_rows(db, run_for(db)) == [("abcd1234", 4, 0, 0)]


def test_comparison_data_has_our_scores_and_labels(db):
    analysis = [{"eval": -25}, {"eval": 25}, {"eval": -25}, {"mate": 0}]
    game_with_analysis(db, analysis)
    analyze_games(db, FakeEngine(), run_for(db), 5)

    (row,) = comparison_data(db, run_for(db))

    assert row["lichess_id"] == "abcd1234"
    assert row["analysis"] == analysis
    assert row["cps"][1] == (-25, None)
    assert set(row["labels"]) == {1, 2, 3, 4}


def test_comparison_data_skips_games_without_lichess_analysis(db):
    add_game(db)
    analyze_games(db, FakeEngine(), run_for(db), 5)

    assert comparison_data(db, run_for(db)) == []


def test_a_full_comparison_from_the_database(db):
    game_with_analysis(db, [{"eval": -25}, {"eval": 25}, {"eval": -25}, {"mate": 0}])
    analyze_games(db, FakeEngine(), run_for(db), 5)

    c = run_comparison(db, run_for(db))

    assert (c.games, c.positions, c.abs_diff_total) == (1, 3, 0)
    assert sum(c.labels.values()) == 4


def test_a_game_not_analyzed_yet_is_counted_separately(db):
    game_with_analysis(db, [{"eval": 1}, {"eval": 2}, {"eval": 3}, {"eval": 4}])

    c = run_comparison(db, run_for(db))

    assert (c.not_analyzed, c.games) == (1, 0)
