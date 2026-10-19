"""Load games from Lichess into PostgreSQL. Safe to run as often as you like."""

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import psycopg

from config import DATABASE_URL, LICHESS_USERNAME
from db import (
    connect,
    full_sync_done,
    mark_full_sync,
    newest_played_at,
    store_game,
    table_counts,
)
from fetch import stream_games
from models import parse_game

# Lichess filters on when a game STARTED, but a correspondence game can finish weeks later.
# So an incremental run starts this far before the newest stored game.
OVERLAP = timedelta(days=30)
# If more games than this fail in one run, something systematic is wrong: stop.
MAX_FAILURES = 25
PROGRESS_EVERY = 250

# Problems with ONE game: report them and carry on. Anything else (a lost connection,
# a bug in our code) is not caught and stops the run.
GAME_ERRORS = (
    ValueError,
    KeyError,
    psycopg.errors.IntegrityError,
    psycopg.errors.DataError,
)


class TooManyFailures(RuntimeError):
    """Raised when so many games fail that something systematic is probably wrong."""


@dataclass
class SyncReport:
    seen: int = 0
    inserted: int = 0
    already_stored: int = 0
    skipped: Counter = field(default_factory=Counter)
    failures: list[tuple[str, str]] = field(default_factory=list)  # (lichess id, reason)


def sync_games(
    conn: psycopg.Connection,
    raw_games: Iterable[dict],
    username: str,
    on_progress: Callable[[SyncReport], None] | None = None,
) -> SyncReport:
    """Parse and store raw Lichess games one at a time. One bad game never stops the run."""
    report = SyncReport()
    for raw in raw_games:
        report.seen += 1
        try:
            game = parse_game(raw, username)
            if game is None:
                report.skipped[f"{raw.get('variant')}/{raw.get('status')}"] += 1
            elif store_game(conn, game):
                report.inserted += 1
            else:
                report.already_stored += 1
        except GAME_ERRORS as exc:
            report.failures.append((str(raw.get("id", "?")), f"{type(exc).__name__}: {exc}"))
            if len(report.failures) > MAX_FAILURES:
                raise TooManyFailures(
                    f"More than {MAX_FAILURES} games failed. Last: {report.failures[-1]}"
                ) from exc

        if on_progress and report.seen % PROGRESS_EVERY == 0:
            on_progress(report)
    return report


def choose_since(conn: psycopg.Connection, username: str, full: bool = False) -> datetime | None:
    """Where to start fetching. None means the whole history."""
    if full or not full_sync_done(conn, username):
        return None
    newest = newest_played_at(conn)
    return None if newest is None else newest - OVERLAP


def _progress(report: SyncReport) -> None:
    print(f"  ...{report.seen} read, {report.inserted} new", flush=True)


def _print_report(report: SyncReport) -> None:
    print(
        f"\nRead {report.seen} games: {report.inserted} new, "
        f"{report.already_stored} already stored, "
        f"{sum(report.skipped.values())} skipped, {len(report.failures)} failed"
    )
    for reason, count in report.skipped.most_common():
        print(f"  skipped {count} x {reason}")
    for game_id, reason in report.failures:
        print(f"  FAILED {game_id}: {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Lichess games into PostgreSQL.")
    parser.add_argument(
        "--full", action="store_true", help="fetch the whole history, ignoring the cursor"
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="only the newest N games (for testing). Never marks the history as complete",
    )
    args = parser.parse_args()
    if args.full and args.max is not None:
        parser.error("--max cannot be combined with --full")

    with connect(DATABASE_URL) as conn:
        if args.max is not None:
            since = None
            mode = f"partial: newest {args.max} games only"
        else:
            since = choose_since(conn, LICHESS_USERNAME, full=args.full)
            if since is None:
                mode = "full history"
            else:
                mode = f"incremental since {since.astimezone(UTC):%Y-%m-%d %H:%M} UTC"
        print(f"Mode: {mode}")

        since_ms = None if since is None else int(since.timestamp() * 1000)
        games = stream_games(LICHESS_USERNAME, max_games=args.max, since_ms=since_ms)
        try:
            report = sync_games(conn, games, LICHESS_USERNAME, on_progress=_progress)
        except TooManyFailures as exc:
            print(f"Aborted: {exc}", file=sys.stderr)
            sys.exit(1)

        # Only a run that read the whole history to the end may claim it is complete.
        if args.max is None and since is None:
            mark_full_sync(conn, LICHESS_USERNAME)

        _print_report(report)
        games_total, moves_total = table_counts(conn)
        print(f"Database now holds {games_total} games and {moves_total} moves")


if __name__ == "__main__":
    main()
