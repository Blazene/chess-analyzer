"""End-to-end checks with the real Stockfish: mate scores and move loss for both colours."""

import pytest
from analysis_helpers import find_stockfish

from analyze import evaluate_game
from engine import open_engine
from loss import move_losses

STOCKFISH = find_stockfish()
pytestmark = pytest.mark.skipif(STOCKFISH is None, reason="Stockfish is not installed")

DEPTH = 10


@pytest.fixture(scope="module")
def engine():
    with open_engine(STOCKFISH) as running:
        yield running


def analysed(engine, moves_san):
    results = evaluate_game(engine, moves_san, depth=DEPTH, game_key=moves_san)
    return results, {m.ply: m for m in move_losses(results)}


def test_white_walks_into_a_forced_mate(engine):
    results, losses = analysed(engine, "f3 e5 g4 Qh4#")

    assert results[3].evaluation.mate == -1  # Black mates in one: negative for White
    assert losses[3].mover == "white"
    assert losses[3].loss_cp > 500
    assert losses[3].label == "blunder"
    assert (losses[4].mover, losses[4].loss_cp, losses[4].label) == ("black", 0, "ok")


def test_black_walks_into_a_forced_mate(engine):
    results, losses = analysed(engine, "e4 f6 d4 g5 Qh5#")

    assert results[4].evaluation.mate == 1  # White mates in one: positive for White
    assert losses[4].mover == "black"
    assert losses[4].loss_cp > 500
    assert losses[4].label == "blunder"
    assert (losses[5].mover, losses[5].loss_cp, losses[5].label) == ("white", 0, "ok")


def test_a_normal_opening_has_no_serious_mistakes(engine):
    _, losses = analysed(engine, "e4 e5 Nf3 Nc6 Bb5 a6")

    assert len(losses) == 6
    assert {m.label for m in losses.values()} <= {"ok", "inaccuracy"}
