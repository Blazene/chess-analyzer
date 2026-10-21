"""Read-only analytics over time: by time control, by time left on the clock, by month.

Only SELECT statements live here. Everything counts YOUR moves and games only, and skips
games against the computer unless asked. Integers come out of SQL; percentages and averages
are computed in Python. The "your moves" filter is the same rule as in insights.py.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from db import connect, get_or_create_run
from engine import DEFAULT_DEPTH

# Time left on your clock AFTER the move, in centiseconds, shortest first. None = no limit.
CLOCK_BUCKETS = (
    ("<10s", 1_000),
    ("10-30s", 3_000),
    ("30-60s", 6_000),
    ("1-3 min", 18_000),
    ("3 min+", None),
)


def _bucket_case() -> str:
    """SQL CASE for the buckets above. Built from the constants only, never from user input."""
    whens = " ".join(f"WHEN clock_cs < {limit} THEN '{name}'" for name, limit in CLOCK_BUCKETS[:-1])
    return f"CASE {whens} ELSE '{CLOCK_BUCKETS[-1][0]}' END"


SPEED_RESULTS_SQL = """
SELECT g.speed,
       count(*) AS games,
       count(*) FILTER (WHERE g.result = 'win'),
       count(*) FILTER (WHERE g.result = 'draw'),
       count(*) FILTER (WHERE g.result = 'loss'),
       count(*) FILTER (WHERE g.result = 'loss' AND g.status = 'outoftime'),
       count(*) FILTER (WHERE g.result = 'win' AND g.status = 'outoftime')
FROM games g
WHERE %(include_ai)s OR NOT g.opponent_is_ai
GROUP BY g.speed
ORDER BY games DESC, g.speed
"""

# A move is yours when the ply parity matches your colour (odd plies are White's).
MY_MOVES = """
WITH my_moves AS (
    SELECT g.speed, g.played_at, m.ply, m.clock_cs, l.loss_cp, l.label
    FROM games g
    JOIN moves m ON m.game_id = g.id
    JOIN move_losses l
      ON l.game_id = m.game_id AND l.ply = m.ply AND l.analysis_run_id = %(run_id)s
    WHERE (mod(m.ply, 2) = 1) = (g.color = 'white')
      AND (%(include_ai)s OR NOT g.opponent_is_ai)
)
"""

SPEED_ACCURACY_SQL = (
    MY_MOVES
    + """
SELECT speed, count(*), sum(loss_cp), count(*) FILTER (WHERE label = 'blunder')
FROM my_moves
GROUP BY speed
ORDER BY 2 DESC, 1
"""
)

MONTH_RESULTS_SQL = """
SELECT to_char(g.played_at AT TIME ZONE 'UTC', 'YYYY-MM'),
       count(*),
       count(*) FILTER (WHERE g.result = 'win'),
       count(*) FILTER (WHERE g.result = 'draw'),
       count(*) FILTER (WHERE g.result = 'loss'),
       coalesce(sum(g.rating), 0),
       count(g.rating)
FROM games g
WHERE %(include_ai)s OR NOT g.opponent_is_ai
GROUP BY 1
ORDER BY 1
"""

MONTH_ACCURACY_SQL = (
    MY_MOVES
    + """
SELECT to_char(played_at AT TIME ZONE 'UTC', 'YYYY-MM'),
       count(*), sum(loss_cp), count(*) FILTER (WHERE label = 'blunder')
FROM my_moves
GROUP BY 1
ORDER BY 1
"""
)


@dataclass(frozen=True)
class SpeedRecord:
    speed: str
    games: int
    wins: int
    draws: int
    losses: int
    lost_on_time: int
    won_on_time: int

    @property
    def score(self) -> float:
        """Wins plus half of draws, as a share of games (0 to 1)."""
        return (self.wins + 0.5 * self.draws) / self.games

    @property
    def flag_loss_rate(self) -> float | None:
        """The share of your losses that were on time, or None if you have no losses."""
        return self.lost_on_time / self.losses if self.losses else None


@dataclass(frozen=True)
class MonthResult:
    month: str  # "YYYY-MM", in UTC
    games: int
    wins: int
    draws: int
    losses: int
    rating_sum: int
    rating_count: int

    @property
    def score(self) -> float:
        return (self.wins + 0.5 * self.draws) / self.games

    @property
    def avg_rating(self) -> float | None:
        return self.rating_sum / self.rating_count if self.rating_count else None


@dataclass(frozen=True)
class GroupStats:
    """Your moves in one group (a speed, a clock bucket or a month)."""

    key: str
    moves: int
    total_loss_cp: int
    blunders: int

    @property
    def avg_loss_cp(self) -> float:
        return self.total_loss_cp / self.moves

    @property
    def blunder_rate(self) -> float:
        return self.blunders / self.moves


def speed_results(conn: psycopg.Connection, include_ai: bool = False) -> list[SpeedRecord]:
    """Results per time control, most played first."""
    rows = conn.execute(SPEED_RESULTS_SQL, {"include_ai": include_ai}).fetchall()
    return [SpeedRecord(*row) for row in rows]


def speed_accuracy(
    conn: psycopg.Connection, run_id: int, include_ai: bool = False
) -> list[GroupStats]:
    """Your average loss and blunder rate per time control."""
    params = {"run_id": run_id, "include_ai": include_ai}
    return [GroupStats(*row) for row in conn.execute(SPEED_ACCURACY_SQL, params).fetchall()]


def clock_accuracy(
    conn: psycopg.Connection,
    run_id: int,
    speed: str | None = None,
    include_ai: bool = False,
) -> list[GroupStats]:
    """Your average loss and blunder rate by time left after the move, shortest first.

    Moves with no recorded clock are left out, and so are empty buckets.
    """
    params: dict = {"run_id": run_id, "include_ai": include_ai}
    speed_filter = ""
    if speed is not None:
        params["speed"] = speed
        speed_filter = "AND speed = %(speed)s"
    sql = (
        MY_MOVES
        + f"""
SELECT {_bucket_case()}, count(*), sum(loss_cp), count(*) FILTER (WHERE label = 'blunder')
FROM my_moves
WHERE clock_cs IS NOT NULL {speed_filter}
GROUP BY 1
"""
    )
    by_bucket = {row[0]: GroupStats(*row) for row in conn.execute(sql, params).fetchall()}
    return [by_bucket[name] for name, _ in CLOCK_BUCKETS if name in by_bucket]


def monthly_results(conn: psycopg.Connection, include_ai: bool = False) -> list[MonthResult]:
    """Results per calendar month (UTC), oldest first. Months with no games are not listed."""
    rows = conn.execute(MONTH_RESULTS_SQL, {"include_ai": include_ai}).fetchall()
    return [MonthResult(*row) for row in rows]


def monthly_accuracy(
    conn: psycopg.Connection, run_id: int, include_ai: bool = False
) -> list[GroupStats]:
    """Your average loss and blunder rate per month (UTC), analyzed games only."""
    params = {"run_id": run_id, "include_ai": include_ai}
    return [GroupStats(*row) for row in conn.execute(MONTH_ACCURACY_SQL, params).fetchall()]


def format_speeds(results: Sequence[SpeedRecord], accuracy: Sequence[GroupStats]) -> str:
    if not results:
        return "No games yet."
    by_speed = {s.key: s for s in accuracy}
    lines = [
        f"{'speed':<15} {'games':>5} {'W':>4} {'D':>4} {'L':>4} {'score':>7} "
        f"{'lost on time':>14} {'avg loss':>9} {'blunders':>9}"
    ]
    for r in results:
        stats = by_speed.get(r.speed)
        share = r.flag_loss_rate
        on_time = "-" if share is None else f"{r.lost_on_time} ({share:.0%})"
        avg = "-" if stats is None else f"{stats.avg_loss_cp:.0f}cp"
        rate = "-" if stats is None else f"{stats.blunder_rate:.1%}"
        lines.append(
            f"{r.speed:<15} {r.games:>5} {r.wins:>4} {r.draws:>4} {r.losses:>4} "
            f"{r.score:>7.1%} {on_time:>14} {avg:>9} {rate:>9}"
        )
    total_games = sum(r.games for r in results)
    total_moves = sum(s.moves for s in accuracy)
    lines.append(f"\nGames: {total_games:,}. Your analyzed moves: {total_moves:,}.")
    return "\n".join(lines)


def format_clock(stats: Sequence[GroupStats]) -> str:
    if not stats:
        return "No moves with a recorded clock."
    lines = [f"{'time left':<10} {'your moves':>10} {'avg loss':>9} {'blunders':>9}"]
    for s in stats:
        lines.append(f"{s.key:<10} {s.moves:>10,} {s.avg_loss_cp:>7.0f}cp {s.blunder_rate:>9.1%}")
    return "\n".join(lines)


def format_months(results: Sequence[MonthResult], accuracy: Sequence[GroupStats], last: int) -> str:
    if not results:
        return "No games yet."
    by_month = {s.key: s for s in accuracy}
    lines = [
        f"{'month':<8} {'games':>5} {'score':>7} {'avg rating':>10} {'avg loss':>9} {'blunders':>9}"
    ]
    for r in results[-last:]:
        stats = by_month.get(r.month)
        rating = "-" if r.avg_rating is None else f"{r.avg_rating:.0f}"
        avg = "-" if stats is None else f"{stats.avg_loss_cp:.0f}cp"
        rate = "-" if stats is None else f"{stats.blunder_rate:.1%}"
        lines.append(f"{r.month:<8} {r.games:>5} {r.score:>7.1%} {rating:>10} {avg:>9} {rate:>9}")
    return "\n".join(lines)


def main() -> None:
    from batch import engine_name
    from config import DATABASE_URL, STOCKFISH_PATH

    parser = argparse.ArgumentParser(description="Accuracy by time control, clock and month.")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--speed", default=None, help="limit the clock table, e.g. blitz")
    parser.add_argument("--months", type=int, default=12, help="most recent months to list")
    parser.add_argument(
        "--include-ai", action="store_true", help="count games against the computer"
    )
    args = parser.parse_args()
    if args.months < 1:
        parser.error("--months must be at least 1")

    with connect(DATABASE_URL) as conn:
        run_id = get_or_create_run(conn, engine_name(STOCKFISH_PATH), args.depth)
        speeds = speed_results(conn, args.include_ai)
        speed_stats = speed_accuracy(conn, run_id, args.include_ai)
        clock = clock_accuracy(conn, run_id, args.speed, args.include_ai)
        months = monthly_results(conn, args.include_ai)
        month_stats = monthly_accuracy(conn, run_id, args.include_ai)

    print("By time control (score = wins + half of draws; lost on time = share of your losses)\n")
    print(format_speeds(speeds, speed_stats))
    scope = f"{args.speed} games" if args.speed else "all games"
    print(f"\nBy time left on your clock after the move ({scope})\n")
    print(format_clock(clock))
    print(f"\nBy month (UTC), last {args.months} with games; months with no games are not listed\n")
    print(format_months(months, month_stats, args.months))


if __name__ == "__main__":
    main()
