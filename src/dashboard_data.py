"""Everything the dashboard shows, loaded in one call and shaped into tables.

No Streamlit in this file, so plain pytest can test it. The dashboard needs only a database
connection: the analysis run to show is found from the data, so a deployed dashboard does
not need Stockfish at all.
"""

from dataclasses import dataclass

import pandas as pd
import psycopg

from insights import MIN_GAMES, OpeningRecord, PhaseStats, opening_win_rates, phase_accuracy
from time_insights import (
    GroupStats,
    MonthResult,
    SpeedRecord,
    clock_accuracy,
    monthly_accuracy,
    monthly_results,
    speed_accuracy,
    speed_results,
)

# The run with the most analyzed games. If two runs are tied, the newest one.
LATEST_RUN_SQL = """
SELECT r.id, r.engine_name, r.depth, count(DISTINCT l.game_id) AS games
FROM analysis_runs r
JOIN move_losses l ON l.analysis_run_id = r.id
GROUP BY r.id
ORDER BY games DESC, r.id DESC
LIMIT 1
"""

OPENING_COLUMNS = ["Color", "Opening", "Games", "Wins", "Draws", "Losses", "Score %"]
SPEED_COLUMNS = [
    "Speed",
    "Games",
    "Wins",
    "Draws",
    "Losses",
    "Score %",
    "Lost on time",
    "Lost on time % of losses",
    "Avg loss (cp)",
    "Blunder %",
]
CLOCK_COLUMNS = ["Time left", "Your moves", "Avg loss (cp)", "Blunder %"]
MONTH_COLUMNS = ["Month", "Games", "Score %", "Avg rating", "Avg loss (cp)", "Blunder %"]
PHASE_COLUMNS = ["Phase", "Your moves", "Avg loss (cp)", "Blunder %"]


@dataclass(frozen=True)
class RunInfo:
    run_id: int
    engine_name: str
    depth: int
    games_analyzed: int


@dataclass(frozen=True)
class Dashboard:
    """All the dashboard's data. The accuracy lists are empty when nothing is analyzed."""

    run: RunInfo | None
    openings: list[OpeningRecord]
    phases: list[PhaseStats]
    speeds: list[SpeedRecord]
    speed_stats: list[GroupStats]
    clock: list[GroupStats]
    months: list[MonthResult]
    month_stats: list[GroupStats]

    @property
    def games(self) -> int:
        return sum(s.games for s in self.speeds)

    @property
    def score(self) -> float | None:
        """Wins plus half of draws, as a share of all games. None without games."""
        if self.games == 0:
            return None
        wins = sum(s.wins for s in self.speeds)
        draws = sum(s.draws for s in self.speeds)
        return (wins + 0.5 * draws) / self.games

    @property
    def analyzed_moves(self) -> int:
        return sum(p.moves for p in self.phases)

    @property
    def avg_loss_cp(self) -> float | None:
        if self.analyzed_moves == 0:
            return None
        return sum(p.total_loss_cp for p in self.phases) / self.analyzed_moves

    @property
    def blunder_rate(self) -> float | None:
        if self.analyzed_moves == 0:
            return None
        return sum(p.blunders for p in self.phases) / self.analyzed_moves


def latest_run(conn: psycopg.Connection) -> RunInfo | None:
    """The analysis run to show, or None if nothing has been analyzed."""
    row = conn.execute(LATEST_RUN_SQL).fetchone()
    return None if row is None else RunInfo(*row)


def load_dashboard(
    conn: psycopg.Connection, include_ai: bool = False, min_games: int = MIN_GAMES
) -> Dashboard:
    """Run every query the dashboard needs. Results without a run still load."""
    run = latest_run(conn)
    analyzed = run is not None
    run_id = run.run_id if run else None
    return Dashboard(
        run=run,
        openings=opening_win_rates(conn, min_games, include_ai),
        phases=phase_accuracy(conn, run_id, include_ai=include_ai) if analyzed else [],
        speeds=speed_results(conn, include_ai),
        speed_stats=speed_accuracy(conn, run_id, include_ai) if analyzed else [],
        clock=clock_accuracy(conn, run_id, include_ai=include_ai) if analyzed else [],
        months=monthly_results(conn, include_ai),
        month_stats=monthly_accuracy(conn, run_id, include_ai) if analyzed else [],
    )


def _pct(share: float | None) -> float | None:
    return None if share is None else round(share * 100, 1)


def openings_frame(records: list[OpeningRecord]) -> pd.DataFrame:
    rows = [
        {
            "Color": r.color,
            "Opening": r.opening,
            "Games": r.games,
            "Wins": r.wins,
            "Draws": r.draws,
            "Losses": r.losses,
            "Score %": _pct(r.score),
        }
        for r in records
    ]
    return pd.DataFrame(rows, columns=OPENING_COLUMNS)


def speeds_frame(results: list[SpeedRecord], stats: list[GroupStats]) -> pd.DataFrame:
    by_speed = {s.key: s for s in stats}
    rows = []
    for r in results:
        s = by_speed.get(r.speed)
        rows.append(
            {
                "Speed": r.speed,
                "Games": r.games,
                "Wins": r.wins,
                "Draws": r.draws,
                "Losses": r.losses,
                "Score %": _pct(r.score),
                "Lost on time": r.lost_on_time,
                "Lost on time % of losses": _pct(r.flag_loss_rate),
                "Avg loss (cp)": None if s is None else round(s.avg_loss_cp),
                "Blunder %": None if s is None else _pct(s.blunder_rate),
            }
        )
    return pd.DataFrame(rows, columns=SPEED_COLUMNS)


def clock_frame(stats: list[GroupStats]) -> pd.DataFrame:
    rows = [
        {
            "Time left": s.key,
            "Your moves": s.moves,
            "Avg loss (cp)": round(s.avg_loss_cp),
            "Blunder %": _pct(s.blunder_rate),
        }
        for s in stats
    ]
    return pd.DataFrame(rows, columns=CLOCK_COLUMNS)


def months_frame(results: list[MonthResult], stats: list[GroupStats]) -> pd.DataFrame:
    by_month = {s.key: s for s in stats}
    rows = []
    for r in results:
        s = by_month.get(r.month)
        rows.append(
            {
                "Month": r.month,
                "Games": r.games,
                "Score %": _pct(r.score),
                "Avg rating": None if r.avg_rating is None else round(r.avg_rating),
                "Avg loss (cp)": None if s is None else round(s.avg_loss_cp),
                "Blunder %": None if s is None else _pct(s.blunder_rate),
            }
        )
    return pd.DataFrame(rows, columns=MONTH_COLUMNS)


def phases_frame(stats: list[PhaseStats]) -> pd.DataFrame:
    rows = [
        {
            "Phase": s.phase,
            "Your moves": s.moves,
            "Avg loss (cp)": round(s.avg_loss_cp),
            "Blunder %": _pct(s.blunder_rate),
        }
        for s in stats
    ]
    return pd.DataFrame(rows, columns=PHASE_COLUMNS)
