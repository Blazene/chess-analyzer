"""Walk a game through Stockfish, one position at a time."""

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import chess
import chess.engine

from engine import DEFAULT_DEPTH, Evaluation, evaluate, open_engine
from loss import move_losses, summarize

# Used ONLY to draw curves and preview swings. Day 10 decides the real treatment of mates.
MATE_DISPLAY_CP = 1000
BAR_SCALE_CP = 500
BAR_HALF_WIDTH = 10


@dataclass(frozen=True)
class PlyEval:
    ply: int  # 0 = the starting position, N = the position after move N
    san: str | None  # the move that led to this position (None at ply 0)
    evaluation: Evaluation | None  # None when the game is already over in this position
    seconds: float
    checkmate: bool = False  # the game ended here by checkmate


def evaluate_game(
    engine: chess.engine.SimpleEngine,
    moves_san: str,
    depth: int = DEFAULT_DEPTH,
    game_key: object | None = None,
    on_ply: Callable[[PlyEval], None] | None = None,
) -> list[PlyEval]:
    """Evaluate the starting position and the position after every move, in order.

    One board is walked with push(), so the engine sees the full move history
    (which it needs to recognise repetition draws).
    """
    board = chess.Board()
    results: list[PlyEval] = []

    for ply, san in enumerate([None, *moves_san.split()]):
        if san is not None:
            try:
                board.push_san(san)
            except ValueError as exc:
                raise ValueError(f"cannot replay move '{san}' at ply {ply}: {exc}") from exc

        started = time.perf_counter()
        evaluation = None
        if not board.is_game_over():
            evaluation = evaluate(engine, board, depth, game=game_key)
        result = PlyEval(ply, san, evaluation, time.perf_counter() - started, board.is_checkmate())

        results.append(result)
        if on_ply:
            on_ply(result)

    return results


def display_cp(evaluation: Evaluation) -> int:
    """A single number for drawing and comparing. Mates count as +/- 1000 cp (display only)."""
    if evaluation.mate is not None:
        return MATE_DISPLAY_CP if evaluation.mate > 0 else -MATE_DISPLAY_CP
    return evaluation.cp


def biggest_swings(results: Sequence[PlyEval], top: int = 3) -> list[tuple[int, int]]:
    """The moves that hurt the player who made them most: [(ply, centipawns lost), ...].

    Preview only. Day 10 turns this into the real centipawn-loss column.
    """
    swings = []
    for before, after in zip(results, results[1:], strict=False):
        if before.evaluation is None or after.evaluation is None:
            continue
        was, now = display_cp(before.evaluation), display_cp(after.evaluation)
        white_moved = after.ply % 2 == 1
        loss = (was - now) if white_moved else (now - was)
        if loss > 0:
            swings.append((after.ply, loss))
    return sorted(swings, key=lambda swing: swing[1], reverse=True)[:top]


def move_label(ply: int, san: str | None) -> str:
    if san is None:
        return "start"
    number = (ply + 1) // 2
    return f"{number}. {san}" if ply % 2 == 1 else f"{number}... {san}"


def bar(cp: int) -> str:
    """Black-better blocks grow to the left of the bar, White-better to the right."""
    clipped = max(-BAR_SCALE_CP, min(BAR_SCALE_CP, cp))
    steps = round(clipped / BAR_SCALE_CP * BAR_HALF_WIDTH)
    left = "#" * max(0, -steps)
    right = "#" * max(0, steps)
    return f"{left:>{BAR_HALF_WIDTH}}|{right:<{BAR_HALF_WIDTH}}"


def cp_text(evaluation: Evaluation) -> str:
    if evaluation.mate is not None:
        return f"#{evaluation.mate:+d}"
    return f"{evaluation.cp:+d}"


def print_curve(results: Sequence[PlyEval]) -> None:
    print("ply  move            eval  Black better <-|-> White better")
    for r in results:
        if r.evaluation is None:
            text, graphic = "game over", ""
        else:
            text, graphic = cp_text(r.evaluation), bar(display_cp(r.evaluation))
        print(f"{r.ply:>3}  {move_label(r.ply, r.san):<12} {text:>9}  {graphic}")


def print_swings(results: Sequence[PlyEval]) -> None:
    losses = move_losses(results)
    print("\nLoss per move, from the mover's point of view (mates capped at 1000):")
    for mover in ("white", "black"):
        average, counts = summarize(losses, mover)
        if average is None:
            continue
        print(
            f"  {mover:<5} average {average:.0f} cp | {counts['inaccuracy']} inaccuracies, "
            f"{counts['mistake']} mistakes, {counts['blunder']} blunders"
        )
    worst = sorted(losses, key=lambda m: m.loss_cp, reverse=True)[:5]
    worst = [m for m in worst if m.loss_cp > 0]
    if not worst:
        print("\nNo move made the position worse.")
        return
    print("\nWorst moves:")
    for m in worst:
        print(
            f"  ply {m.ply:>3}  {move_label(m.ply, m.san):<12} {m.mover:<5} "
            f"lost {m.loss_cp:>4} cp ({m.win_drop:4.1f} win points)  {m.label}"
        )


def print_timing(results: Sequence[PlyEval], games_total: int, moves_total: int) -> None:
    evaluated = [r for r in results if r.evaluation is not None]
    total = sum(r.seconds for r in results)
    average = total / len(evaluated)
    positions = games_total + moves_total  # every move, plus the start position of each game
    hours = average * positions / 3600
    print(f"\nThis game: {len(evaluated)} positions in {total:.1f}s ({average:.2f}s each)")
    print(f"Rough estimate for all {games_total} games ({positions:,} positions): ", end="")
    print(f"{hours:.1f} hours on one process")


def main() -> None:
    from config import DATABASE_URL, STOCKFISH_PATH
    from db import connect, get_game, table_counts

    parser = argparse.ArgumentParser(description="Walk one stored game through Stockfish.")
    parser.add_argument("lichess_id", nargs="?", default=None, help="default: your newest game")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    args = parser.parse_args()

    with connect(DATABASE_URL) as conn:
        game = get_game(conn, args.lichess_id)
        games_total, moves_total = table_counts(conn)
    if game is None:
        print("No such game in the database", file=sys.stderr)
        sys.exit(1)

    print(
        f"Game {game['lichess_id']}: you were {game['color']}, {game['result']} "
        f"({game['status']}) against {game['opponent_name']}"
    )
    print(f"Analyzing at depth {args.depth} ", end="", flush=True)

    try:
        with open_engine(STOCKFISH_PATH) as engine:
            engine_name = engine.id.get("name", "unknown engine")
            results = evaluate_game(
                engine,
                game["moves_san"],
                args.depth,
                game_key=game["lichess_id"],
                on_ply=lambda _result: print(".", end="", flush=True),
            )
    except ValueError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\nEngine: {engine_name}\n")
    print_curve(results)
    print_swings(results)
    print_timing(results, games_total, moves_total)


if __name__ == "__main__":
    main()
