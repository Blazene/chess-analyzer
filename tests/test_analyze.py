import os
import shutil

import pytest
from chess.engine import Cp, PovScore
from db_helpers import insert_game

from analyze import (
    PlyEval,
    bar,
    biggest_swings,
    display_cp,
    evaluate_game,
    move_label,
)
from db import get_game, store_game
from engine import Evaluation, open_engine
from models import parse_game

FOOLS_MATE_MOVES = "f3 e5 g4 Qh4#"


class FakeEngine:
    """Answers +25 for the side to move and records what it was asked."""

    def __init__(self):
        self.calls = []

    def analyse(self, board, limit, game=None):
        self.calls.append({"history": len(board.move_stack), "game": game, "depth": limit.depth})
        return {"score": PovScore(Cp(25), board.turn), "pv": [next(iter(board.legal_moves))]}


def ev(cp):
    return Evaluation(cp, None, None)


def ply_eval(ply, evaluation):
    return PlyEval(ply, "x" if ply else None, evaluation, 0.0)


# ---------- walking a game (fake engine) ----------


def test_walk_has_one_entry_per_position_including_the_start():
    seen = []

    results = evaluate_game(FakeEngine(), FOOLS_MATE_MOVES, depth=5, on_ply=seen.append)

    assert [r.ply for r in results] == [0, 1, 2, 3, 4]
    assert [r.san for r in results] == [None, "f3", "e5", "g4", "Qh4#"]
    assert seen == results


def test_start_position_is_evaluated():
    results = evaluate_game(FakeEngine(), FOOLS_MATE_MOVES, depth=5)

    assert results[0].evaluation is not None


def test_final_checkmate_has_no_evaluation():
    results = evaluate_game(FakeEngine(), FOOLS_MATE_MOVES, depth=5)

    assert all(r.evaluation is not None for r in results[:4])
    assert results[4].evaluation is None


def test_engine_sees_the_full_move_history():
    fake = FakeEngine()

    evaluate_game(fake, FOOLS_MATE_MOVES, depth=5)

    assert [call["history"] for call in fake.calls] == [0, 1, 2, 3]


def test_game_key_and_depth_reach_every_call():
    fake = FakeEngine()

    evaluate_game(fake, FOOLS_MATE_MOVES, depth=7, game_key="G1")

    assert {call["game"] for call in fake.calls} == {"G1"}
    assert {call["depth"] for call in fake.calls} == {7}


def test_curve_is_from_whites_point_of_view_whoever_is_to_move():
    results = evaluate_game(FakeEngine(), FOOLS_MATE_MOVES, depth=5)

    assert [r.evaluation.cp for r in results[:4]] == [25, -25, 25, -25]


def test_illegal_move_names_the_ply():
    with pytest.raises(ValueError, match="ply 2"):
        evaluate_game(FakeEngine(), "e4 e4", depth=5)


def test_empty_game_has_only_the_start_position():
    results = evaluate_game(FakeEngine(), "", depth=5)

    assert [r.ply for r in results] == [0]


# ---------- display helpers ----------


@pytest.mark.parametrize(
    ("evaluation", "expected"),
    [
        (Evaluation(-35, None, None), -35),
        (Evaluation(None, 3, None), 1000),
        (Evaluation(None, -1, None), -1000),
    ],
)
def test_display_cp(evaluation, expected):
    assert display_cp(evaluation) == expected


def test_biggest_swings_are_measured_against_the_player_who_moved():
    results = [
        ply_eval(0, ev(20)),
        ply_eval(1, ev(30)),
        ply_eval(2, ev(400)),
        ply_eval(3, ev(-100)),
    ]

    assert biggest_swings(results, top=2) == [(3, 500), (2, 370)]


def test_moves_that_improved_the_position_are_not_listed():
    results = [ply_eval(0, ev(20)), ply_eval(1, ev(30))]

    assert biggest_swings(results) == []


def test_positions_without_an_evaluation_are_skipped():
    results = [ply_eval(0, ev(0)), ply_eval(1, ev(-300)), ply_eval(2, None)]

    assert biggest_swings(results) == [(1, 300)]


@pytest.mark.parametrize(
    ("cp", "expected"),
    [
        (0, " " * 10 + "|" + " " * 10),
        (500, " " * 10 + "|" + "#" * 10),
        (-250, " " * 5 + "#" * 5 + "|" + " " * 10),
        (99999, " " * 10 + "|" + "#" * 10),
    ],
)
def test_bar(cp, expected):
    assert bar(cp) == expected


@pytest.mark.parametrize(
    ("ply", "san", "expected"),
    [(0, None, "start"), (1, "e4", "1. e4"), (2, "c5", "1... c5"), (3, "c4", "2. c4")],
)
def test_move_label(ply, san, expected):
    assert move_label(ply, san) == expected


# ---------- real Stockfish ----------


def _find_stockfish():
    found = shutil.which("stockfish")
    if found:
        return found
    for path in ("/opt/homebrew/bin/stockfish", "/usr/local/bin/stockfish", "/usr/games/stockfish"):
        if os.path.exists(path):
            return path
    return None


@pytest.fixture(scope="module")
def engine():
    path = _find_stockfish()
    if path is None:
        pytest.skip("Stockfish is not installed")
    with open_engine(path, hash_mb=16) as eng:
        yield eng


def test_real_engine_walks_a_short_game(engine):
    results = evaluate_game(engine, "e4 e5 Nf3", depth=8, game_key="T1")

    assert len(results) == 4
    assert all(r.evaluation is not None for r in results)


def test_real_engine_sees_the_mate_before_it_happens(engine):
    results = evaluate_game(engine, FOOLS_MATE_MOVES, depth=8, game_key="T2")

    assert results[3].evaluation.mate == -1
    assert results[4].evaluation is None


# ---------- reading a stored game ----------


def test_get_game_by_id(db, raw_game):
    store_game(db, parse_game(raw_game, "blazene"))

    game = get_game(db, "4MhVOLfl")

    assert game["lichess_id"] == "4MhVOLfl"
    assert game["color"] == "black"
    assert game["status"] == "outoftime"
    assert game["opponent_name"] == "a_jakov95"
    assert game["moves_san"] == raw_game["moves"]


def test_get_game_defaults_to_the_newest(db):
    insert_game(db, lichess_id="AAAAAAAA", played_at="2026-01-01T00:00:00Z")
    insert_game(db, lichess_id="BBBBBBBB", played_at="2026-03-01T00:00:00Z")

    assert get_game(db)["lichess_id"] == "BBBBBBBB"


def test_get_game_unknown_id_returns_none(db):
    insert_game(db)

    assert get_game(db, "ZZZZZZZZ") is None


def test_get_game_on_an_empty_database_returns_none(db):
    assert get_game(db) is None
