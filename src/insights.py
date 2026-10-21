"""Read-only analytics: what the stored games and analysis say about your play.

Only SELECT statements live here. db.py loads and writes data; this file only summarizes it.
Every query counts YOUR moves and games only, and skips games against the computer unless
asked. Integers come out of SQL and the percentages are computed in Python.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from db import connect, get_or_create_run
from engine import DEFAULT_DEPTH

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
WHERE %(include_ai)s OR NOT g.opponent_is_ai
GROUP BY g.color, 2
HAVING count(*) >= %(min_games)s
ORDER BY games DESC, g.color, opening
"""

# A move belongs to you when the ply parity matches your colour (odd plies are White's).
# The phase comes from the position AFTER the move. Pieces are counted from the FEN's
# board part by deleting everything except Q, R, B, N (either case).
PHASE_SQL = """
WITH my_moves AS (
    SELECT m.ply,
           l.loss_cp,
           l.label,
           length(regexp_replace(split_part(m.fen_after, ' ', 1), '[^QRBNqrbn]', '', 'g'))
               AS pieces
    FROM games g
    JOIN moves m ON m.game_id = g.id
    JOIN move_losses l
      ON l.game_id = m.game_id AND l.ply = m.ply AND l.analysis_run_id = %(run_id)s
    WHERE (mod(m.ply, 2) = 1) = (g.color = 'white')
      AND (%(include_ai)s OR NOT g.opponent_is_ai)
)
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
    conn: psycopg.Connection, min_games: int = MIN_GAMES, include_ai: bool = False
) -> list[OpeningRecord]:
    """Result per opening family and colour, most played first."""
    rows = conn.execute(OPENING_SQL, {"min_games": min_games, "include_ai": include_ai})
    return [OpeningRecord(*row) for row in rows.fetchall()]


def phase_accuracy(
    conn: psycopg.Connection,
    run_id: int,
    opening_plies: int = OPENING_PLIES,
    endgame_pieces: int = ENDGAME_PIECES,
    include_ai: bool = False,
) -> list[PhaseStats]:
    """Your average loss and blunder rate per phase. Phases with no moves are left out."""
    params = {
        "run_id": run_id,
        "opening_plies": opening_plies,
        "endgame_pieces": endgame_pieces,
        "include_ai": include_ai,
    }
    by_phase = {row[0]: PhaseStats(*row) for row in conn.execute(PHASE_SQL, params).fetchall()}
    return [by_phase[phase] for phase in PHASES if phase in by_phase]


def format_openings(records: Sequence[OpeningRecord], top: int) -> str:
    if not records:
        return "No opening has enough games yet."
    lines = [f"{'color':<6} {'opening':<38} {'games':>5} {'W':>4} {'D':>4} {'L':>4} {'score':>7}"]
    for r in records[:top]:
        lines.append(
            f"{r.color:<6} {r.opening[:38]:<38} {r.games:>5} {r.wins:>4} {r.draws:>4} "
            f"{r.losses:>4} {r.score:>7.1%}"
        )
    return "\n".join(lines)


def format_phases(stats: Sequence[PhaseStats]) -> str:
    if not stats:
        return "No analyzed moves yet."
    lines = [f"{'phase':<11} {'your moves':>10} {'avg loss':>10} {'blunders':>9}"]
    for s in stats:
        lines.append(f"{s.phase:<11} {s.moves:>10,} {s.avg_loss_cp:>8.0f}cp {s.blunder_rate:>9.1%}")
    lines.append(f"{'total':<11} {sum(s.moves for s in stats):>10,}")
    return "\n".join(lines)


def main() -> None:
    from batch import engine_name
    from config import DATABASE_URL, STOCKFISH_PATH

    parser = argparse.ArgumentParser(description="Opening results and accuracy by game phase.")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    parser.add_argument("--top", type=int, default=15, help="openings to show")
    parser.add_argument(
        "--include-ai", action="store_true", help="count games against the computer"
    )
    args = parser.parse_args()

    with connect(DATABASE_URL) as conn:
        run_id = get_or_create_run(conn, engine_name(STOCKFISH_PATH), args.depth)
        openings = opening_win_rates(conn, args.min_games, args.include_ai)
        phases = phase_accuracy(conn, run_id, include_ai=args.include_ai)

    print(f"Openings with at least {args.min_games} games (score = wins + half of draws)\n")
    print(format_openings(openings, args.top))
    print("\nYour moves by phase (loss is capped at 1000 cp per move)\n")
    print(format_phases(phases))


if __name__ == "__main__":
    main()
