import psycopg
import pytest
from analysis_helpers import FakeEngine, add_game

from analyze import PlyEval, evaluate_game
from db import games_to_analyze, get_or_create_run, remaining_work, store_analysis
from engine import Evaluation
from loss import MoveLoss, move_losses

INSERT_LOSS = (
    "INSERT INTO move_losses (analysis_run_id, game_id, ply, loss_cp, label) "
    "VALUES (%s, %s, %s, %s, %s)"
)


def setup(db, moves_san="f3 e5 g4 Qh4#"):
    return add_game(db, moves_san=moves_san), get_or_create_run(db, "Fake 1", 5)


def analysed(moves_san="f3 e5 g4 Qh4#"):
    results = evaluate_game(FakeEngine(), moves_san, depth=5)
    return results, move_losses(results)


def count(db, table, game_id):
    return db.execute(f"SELECT count(*) FROM {table} WHERE game_id = %s", (game_id,)).fetchone()[0]


def rejected(db, error, constraint, *params):
    with pytest.raises(error) as exc_info:
        with db.transaction():
            db.execute(INSERT_LOSS, params)
    assert exc_info.value.diag.constraint_name == constraint


# ---------- analysis runs ----------


def test_a_run_is_created_once_per_setting(db):
    first = get_or_create_run(db, "Fake 1", 14)
    again = get_or_create_run(db, "Fake 1", 14)

    assert first == again
    rows = db.execute("SELECT count(*) FROM analysis_runs WHERE engine_name = 'Fake 1'").fetchone()
    assert rows[0] == 1


def test_another_depth_or_engine_gets_its_own_run(db):
    base = get_or_create_run(db, "Fake 1", 14)

    assert get_or_create_run(db, "Fake 1", 18) != base
    assert get_or_create_run(db, "Fake 2", 14) != base


# ---------- move_losses constraints ----------


def test_move_loss_rejects_an_unknown_label(db):
    game_id, run_id = setup(db)

    rejected(
        db,
        psycopg.errors.CheckViolation,
        "move_losses_label_valid",
        run_id,
        game_id,
        1,
        10,
        "terrible",
    )


def test_move_loss_rejects_a_negative_loss(db):
    game_id, run_id = setup(db)

    rejected(
        db,
        psycopg.errors.CheckViolation,
        "move_losses_loss_nonnegative",
        run_id,
        game_id,
        1,
        -1,
        "ok",
    )


def test_move_loss_rejects_ply_zero(db):
    game_id, run_id = setup(db)

    rejected(
        db, psycopg.errors.CheckViolation, "move_losses_ply_positive", run_id, game_id, 0, 0, "ok"
    )


def test_move_loss_needs_an_existing_move(db):
    game_id, run_id = setup(db)

    rejected(
        db,
        psycopg.errors.ForeignKeyViolation,
        "move_losses_move_fkey",
        run_id,
        game_id,
        99,
        0,
        "ok",
    )


# ---------- store_analysis ----------


def test_store_analysis_saves_evaluations_and_losses(db):
    game_id, run_id = setup(db)
    results, losses = analysed()

    store_analysis(db, run_id, game_id, results, losses)

    assert count(db, "evaluations", game_id) == 4  # plies 0 to 3, the mate has none
    assert count(db, "move_losses", game_id) == 4  # plies 1 to 4


def test_a_mate_score_goes_to_its_own_column(db):
    game_id, run_id = setup(db, "f3 e5")
    results = [
        PlyEval(0, None, Evaluation(None, 3, "e2e4"), 0.0),
        PlyEval(1, "f3", Evaluation(-40, None, "e7e5"), 0.0),
    ]
    losses = [MoveLoss(1, "f3", "white", 1000, 90.0, "blunder")]

    store_analysis(db, run_id, game_id, results, losses)

    rows = db.execute(
        "SELECT stockfish_cp, stockfish_mate, best_move FROM evaluations "
        "WHERE game_id = %s ORDER BY ply",
        (game_id,),
    ).fetchall()
    assert rows == [(None, 3, "e2e4"), (-40, None, "e7e5")]


def test_storing_the_same_analysis_twice_is_rejected(db):
    game_id, run_id = setup(db)
    results, losses = analysed()
    store_analysis(db, run_id, game_id, results, losses)

    with pytest.raises(psycopg.errors.UniqueViolation) as exc_info:
        store_analysis(db, run_id, game_id, results, losses)

    assert exc_info.value.diag.constraint_name == "evaluations_pkey"
    assert count(db, "evaluations", game_id) == 4  # the first save is untouched


def test_a_failed_save_leaves_nothing_behind(db):
    game_id, run_id = setup(db)
    results, _ = analysed()
    bad_losses = [MoveLoss(99, "x", "white", 0, 0.0, "ok")]  # move 99 does not exist

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        store_analysis(db, run_id, game_id, results, bad_losses)

    assert count(db, "evaluations", game_id) == 0
    assert count(db, "move_losses", game_id) == 0


# ---------- cascades ----------


def test_deleting_a_game_removes_its_analysis(db):
    game_id, run_id = setup(db)
    results, losses = analysed()
    store_analysis(db, run_id, game_id, results, losses)

    db.execute("DELETE FROM games WHERE id = %s", (game_id,))

    assert count(db, "evaluations", game_id) == 0
    assert count(db, "move_losses", game_id) == 0


def test_deleting_a_run_removes_only_its_analysis(db):
    game_id, run_id = setup(db)
    results, losses = analysed()
    store_analysis(db, run_id, game_id, results, losses)

    db.execute("DELETE FROM analysis_runs WHERE id = %s", (run_id,))

    assert count(db, "evaluations", game_id) == 0
    assert count(db, "move_losses", game_id) == 0
    assert count(db, "moves", game_id) == 4


# ---------- choosing what to analyze ----------


def test_games_to_analyze_lists_newest_first_and_skips_finished_games(db):
    add_game(db, "old00001", "e4 e5", "2024-01-01")
    newest = add_game(db, "new00001", "e4 e5", "2024-03-01")
    add_game(db, "mid00001", "e4 e5", "2024-02-01")
    run_id = get_or_create_run(db, "Fake 1", 5)

    games = games_to_analyze(db, run_id)
    assert [g["lichess_id"] for g in games] == ["new00001", "mid00001", "old00001"]
    assert games[0]["moves_san"] == "e4 e5"

    results, losses = analysed("e4 e5")
    store_analysis(db, run_id, newest, results, losses)
    assert [g["lichess_id"] for g in games_to_analyze(db, run_id)] == ["mid00001", "old00001"]


def test_games_to_analyze_respects_the_limit(db):
    add_game(db, "old00001", "e4 e5", "2024-01-01")
    add_game(db, "new00001", "e4 e5", "2024-03-01")
    add_game(db, "mid00001", "e4 e5", "2024-02-01")
    run_id = get_or_create_run(db, "Fake 1", 5)

    games = games_to_analyze(db, run_id, limit=2)

    assert [g["lichess_id"] for g in games] == ["new00001", "mid00001"]


def test_each_run_tracks_its_own_progress(db):
    game_id, run_a = setup(db)
    run_b = get_or_create_run(db, "Fake 1", 6)
    results, losses = analysed()
    store_analysis(db, run_a, game_id, results, losses)

    assert games_to_analyze(db, run_a) == []
    assert [g["id"] for g in games_to_analyze(db, run_b)] == [game_id]


def test_remaining_work_counts_games_and_moves(db):
    first = add_game(db, "aaaa0001", "f3 e5 g4 Qh4#", "2024-02-01")
    add_game(db, "bbbb0001", "e4 e5", "2024-01-01")
    run_id = get_or_create_run(db, "Fake 1", 5)
    assert remaining_work(db, run_id) == (2, 6)

    results, losses = analysed()
    store_analysis(db, run_id, first, results, losses)

    assert remaining_work(db, run_id) == (1, 2)
