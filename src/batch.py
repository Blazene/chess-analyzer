"""Analyze stored games with Stockfish and save the results. Safe to stop and restart.

Each game is saved in its own transaction, and games that already have results for this
engine and depth are skipped, so Ctrl+C loses at most the game in progress.
"""

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import chess.engine
import psycopg

from analyze import evaluate_game
from db import (
    connect,
    games_to_analyze,
    get_or_create_run,
    remaining_work,
    store_analysis,
)
from engine import DEFAULT_DEPTH, open_engine
from loss import move_losses

MAX_FAILURES = 25


@dataclass
class BatchResult:
    analyzed: int = 0
    positions: int = 0
    seconds: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)  # (lichess_id, message)
    aborted: bool = False


def analyze_games(
    conn: psycopg.Connection,
    engine: chess.engine.SimpleEngine,
    run_id: int,
    depth: int,
    limit: int | None = None,
    on_game: Callable[[int, int, str, int, float], None] | None = None,
) -> BatchResult:
    """Analyze every game without results for this run (at most `limit`), newest first.

    Only errors caused by one game are caught. An engine crash or a lost connection
    propagates, because every later game would fail the same way.
    """
    games = games_to_analyze(conn, run_id, limit)
    result = BatchResult()

    for index, game in enumerate(games, start=1):
        started = time.perf_counter()
        try:
            plies = evaluate_game(engine, game["moves_san"], depth, game_key=game["lichess_id"])
            losses = move_losses(plies)
            store_analysis(conn, run_id, game["id"], plies, losses)
        except (ValueError, psycopg.DataError, psycopg.IntegrityError) as exc:
            result.failures.append((game["lichess_id"], str(exc)))
            if len(result.failures) > MAX_FAILURES:
                result.aborted = True
                break
            continue

        elapsed = time.perf_counter() - started
        evaluated = sum(1 for p in plies if p.evaluation is not None)
        result.analyzed += 1
        result.positions += evaluated
        result.seconds += elapsed
        if on_game:
            on_game(index, len(games), game["lichess_id"], evaluated, elapsed)

    return result


def main() -> None:
    from config import DATABASE_URL, STOCKFISH_PATH

    parser = argparse.ArgumentParser(description="Analyze stored games with Stockfish.")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--limit", type=int, default=None, help="analyze at most this many games")
    args = parser.parse_args()

    def progress(index: int, total: int, lichess_id: str, positions: int, seconds: float) -> None:
        print(f"[{index}/{total}] {lichess_id}  {positions} positions  {seconds:.1f}s", flush=True)

    try:
        with connect(DATABASE_URL) as conn, open_engine(STOCKFISH_PATH) as engine:
            name = engine.id.get("name", "unknown engine")
            run_id = get_or_create_run(conn, name, args.depth)
            games_left, moves_left = remaining_work(conn, run_id)
            print(
                f"{name} at depth {args.depth}: {games_left} games to analyze "
                f"({moves_left:,} moves)"
            )
            if games_left == 0:
                print("Nothing to do.")
                return
            result = analyze_games(conn, engine, run_id, args.depth, args.limit, progress)
    except KeyboardInterrupt:
        print("\nStopped. Finished games are saved; run the same command to continue.")
        sys.exit(130)

    print(
        f"\nAnalyzed {result.analyzed} games, {result.positions} positions, {result.seconds:.0f}s"
    )
    if result.positions:
        average = result.seconds / result.positions
        hours = average * (moves_left + games_left) / 3600
        print(
            f"{average:.3f}s per position. Whole remaining queue at this speed: {hours:.1f} hours"
        )
    for lichess_id, message in result.failures:
        print(f"FAILED {lichess_id}: {message}", file=sys.stderr)
    if result.aborted:
        print(f"Aborted: more than {MAX_FAILURES} games failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
