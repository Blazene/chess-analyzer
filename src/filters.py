"""One definition of which games and moves count, shared by every analytics query.

Filters are applied in SQL, before anything is aggregated: an average loss or a win rate
cannot be re-filtered afterwards. A query is a template with two placeholders, and render()
fills them in:
  {where}     the game filters, as the body of a WHERE clause (games must be aliased g)
  {my_moves}  a WITH clause called my_moves, holding YOUR moves only, with the filters applied
"""

from dataclasses import dataclass
from datetime import date

COLORS = ("white", "black")

# A move is yours when the ply parity matches your colour (odd plies are White's).
# Pieces are counted from the FEN's board part by keeping only Q, R, B and N of either case.
MY_MOVES_CTE = """
WITH my_moves AS (
    SELECT g.speed, g.played_at, m.ply, m.clock_cs, l.loss_cp, l.label,
           length(regexp_replace(split_part(m.fen_after, ' ', 1), '[^QRBNqrbn]', '', 'g'))
               AS pieces
    FROM games g
    JOIN moves m ON m.game_id = g.id
    JOIN move_losses l
      ON l.game_id = m.game_id AND l.ply = m.ply AND l.analysis_run_id = %(run_id)s
    WHERE (mod(m.ply, 2) = 1) = (g.color = 'white')
      AND {where}
)
"""


@dataclass(frozen=True)
class Filters:
    include_ai: bool = False  # games against the computer
    color: str | None = None  # "white", "black", or None for both
    speeds: tuple[str, ...] | None = None  # None = every time control
    start: date | None = None  # first UTC day included
    end: date | None = None  # last UTC day included

    def __post_init__(self) -> None:
        if self.color is not None and self.color not in COLORS:
            raise ValueError(f"color must be 'white', 'black' or None, not {self.color!r}")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")

    def where(self) -> tuple[str, dict]:
        """The WHERE-clause body and its parameters. Only the filters that are set appear."""
        clauses = ["(%(include_ai)s OR NOT g.opponent_is_ai)"]
        params: dict = {"include_ai": self.include_ai}
        if self.color is not None:
            clauses.append("g.color = %(color)s")
            params["color"] = self.color
        if self.speeds is not None:
            if self.speeds:
                clauses.append("g.speed = ANY(%(speeds)s)")
                params["speeds"] = list(self.speeds)
            else:
                clauses.append("FALSE")  # nothing selected means nothing matches
        if self.start is not None:
            clauses.append("(g.played_at AT TIME ZONE 'UTC')::date >= %(start)s")
            params["start"] = self.start
        if self.end is not None:
            clauses.append("(g.played_at AT TIME ZONE 'UTC')::date <= %(end)s")
            params["end"] = self.end
        return " AND ".join(clauses), params


NO_FILTERS = Filters()


def render(template: str, filters: Filters, **params) -> tuple[str, dict]:
    """Fill {my_moves} and {where} in a query template. Returns (sql, parameters).

    Templates are module constants, never user input, so the replacement is safe.
    """
    where, filter_params = filters.where()
    sql = template.replace("{my_moves}", MY_MOVES_CTE).replace("{where}", where)
    return sql, {**filter_params, **params}
