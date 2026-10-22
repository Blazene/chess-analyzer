"""Read-only analytics: opening results and accuracy by game phase.

Only SELECT statements live here. Which games and moves count is decided by filters.py.
Integers come out of SQL; percentages and averages are computed in Python.
"""

from dataclasses import dataclass

import psycopg

from filters import NO_FILTERS, Filters, render

MIN_GAMES = 10
OPENING_PLIES = 20  # the first 10 moves by each side
ENDGAME_PIECES = 6  # queens, rooks, bishops and knights of BOTH sides, pawns and kings excluded
PHASES = ("opening", "middlegame", "endgame")

OPENING_SQL = """
SELECT g.color,
       coalesce(nullif(trim(split_part(g.opening_name, ':', 1)), ''), 'Unknown') AS opening,
       count(*) AS games,
       count(*) FILTER (WHERE g.result = 'win') AS wins,
       count(*) FILTER (WHERE g.result = 'draw') AS draws,
       count(*) FILTER (WHERE g.result = 'loss') AS losses
FROM games g
WHERE {where}
GROUP BY g.color, 2
HAVING count(*) >= %(min_games)s
ORDER BY games DESC, g.color, opening
"""

# The phase comes from the position AFTER the move.
PHASE_SQL = """
{my_moves}
SELECT CASE WHEN ply <= %(opening_plies)s THEN 'opening'
            WHEN pieces <= %(endgame_pieces)s THEN 'endgame'
            ELSE 'middlegame' END AS phase,
       count(*) AS moves,
       sum(loss_cp) AS total_loss_cp,
       count(*) FILTER (WHERE label = 'blunder') AS blunders
FROM my_moves
GROUP BY 1
"""


@dataclass(frozen=True)
class OpeningRecord:
    color: str
    opening: str
    games: int
    wins: int
    draws: int
    losses: int

    @property
    def score(self) -> float:
        """Wins plus half of draws, as a share of games (0 to 1)."""
        return (self.wins + 0.5 * self.draws) / self.games


@dataclass(frozen=True)
class PhaseStats:
    phase: str
    moves: int
    total_loss_cp: int
    blunders: int

    @property
    def avg_loss_cp(self) -> float:
        return self.total_loss_cp / self.moves

    @property
    def blunder_rate(self) -> float:
        return self.blunders / self.moves


def opening_win_rates(
    conn: psycopg.Connection, filters: Filters = NO_FILTERS, min_games: int = MIN_GAMES
) -> list[OpeningRecord]:
    """Result per opening family and colour, most played first."""
    sql, params = render(OPENING_SQL, filters, min_games=min_games)
    return [OpeningRecord(*row) for row in conn.execute(sql, params).fetchall()]


def phase_accuracy(
    conn: psycopg.Connection,
    run_id: int,
    filters: Filters = NO_FILTERS,
    opening_plies: int = OPENING_PLIES,
    endgame_pieces: int = ENDGAME_PIECES,
) -> list[PhaseStats]:
    """Your average loss and blunder rate per phase. Phases with no moves are left out."""
    sql, params = render(
        PHASE_SQL,
        filters,
        run_id=run_id,
        opening_plies=opening_plies,
        endgame_pieces=endgame_pieces,
    )
    by_phase = {row[0]: PhaseStats(*row) for row in conn.execute(sql, params).fetchall()}
    return [by_phase[phase] for phase in PHASES if phase in by_phase]
