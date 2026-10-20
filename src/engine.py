"""Ask Stockfish about a position.

Sign convention, used everywhere in this project:
  * cp is centipawns from WHITE's point of view: positive means White is better.
  * mate is signed moves-to-mate from WHITE's point of view: +3 means White mates in 3,
    -3 means Black mates in 3.
  * Exactly one of cp and mate is set, matching the CHECK constraint on evaluations.
"""

import argparse
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import chess
import chess.engine

DEFAULT_DEPTH = 14


@dataclass(frozen=True)
class Evaluation:
    cp: int | None
    mate: int | None
    best_move: str | None  # UCI, e.g. "e2e4"


def normalize_score(pov: chess.engine.PovScore) -> tuple[int | None, int | None]:
    """Turn Stockfish's side-to-move score into (cp, mate) from White's point of view."""
    white = pov.white()
    mate = white.mate()
    if mate is None:
        return white.score(), None
    if mate == 0:
        raise ValueError("mate in 0 does not say who won: finished games must not be evaluated")
    return None, mate


@contextmanager
def open_engine(
    path: str, threads: int = 1, hash_mb: int = 64
) -> Iterator[chess.engine.SimpleEngine]:
    """Start Stockfish, configure it, and always shut the process down afterwards."""
    with chess.engine.SimpleEngine.popen_uci(path) as engine:
        engine.configure({"Threads": threads, "Hash": hash_mb})
        yield engine


def evaluate(
    engine: chess.engine.SimpleEngine, board: chess.Board, depth: int = DEFAULT_DEPTH
) -> Evaluation:
    """Evaluate the position on the board, searching to a fixed depth."""
    if board.is_game_over():
        raise ValueError("position is game over: nothing to evaluate")
    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    cp, mate = normalize_score(info["score"])
    pv = info.get("pv")
    return Evaluation(cp, mate, pv[0].uci() if pv else None)


def describe(evaluation: Evaluation) -> str:
    if evaluation.mate is not None:
        side = "White" if evaluation.mate > 0 else "Black"
        return f"{side} mates in {abs(evaluation.mate)}"
    return f"{evaluation.cp:+d} cp (positive = White is better)"


def main() -> None:
    from config import STOCKFISH_PATH

    parser = argparse.ArgumentParser(description="Evaluate one position with Stockfish.")
    parser.add_argument(
        "fen", nargs="?", default=chess.STARTING_FEN, help="default: start position"
    )
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    args = parser.parse_args()

    try:
        board = chess.Board(args.fen)
        with open_engine(STOCKFISH_PATH) as engine:
            name = engine.id.get("name", "unknown engine")
            started = time.perf_counter()
            result = evaluate(engine, board, args.depth)
            elapsed = time.perf_counter() - started
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    side = "White" if board.turn == chess.WHITE else "Black"
    print(f"Engine:       {name}")
    print(f"Side to move: {side}")
    print(f"Evaluation:   {describe(result)}")
    print(f"Best move:    {result.best_move}")
    print(f"Search:       depth {args.depth}, {elapsed:.2f}s")


if __name__ == "__main__":
    main()
