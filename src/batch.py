"""Analyze stored games with Stockfish and save the results. Safe to stop and restart.

Each game is saved in its own transaction, and games that already have results for this
engine and depth are skipped, so Ctrl+C loses at most the games in progress.

Two modes follow the same rules: one process (the default), or a pool of worker processes
that each analyze whole games. Workers never touch the database. They send results back
and this process saves them, one game at a time.
"""

import argparse
import signal
import sys
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Executor, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from functools import partial

import chess.engine
import psycopg

from analyze import PlyEval, evaluate_game
from db import connect, games_to_analyze, get_or_create_run, remaining_work, store_analysis
from engine import DEFAULT_DEPTH, open_engine
from loss import MoveLoss, move_losses

MAX_FAILURES = 25

ProgressCallback = Callable[[int, int, str, int, float], None]


@dataclass
class BatchResult:
    analyzed: int = 0
    positions: int = 0
    seconds: float = 0.0  # engine time, added up over all games
    wall_seconds: float = 0.0  # real elapsed time for the whole run
    failures: list[tuple[str, str]] = field(default_factory=list)  # (lichess_id, message)
    aborted: bool = False


@dataclass(frozen=True)
class Computed:
    """What comes back for one game: results to save, or the reason it failed."""

    game_id: int
    lichess_id: str
    plies: list[PlyEval] | None
    losses: list[MoveLoss] | None
    error: str | None
    seconds: float


def compute_game(engine: chess.engine.SimpleEngine, game: dict, depth: int) -> Computed:
    """Run Stockfish over one game and work out its losses. Touches no database."""
    started = time.perf_counter()
    try:
        plies = evaluate_game(engine, game["moves_san"], depth, game_key=game["lichess_id"])
        losses = move_losses(plies)
    except ValueError as exc:
        elapsed = time.perf_counter() - started
        return Computed(game["id"], game["lichess_id"], None, None, str(exc), elapsed)
    elapsed = time.perf_counter() - started
    return Computed(game["id"], game["lichess_id"], plies, losses, None, elapsed)


def record(
    conn: psycopg.Connection,
    run_id: int,
    computed: Computed,
    result: BatchResult,
    done: int,
    total: int,
    on_game: ProgressCallback | None,
) -> None:
    """Save one computed game, or note why it failed. Only ever runs in the main process."""
    error = computed.error
    if error is None:
        try:
            store_analysis(conn, run_id, computed.game_id, computed.plies, computed.losses)
        except (psycopg.DataError, psycopg.IntegrityError) as exc:
            error = str(exc)
    if error is not None:
        result.failures.append((computed.lichess_id, error))
        return

    evaluated = sum(1 for p in computed.plies if p.evaluation is not None)
    result.analyzed += 1
    result.positions += evaluated
    result.seconds += computed.seconds
    if on_game:
        on_game(done, total, computed.lichess_id, evaluated, computed.seconds)


def analyze_games(
    conn: psycopg.Connection,
    engine: chess.engine.SimpleEngine,
    run_id: int,
    depth: int,
    limit: int | None = None,
    on_game: ProgressCallback | None = None,
) -> BatchResult:
    """Analyze every game without results for this run (at most `limit`), newest first.

    Only errors caused by one game are caught. An engine crash or a lost connection
    propagates, because every later game would fail the same way.
    """
    games = games_to_analyze(conn, run_id, limit)
    result = BatchResult()
    started = time.perf_counter()

    for done, game in enumerate(games, start=1):
        computed = compute_game(engine, game, depth)
        record(conn, run_id, computed, result, done, len(games), on_game)
        if len(result.failures) > MAX_FAILURES:
            result.aborted = True
            break

    result.wall_seconds = time.perf_counter() - started
    return result


def analyze_games_parallel(
    conn: psycopg.Connection,
    executor: Executor,
    work: Callable[[dict, int], Computed],
    run_id: int,
    depth: int,
    limit: int | None = None,
    max_in_flight: int = 2,
    on_game: ProgressCallback | None = None,
) -> BatchResult:
    """Like analyze_games, but `work(game, depth)` runs on the executor.

    At most `max_in_flight` games are submitted at a time. Results are saved here, in the
    order they finish. If a worker raises (an engine crash), the error propagates and
    games that have not started are cancelled.
    """
    if max_in_flight < 1:
        raise ValueError("max_in_flight must be at least 1")

    games = games_to_analyze(conn, run_id, limit)
    total = len(games)
    result = BatchResult()
    started = time.perf_counter()
    waiting = iter(games)
    in_flight: set[Future] = set()
    done = 0

    def top_up() -> None:
        while len(in_flight) < max_in_flight:
            game = next(waiting, None)
            if game is None:
                return
            in_flight.add(executor.submit(work, game, depth))

    try:
        top_up()
        while in_flight:
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in finished:
                in_flight.discard(future)
                done += 1
                record(conn, run_id, future.result(), result, done, total, on_game)
                if len(result.failures) > MAX_FAILURES:
                    result.aborted = True
                    return result
            top_up()
    finally:
        for future in in_flight:
            future.cancel()
        result.wall_seconds = time.perf_counter() - started

    return result


def ignore_interrupt() -> None:
    """Runs in each worker. Ctrl+C is handled by the main process, not by every worker."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def process_game(game: dict, depth: int, stockfish_path: str) -> Computed:
    """Runs in a worker process: a fresh Stockfish for this one game, always closed."""
    with open_engine(stockfish_path) as engine:
        return compute_game(engine, game, depth)


def analyze_games_in_processes(
    conn: psycopg.Connection,
    stockfish_path: str,
    run_id: int,
    depth: int,
    workers: int,
    limit: int | None = None,
    on_game: ProgressCallback | None = None,
) -> BatchResult:
    with ProcessPoolExecutor(max_workers=workers, initializer=ignore_interrupt) as pool:
        return analyze_games_parallel(
            conn,
            pool,
            partial(process_game, stockfish_path=stockfish_path),
            run_id,
            depth,
            limit,
            max_in_flight=workers * 2,
            on_game=on_game,
        )


def engine_name(stockfish_path: str) -> str:
    with open_engine(stockfish_path) as engine:
        return engine.id.get("name", "unknown engine")


def main() -> None:
    from config import DATABASE_URL, STOCKFISH_PATH

    parser = argparse.ArgumentParser(description="Analyze stored games with Stockfish.")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--limit", type=int, default=None, help="analyze at most this many games")
    parser.add_argument("--workers", type=int, default=1, help="worker processes (1 = just one)")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")

    def progress(index: int, total: int, lichess_id: str, positions: int, seconds: float) -> None:
        print(f"[{index}/{total}] {lichess_id}  {positions} positions  {seconds:.1f}s", flush=True)

    try:
        with connect(DATABASE_URL) as conn:
            name = engine_name(STOCKFISH_PATH)
            run_id = get_or_create_run(conn, name, args.depth)
            games_left, moves_left = remaining_work(conn, run_id)
            print(
                f"{name} at depth {args.depth}, {args.workers} worker(s): "
                f"{games_left} games to analyze ({moves_left:,} moves)"
            )
            if games_left == 0:
                print("Nothing to do.")
                return
            if args.workers == 1:
                with open_engine(STOCKFISH_PATH) as engine:
                    result = analyze_games(conn, engine, run_id, args.depth, args.limit, progress)
            else:
                result = analyze_games_in_processes(
                    conn, STOCKFISH_PATH, run_id, args.depth, args.workers, args.limit, progress
                )
    except KeyboardInterrupt:
        print("\nStopped. Finished games are saved; run the same command to continue.")
        sys.exit(130)

    print(
        f"\nAnalyzed {result.analyzed} games, {result.positions} positions "
        f"in {result.wall_seconds:.0f}s"
    )
    if result.positions:
        per_position = result.wall_seconds / result.positions
        hours = per_position * (moves_left + games_left) / 3600
        print(f"{per_position:.3f}s per position (real time)")
        print(f"Whole remaining queue at this speed: {hours:.1f} hours")
    if args.workers > 1 and result.wall_seconds:
        speedup = result.seconds / result.wall_seconds
        print(f"Engine time added up: {result.seconds:.0f}s, about {speedup:.1f}x one process")
    for lichess_id, message in result.failures:
        print(f"FAILED {lichess_id}: {message}", file=sys.stderr)
    if result.aborted:
        print(f"Aborted: more than {MAX_FAILURES} games failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
