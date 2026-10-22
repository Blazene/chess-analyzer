"""Read-only analytics over time: by time control, by time left on the clock, by month.

Only SELECT statements live here. Which games and moves count is decided by filters.py.
Integers come out of SQL; percentages and averages are computed in Python.
"""

from dataclasses import dataclass

import psycopg

from filters import NO_FILTERS, Filters, render

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
WHERE {where}
GROUP BY g.speed
ORDER BY games DESC, g.speed
"""

SPEED_ACCURACY_SQL = """
{my_moves}
SELECT speed, count(*), sum(loss_cp), count(*) FILTER (WHERE label = 'blunder')
FROM my_moves
GROUP BY speed
ORDER BY 2 DESC, 1
"""

CLOCK_SQL = (
    "{my_moves}\nSELECT "
    + _bucket_case()
    + ", count(*), sum(loss_cp), count(*) FILTER (WHERE label = 'blunder')\n"
    + "FROM my_moves\nWHERE clock_cs IS NOT NULL\nGROUP BY 1\n"
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
WHERE {where}
GROUP BY 1
ORDER BY 1
"""

MONTH_ACCURACY_SQL = """
{my_moves}
SELECT to_char(played_at AT TIME ZONE 'UTC', 'YYYY-MM'),
       count(*), sum(loss_cp), count(*) FILTER (WHERE label = 'blunder')
FROM my_moves
GROUP BY 1
ORDER BY 1
"""


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


def speed_results(conn: psycopg.Connection, filters: Filters = NO_FILTERS) -> list[SpeedRecord]:
    """Results per time control, most played first."""
    sql, params = render(SPEED_RESULTS_SQL, filters)
    return [SpeedRecord(*row) for row in conn.execute(sql, params).fetchall()]


def speed_accuracy(
    conn: psycopg.Connection, run_id: int, filters: Filters = NO_FILTERS
) -> list[GroupStats]:
    """Your average loss and blunder rate per time control."""
    sql, params = render(SPEED_ACCURACY_SQL, filters, run_id=run_id)
    return [GroupStats(*row) for row in conn.execute(sql, params).fetchall()]


def clock_accuracy(
    conn: psycopg.Connection, run_id: int, filters: Filters = NO_FILTERS
) -> list[GroupStats]:
    """Your average loss and blunder rate by time left after the move, shortest first.

    Moves with no recorded clock are left out, and so are empty buckets.
    """
    sql, params = render(CLOCK_SQL, filters, run_id=run_id)
    by_bucket = {row[0]: GroupStats(*row) for row in conn.execute(sql, params).fetchall()}
    return [by_bucket[name] for name, _ in CLOCK_BUCKETS if name in by_bucket]


def monthly_results(conn: psycopg.Connection, filters: Filters = NO_FILTERS) -> list[MonthResult]:
    """Results per calendar month (UTC), oldest first. Months with no games are not listed."""
    sql, params = render(MONTH_RESULTS_SQL, filters)
    return [MonthResult(*row) for row in conn.execute(sql, params).fetchall()]


def monthly_accuracy(
    conn: psycopg.Connection, run_id: int, filters: Filters = NO_FILTERS
) -> list[GroupStats]:
    """Your average loss and blunder rate per month (UTC), analyzed games only."""
    sql, params = render(MONTH_ACCURACY_SQL, filters, run_id=run_id)
    return [GroupStats(*row) for row in conn.execute(sql, params).fetchall()]
