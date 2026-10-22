"""Measure the dashboard's queries with EXPLAIN ANALYZE and test candidate indexes safely.

Candidate indexes are built inside a transaction that is always rolled back, so this script
never changes your database (apart from refreshing planner statistics with ANALYZE).
Run it while nothing else uses the database: no batch run, no open dashboard.
"""

import argparse
import json
import statistics
import time
from dataclasses import dataclass

import psycopg

import dashboard_data as data
import insights
import time_insights
from filters import NO_FILTERS, Filters, render

RUNS = 5
MIN_GAIN = 0.30  # an index must cut a query's time by at least this share...
MIN_SAVING_MS = 10.0  # ...and by at least this many milliseconds

QUERIES = (
    ("openings", insights.OPENING_SQL),
    ("phase accuracy", insights.PHASE_SQL),
    ("speed results", time_insights.SPEED_RESULTS_SQL),
    ("speed accuracy", time_insights.SPEED_ACCURACY_SQL),
    ("clock accuracy", time_insights.CLOCK_SQL),
    ("month results", time_insights.MONTH_RESULTS_SQL),
    ("month accuracy", time_insights.MONTH_ACCURACY_SQL),
)

TABLES = ("games", "moves", "move_losses", "evaluations")


@dataclass(frozen=True)
class Candidate:
    name: str
    sql: str


CANDIDATES = (
    Candidate(
        "cand_moves_covering",
        "CREATE INDEX cand_moves_covering ON moves (game_id, ply) INCLUDE (clock_cs, fen_after)",
    ),
    Candidate(
        "cand_losses_covering",
        "CREATE INDEX cand_losses_covering ON move_losses (analysis_run_id, game_id, ply) "
        "INCLUDE (loss_cp, label)",
    ),
    Candidate(
        "cand_games_filter",
        "CREATE INDEX cand_games_filter ON games (opponent_is_ai, speed, played_at)",
    ),
)


@dataclass(frozen=True)
class PlanSummary:
    execution_ms: float
    planning_ms: float
    scans: tuple[str, ...]  # each distinct scan, in plan order
    jit: bool


@dataclass(frozen=True)
class Measurement:
    name: str
    median_ms: float
    summary: PlanSummary


def _walk(node: dict):
    yield node
    for child in node.get("Plans", []):
        yield from _walk(child)


def summarize_plan(explain_json: list[dict]) -> PlanSummary:
    """Boil an EXPLAIN (FORMAT JSON) result down to its times and the scans it used."""
    top = explain_json[0]
    scans: list[str] = []
    for node in _walk(top["Plan"]):
        kind = node["Node Type"]
        if "Scan" not in kind:
            continue
        relation, index = node.get("Relation Name"), node.get("Index Name")
        if relation and index:
            label = f"{kind} on {relation} using {index}"
        else:
            label = f"{kind} on {relation or index or node.get('CTE Name', '?')}"
        if label not in scans:
            scans.append(label)
    return PlanSummary(top["Execution Time"], top["Planning Time"], tuple(scans), "JIT" in top)


def uses_index(summary: PlanSummary, index_name: str) -> bool:
    return any(index_name in scan for scan in summary.scans)


def explain(conn: psycopg.Connection, sql: str, params: dict) -> PlanSummary:
    plan = conn.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + sql, params).fetchone()[0]
    if isinstance(plan, str):
        plan = json.loads(plan)
    return summarize_plan(plan)


def measure(
    conn: psycopg.Connection,
    name: str,
    template: str,
    filters: Filters,
    params: dict,
    runs: int = RUNS,
) -> Measurement:
    """Run EXPLAIN ANALYZE several times. Keeps the median time and the last plan."""
    sql, bound = render(template, filters, **params)
    summaries = [explain(conn, sql, bound) for _ in range(runs)]
    median = statistics.median(s.execution_ms for s in summaries)
    return Measurement(name, median, summaries[-1])


def measure_all(
    conn: psycopg.Connection, run_id: int, filters: Filters, runs: int = RUNS
) -> list[Measurement]:
    params = {
        "run_id": run_id,
        "min_games": insights.MIN_GAMES,
        "opening_plies": insights.OPENING_PLIES,
        "endgame_pieces": insights.ENDGAME_PIECES,
    }
    return [measure(conn, name, sql, filters, params, runs) for name, sql in QUERIES]


def time_dashboard(conn: psycopg.Connection, filters: Filters, runs: int = RUNS) -> float:
    """Median wall-clock milliseconds to load everything the dashboard shows."""
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        data.load_dashboard(conn, filters)
        times.append((time.perf_counter() - started) * 1000)
    return statistics.median(times)


def trial(
    conn: psycopg.Connection, candidate: Candidate, run_id: int, filters: Filters, runs: int = RUNS
) -> tuple[list[Measurement], float]:
    """Build the candidate index, measure every query and the dashboard, then undo it."""
    with conn.transaction(force_rollback=True):
        conn.execute(candidate.sql)
        return measure_all(conn, run_id, filters, runs), time_dashboard(conn, filters, runs)


def worthwhile(name: str, baseline: list[Measurement], trialled: list[Measurement]) -> list[str]:
    """Queries where the index is used AND saves enough time to justify its cost."""
    wins = []
    for before, after in zip(baseline, trialled, strict=True):
        saving = before.median_ms - after.median_ms
        if (
            uses_index(after.summary, name)
            and saving >= MIN_SAVING_MS
            and saving >= MIN_GAIN * before.median_ms
        ):
            wins.append(before.name)
    return wins


def table_sizes(conn: psycopg.Connection) -> dict[str, str]:
    """Total size on disk (table plus its indexes) of the main tables."""
    rows = conn.execute(
        "SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) FROM pg_class "
        "WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace AND relname = ANY(%s)",
        (list(TABLES),),
    ).fetchall()
    return dict(rows)


def plan_text(summary: PlanSummary) -> str:
    return "; ".join(summary.scans) + (" (JIT)" if summary.jit else "")


def main() -> None:
    from config import DATABASE_URL
    from db import connect

    parser = argparse.ArgumentParser(description="EXPLAIN ANALYZE the dashboard queries.")
    parser.add_argument("--runs", type=int, default=RUNS)
    args = parser.parse_args()

    with connect(DATABASE_URL) as conn:
        run = data.latest_run(conn)
        if run is None:
            raise SystemExit("Nothing analyzed yet. Run src/batch.py first.")
        for table in TABLES:
            conn.execute(f"ANALYZE {table}")  # fresh statistics for the planner

        white = Filters(color="white")
        baseline = measure_all(conn, run.run_id, NO_FILTERS, args.runs)
        base_load = time_dashboard(conn, NO_FILTERS, args.runs)
        base_white = time_dashboard(conn, white, args.runs)

        print(f"Sizes with indexes: {table_sizes(conn)}")
        print(f"\nBaseline, median of {args.runs} (EXPLAIN ANALYZE ms)")
        for m in baseline:
            print(f"  {m.name:<15} {m.median_ms:>7.1f}  {plan_text(m.summary)}")
        print(f"\nDashboard load: {base_load:.0f} ms all games, {base_white:.0f} ms white only")

        for candidate in CANDIDATES:
            measured, load = trial(conn, candidate, run.run_id, NO_FILTERS, args.runs)
            used = [
                f"{b.name} {b.median_ms:.1f}->{a.median_ms:.1f}"
                for b, a in zip(baseline, measured, strict=True)
                if uses_index(a.summary, candidate.name)
            ]
            wins = worthwhile(candidate.name, baseline, measured)
            print(f"\n{candidate.name}")
            print(f"  used by: {', '.join(used) if used else 'no query'}")
            print(f"  dashboard load with it: {load:.0f} ms (was {base_load:.0f})")
            print(f"  passes the rule for: {', '.join(wins) if wins else 'nothing'}")


if __name__ == "__main__":
    main()
