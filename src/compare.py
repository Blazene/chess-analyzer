"""Check that stored results are consistent, then compare them with Lichess's own analysis.

Lichess analysis (games.lichess_analysis) is read as a list with one entry per move, from
White's point of view: {"eval": cp} or {"mate": n}, plus an optional {"judgment": {"name":
"Blunder"}}. That format is recalled, not verified: a list whose length does not match the
game's move count is counted as a shape mismatch and skipped, never silently used.
"""

import argparse
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import psycopg

from db import comparison_data, connect, get_or_create_run, integrity_rows
from engine import DEFAULT_DEPTH, Evaluation
from loss import CP_CAP, clamp_cp, to_cp

LABELS = ("ok", "inaccuracy", "mistake", "blunder")
SIGN_MIN_CP = 50  # below this either engine is basically saying "equal"


def lichess_cp(entry: Mapping) -> int | None:
    """Lichess's score for one move as capped centipawns, or None if it has no usable score."""
    mate = entry.get("mate")
    if mate is not None:
        if mate == 0:
            return None
        return CP_CAP if mate > 0 else -CP_CAP
    cp = entry.get("eval")
    return None if cp is None else clamp_cp(cp)


def lichess_label(entry: Mapping) -> str:
    name = ((entry.get("judgment") or {}).get("name") or "").lower()
    return name if name in LABELS else "ok"


@dataclass
class Comparison:
    games: int = 0
    not_analyzed: int = 0
    skipped_shape: int = 0
    positions: int = 0
    abs_diff_total: int = 0
    sign_checked: int = 0
    sign_agree: int = 0
    labels: Counter[tuple[str, str]] = field(default_factory=Counter)  # (ours, theirs)

    @property
    def mean_abs_diff(self) -> float | None:
        return self.abs_diff_total / self.positions if self.positions else None

    @property
    def sign_rate(self) -> float | None:
        return self.sign_agree / self.sign_checked if self.sign_checked else None


def compare_game(
    comparison: Comparison,
    cps: Mapping[int, int],
    labels: Mapping[int, str],
    lichess: Sequence[Mapping],
) -> None:
    """Add one game to the comparison. `cps` and `labels` are ours, keyed by ply."""
    if len(lichess) != len(labels):
        comparison.skipped_shape += 1
        return
    comparison.games += 1
    for index, entry in enumerate(lichess):
        ply = index + 1
        theirs, ours = lichess_cp(entry), cps.get(ply)
        if theirs is not None and ours is not None:
            comparison.positions += 1
            comparison.abs_diff_total += abs(ours - theirs)
            if abs(ours) >= SIGN_MIN_CP and abs(theirs) >= SIGN_MIN_CP:
                comparison.sign_checked += 1
                comparison.sign_agree += (ours > 0) == (theirs > 0)
        comparison.labels[(labels[ply], lichess_label(entry))] += 1


def run_comparison(conn: psycopg.Connection, run_id: int) -> Comparison:
    comparison = Comparison()
    for row in comparison_data(conn, run_id):
        if not row["labels"]:
            comparison.not_analyzed += 1
            continue
        cps = {ply: to_cp(Evaluation(cp, mate, None)) for ply, (cp, mate) in row["cps"].items()}
        compare_game(comparison, cps, row["labels"], row["analysis"])
    return comparison


def check_integrity(rows: Sequence[tuple]) -> tuple[int, list[str]]:
    """(games not analyzed yet, problems) from (lichess_id, moves, evaluations, losses) rows."""
    unanalyzed = 0
    problems = []
    for lichess_id, moves, evals, losses in rows:
        if evals == 0 and losses == 0:
            unanalyzed += 1
            continue
        if losses != moves:
            problems.append(f"{lichess_id}: {moves} moves but {losses} loss rows")
        if evals not in (moves, moves + 1):
            problems.append(f"{lichess_id}: {moves} moves but {evals} evaluations")
    return unanalyzed, problems


def format_report(c: Comparison) -> str:
    lines = [
        f"Games compared: {c.games} (not analyzed yet: {c.not_analyzed}, "
        f"shape mismatch: {c.skipped_shape})",
        f"Positions compared: {c.positions:,}",
    ]
    if c.mean_abs_diff is not None:
        lines.append(f"Mean absolute difference: {c.mean_abs_diff:.0f} cp (both capped at 1000)")
    if c.sign_rate is not None:
        lines.append(
            f"Same side ahead when both show {SIGN_MIN_CP}+ cp: "
            f"{c.sign_rate:.1%} of {c.sign_checked:,}"
        )
    lines.append("\nMove labels: ours (rows) against Lichess (columns)")
    lines.append(" " * 12 + "".join(f"{label:>12}" for label in LABELS))
    for ours in LABELS:
        counts = "".join(f"{c.labels[(ours, theirs)]:>12,}" for theirs in LABELS)
        lines.append(f"{ours:<12}{counts}")
    return "\n".join(lines)


def main() -> None:
    from batch import engine_name
    from config import DATABASE_URL, STOCKFISH_PATH

    parser = argparse.ArgumentParser(description="Integrity check and comparison with Lichess.")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    args = parser.parse_args()

    with connect(DATABASE_URL) as conn:
        run_id = get_or_create_run(conn, engine_name(STOCKFISH_PATH), args.depth)
        rows = integrity_rows(conn, run_id)
        unanalyzed, problems = check_integrity(rows)
        if problems:
            print(f"INTEGRITY PROBLEMS ({len(problems)}):", file=sys.stderr)
            for problem in problems[:20]:
                print(f"  {problem}", file=sys.stderr)
            sys.exit(1)
        print(f"Integrity OK: {len(rows) - unanalyzed} games checked, {unanalyzed} not analyzed")
        print()
        print(format_report(run_comparison(conn, run_id)))


if __name__ == "__main__":
    main()
