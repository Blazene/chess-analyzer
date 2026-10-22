from datetime import date

import pytest
from time_helpers import add_timed_game, mv

import insights
from db import get_or_create_run
from explain import (
    CANDIDATES,
    QUERIES,
    Measurement,
    PlanSummary,
    measure,
    measure_all,
    summarize_plan,
    table_sizes,
    time_dashboard,
    trial,
    uses_index,
    worthwhile,
)
from filters import NO_FILTERS, Filters


def explain_json(plan, execution=12.5, planning=0.4, **extra):
    return [{"Plan": plan, "Planning Time": planning, "Execution Time": execution, **extra}]


def scan(kind, relation=None, index=None):
    node = {"Node Type": kind}
    if relation:
        node["Relation Name"] = relation
    if index:
        node["Index Name"] = index
    return node


def m(name, ms, scans=()):
    return Measurement(name, ms, PlanSummary(ms, 0.1, tuple(scans), False))


# ---------- reading a plan ----------


def test_summary_reads_times_and_the_scan():
    summary = summarize_plan(explain_json(scan("Seq Scan", "games")))

    assert summary == PlanSummary(12.5, 0.4, ("Seq Scan on games",), False)


def test_nested_scans_are_found_in_plan_order():
    tree = {
        "Node Type": "Hash Join",
        "Plans": [
            scan("Seq Scan", "moves"),
            {"Node Type": "Hash", "Plans": [scan("Seq Scan", "games")]},
        ],
    }

    summary = summarize_plan(explain_json(tree))

    assert summary.scans == ("Seq Scan on moves", "Seq Scan on games")


def test_a_repeated_scan_is_listed_once():
    tree = {"Node Type": "Append", "Plans": [scan("Seq Scan", "games"), scan("Seq Scan", "games")]}

    assert summarize_plan(explain_json(tree)).scans == ("Seq Scan on games",)


def test_an_index_scan_names_its_index():
    summary = summarize_plan(explain_json(scan("Index Scan", "games", "games_played_at_idx")))

    assert summary.scans == ("Index Scan on games using games_played_at_idx",)


def test_jit_is_flagged_when_the_plan_reports_it():
    summary = summarize_plan(explain_json(scan("Seq Scan", "games"), JIT={"Functions": 3}))

    assert summary.jit is True


def test_uses_index_looks_for_the_name_in_the_scans():
    summary = PlanSummary(1.0, 0.1, ("Index Scan on moves using cand_x",), False)

    assert uses_index(summary, "cand_x")
    assert not uses_index(summary, "cand_y")


# ---------- the rule for keeping an index ----------


def test_an_index_that_is_used_and_saves_enough_passes():
    baseline = [m("phase accuracy", 100.0, ["Seq Scan on moves"])]
    trialled = [m("phase accuracy", 40.0, ["Index Only Scan on moves using cand_x"])]

    assert worthwhile("cand_x", baseline, trialled) == ["phase accuracy"]


def test_an_index_the_planner_ignores_does_not_pass_even_if_timings_differ():
    baseline = [m("phase accuracy", 100.0)]
    trialled = [m("phase accuracy", 40.0, ["Seq Scan on moves"])]

    assert worthwhile("cand_x", baseline, trialled) == []


def test_a_saving_under_ten_milliseconds_does_not_pass():
    baseline = [m("openings", 5.0)]
    trialled = [m("openings", 2.0, ["Index Scan on games using cand_x"])]

    assert worthwhile("cand_x", baseline, trialled) == []


def test_a_saving_under_thirty_percent_does_not_pass():
    baseline = [m("phase accuracy", 100.0)]
    trialled = [m("phase accuracy", 80.0, ["Index Scan on moves using cand_x"])]

    assert worthwhile("cand_x", baseline, trialled) == []


# ---------- against the real database ----------


def run_for(db):
    return get_or_create_run(db, "Fake 1", 5)


def sample_params(run_id):
    return {
        "run_id": run_id,
        "min_games": insights.MIN_GAMES,
        "opening_plies": insights.OPENING_PLIES,
        "endgame_pieces": insights.ENDGAME_PIECES,
    }


def test_measure_reports_a_median_time_and_the_plan(db):
    result = measure(db, "openings", insights.OPENING_SQL, NO_FILTERS, {"min_games": 1}, runs=2)

    assert result.name == "openings"
    assert result.median_ms > 0
    assert any("games" in scan for scan in result.summary.scans)


def test_every_query_explains_with_every_filter_set(db):
    run_id = run_for(db)
    add_timed_game(db, run_id, moves=[mv(1, 500, 30)])
    everything = Filters(
        color="white", speeds=("blitz",), start=date(2024, 1, 1), end=date(2024, 12, 31)
    )

    results = measure_all(db, run_id, everything, runs=1)

    assert [r.name for r in results] == [name for name, _ in QUERIES]
    assert all(r.median_ms >= 0 for r in results)


@pytest.mark.parametrize("candidate", CANDIDATES, ids=lambda c: c.name)
def test_a_candidate_index_is_measured_and_then_rolled_back(db, candidate):
    run_id = run_for(db)
    add_timed_game(db, run_id, moves=[mv(1, 500, 30)])

    results, load_ms = trial(db, candidate, run_id, NO_FILTERS, runs=1)

    assert len(results) == len(QUERIES)
    assert load_ms > 0
    left = db.execute("SELECT count(*) FROM pg_indexes WHERE indexname = %s", (candidate.name,))
    assert left.fetchone()[0] == 0


def test_dashboard_timing_is_a_positive_number(db):
    add_timed_game(db)

    assert time_dashboard(db, NO_FILTERS, runs=2) > 0


def test_table_sizes_cover_the_main_tables(db):
    assert set(table_sizes(db)) == {"games", "moves", "move_losses", "evaluations"}
