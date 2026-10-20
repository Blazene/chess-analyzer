import os
import shutil

import chess
import chess.engine
import pytest
from chess.engine import Cp, Mate, PovScore

from engine import Evaluation, describe, evaluate, normalize_score, open_engine

WHITE_MATES_IN_1 = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"  # Ra8#
BLACK_MATES_IN_1 = "r5k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1"  # Ra1#
WHITE_UP_A_QUEEN = "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR {turn} KQkq - 0 1"
BLACK_UP_A_QUEEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR {turn} KQkq - 0 1"
FOOLS_MATE = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
STALEMATE = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"

DEPTH = 12

# ---------- sign convention (no engine needed) ----------


@pytest.mark.parametrize(
    ("relative", "turn", "expected"),
    [
        (Cp(35), chess.WHITE, (35, None)),
        (Cp(35), chess.BLACK, (-35, None)),
        (Cp(-20), chess.WHITE, (-20, None)),
        (Cp(-20), chess.BLACK, (20, None)),
        (Mate(2), chess.WHITE, (None, 2)),
        (Mate(2), chess.BLACK, (None, -2)),
        (Mate(-3), chess.WHITE, (None, -3)),
        (Mate(-3), chess.BLACK, (None, 3)),
    ],
)
def test_normalize_score_is_always_from_whites_point_of_view(relative, turn, expected):
    assert normalize_score(PovScore(relative, turn)) == expected


def test_mate_in_zero_is_refused():
    with pytest.raises(ValueError, match="mate in 0"):
        normalize_score(PovScore(Mate(0), chess.WHITE))


def test_describe_centipawns():
    assert describe(Evaluation(23, None, "e2e4")) == "+23 cp (positive = White is better)"
    assert describe(Evaluation(-8, None, "e7e5")).startswith("-8 cp")


def test_describe_white_mate():
    assert describe(Evaluation(None, 1, "a1a8")) == "White mates in 1"


def test_describe_black_mate():
    assert describe(Evaluation(None, -2, "a8a1")) == "Black mates in 2"


# ---------- real Stockfish ----------


def _find_stockfish() -> str | None:
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


def test_start_position_is_roughly_equal(engine):
    board = chess.Board()

    result = evaluate(engine, board, DEPTH)

    assert result.mate is None
    assert abs(result.cp) < 100
    assert chess.Move.from_uci(result.best_move) in board.legal_moves


def test_white_mate_in_one_is_positive(engine):
    result = evaluate(engine, chess.Board(WHITE_MATES_IN_1), DEPTH)

    assert result.cp is None
    assert result.mate == 1
    assert result.best_move == "a1a8"


def test_black_mate_in_one_is_negative(engine):
    result = evaluate(engine, chess.Board(BLACK_MATES_IN_1), DEPTH)

    assert result.cp is None
    assert result.mate == -1
    assert result.best_move == "a8a1"


@pytest.mark.parametrize(
    ("template", "turn", "sign"),
    [
        (WHITE_UP_A_QUEEN, "w", 1),
        (WHITE_UP_A_QUEEN, "b", 1),
        (BLACK_UP_A_QUEEN, "w", -1),
        (BLACK_UP_A_QUEEN, "b", -1),
    ],
)
def test_material_edge_has_the_same_sign_whoever_is_to_move(engine, template, turn, sign):
    result = evaluate(engine, chess.Board(template.format(turn=turn)), DEPTH)

    assert result.mate is None
    assert result.cp * sign > 300


@pytest.mark.parametrize("fen", [FOOLS_MATE, STALEMATE])
def test_finished_positions_are_refused(engine, fen):
    with pytest.raises(ValueError, match="game over"):
        evaluate(engine, chess.Board(fen), DEPTH)
