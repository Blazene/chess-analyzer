"""Centipawn loss and move classification. Pure functions: no engine, no database.

Rules (decided on Day 10):
  * Every score is clamped to +/-CP_CAP. A mate counts as the cap for the side that mates,
    whatever the distance, so mate in 3 and mate in 9 are the same.
  * Loss is measured from the point of view of the player who moved, and never below zero.
  * Labels come from the drop in win probability, so losing 200 cp in a won position is not
    treated like losing 200 cp in an equal one.
  * A move that delivers checkmate has zero loss. A game that ends in a draw counts as 0 cp.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine import Evaluation

if TYPE_CHECKING:
    from analyze import PlyEval

CP_CAP = 1000
WIN_K = 0.00368208  # steepness of the cp -> win% curve (recalled from Lichess, not verified)

# Thresholds in win-percentage points lost. Tune after the full run (Day 13).
INACCURACY_DROP = 5.0
MISTAKE_DROP = 10.0
BLUNDER_DROP = 15.0

OK = "ok"
INACCURACY = "inaccuracy"
MISTAKE = "mistake"
BLUNDER = "blunder"


@dataclass(frozen=True)
class MoveLoss:
    ply: int
    san: str
    mover: str  # "white" or "black"
    loss_cp: int  # integer, mover's point of view, never negative
    win_drop: float  # win-percentage points lost, derived and never stored
    label: str


def clamp_cp(cp: int) -> int:
    return max(-CP_CAP, min(CP_CAP, cp))


def to_cp(evaluation: Evaluation) -> int:
    """One capped number from White's point of view. Any mate becomes the cap."""
    if evaluation.mate is not None:
        return CP_CAP if evaluation.mate > 0 else -CP_CAP
    return clamp_cp(evaluation.cp)


def win_percent(cp: int) -> float:
    """Chance of winning, 0 to 100, for the side the centipawns favour."""
    return 100 / (1 + math.exp(-WIN_K * cp))


def classify(win_drop: float) -> str:
    if win_drop >= BLUNDER_DROP:
        return BLUNDER
    if win_drop >= MISTAKE_DROP:
        return MISTAKE
    if win_drop >= INACCURACY_DROP:
        return INACCURACY
    return OK


def move_losses(results: Sequence["PlyEval"]) -> list[MoveLoss]:
    """One MoveLoss per move: compare the position before the move with the one after it."""
    losses = []
    for before, after in zip(results, results[1:], strict=False):
        if before.evaluation is None:
            raise ValueError(f"no evaluation before ply {after.ply}: cannot measure the move")

        white_moved = after.ply % 2 == 1
        mover = "white" if white_moved else "black"

        if after.evaluation is None and after.checkmate:
            loss_cp, win_drop = 0, 0.0
        else:
            white_after = 0 if after.evaluation is None else to_cp(after.evaluation)
            sign = 1 if white_moved else -1
            was, now = sign * to_cp(before.evaluation), sign * white_after
            loss_cp = max(0, was - now)
            win_drop = max(0.0, win_percent(was) - win_percent(now))

        losses.append(MoveLoss(after.ply, after.san, mover, loss_cp, win_drop, classify(win_drop)))
    return losses


def summarize(losses: Sequence[MoveLoss], mover: str) -> tuple[float | None, Counter[str]]:
    """Average loss and label counts for one side. No moves gives (None, empty)."""
    mine = [m for m in losses if m.mover == mover]
    if not mine:
        return None, Counter()
    return sum(m.loss_cp for m in mine) / len(mine), Counter(m.label for m in mine)
