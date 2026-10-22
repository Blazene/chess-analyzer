"""Time the same games with different numbers of worker processes. Saves nothing."""

import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from functools import partial

from batch import ignore_interrupt, process_game
from db import connect, recent_games
from engine import DEFAULT_DEPTH


def run(games: list[dict], depth: int, workers: int, stockfish_path: str) -> float:
    work = partial(process_game, stockfish_path=stockfish_path)
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers, initializer=ignore_interrupt) as pool:
        computed = list(pool.map(work, games, [depth] * len(games)))
    elapsed = time.perf_counter() - started
    failed = [c for c in computed if c.error]
    if failed:
        raise SystemExit(
            f"{len(failed)} games failed, e.g. {failed[0].lichess_id}: {failed[0].error}"
        )
    return elapsed


def main() -> None:
    from config import DATABASE_URL, STOCKFISH_PATH

    parser = argparse.ArgumentParser(description="Time the same games with N worker processes.")
    parser.add_argument("--games", type=int, default=12)
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--workers", default="1,2,4", help="comma-separated, e.g. 1,2,4,6,1")
    args = parser.parse_args()

    with connect(DATABASE_URL) as conn:
        games = recent_games(conn, args.games)
    counts = [int(part) for part in args.workers.split(",")]
    positions = sum(len(game["moves_san"].split()) + 1 for game in games)
    print(f"{len(games)} games, about {positions} positions, depth {args.depth}. Saves nothing.")

    baseline = None
    for workers in counts:
        elapsed = run(games, args.depth, workers, STOCKFISH_PATH)
        baseline = baseline or elapsed
        speed = positions / elapsed
        print(
            f"{workers:>2} workers: {elapsed:6.1f}s  {speed:5.1f} positions/s  "
            f"{baseline / elapsed:4.1f}x"
        )


if __name__ == "__main__":
    main()
