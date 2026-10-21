import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from analysis_helpers import FakeEngine, add_game, find_stockfish

import batch
from batch import analyze_games_in_processes, analyze_games_parallel, compute_game
from db import get_or_create_run, recent_games


def run_for(db):
    return get_or_create_run(db, "Fake 1", 5)


def fake_work(fake=None):
    fake = fake or FakeEngine()
    return lambda game, depth: compute_game(fake, game, depth)


def parallel(db, work, workers=2, max_in_flight=4, limit=None, on_game=None):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return analyze_games_parallel(
            db,
            pool,
            work,
            run_for(db),
            5,
            limit=limit,
            max_in_flight=max_in_flight,
            on_game=on_game,
        )


def evaluation_count(db):
    return db.execute("SELECT count(*) FROM evaluations").fetchone()[0]


def add_games(db, count):
    for number in range(count):
        add_game(db, f"game000{number}", "e4 e5", f"2024-01-0{number + 1}")


def test_a_parallel_run_stores_every_game_once(db):
    add_games(db, 3)

    result = parallel(db, fake_work())

    assert (result.analyzed, result.positions, result.failures, result.aborted) == (3, 9, [], False)
    assert evaluation_count(db) == 9
    per_game = db.execute("SELECT count(*) FROM evaluations GROUP BY game_id").fetchall()
    assert per_game == [(3,), (3,), (3,)]


def test_a_parallel_run_can_be_resumed(db):
    add_game(db, "aaaa0001", "e4 e5", "2024-02-01")
    add_game(db, "bbbb0001", "e4 e5", "2024-01-01")

    first = parallel(db, fake_work(), limit=1)
    second = parallel(db, fake_work())
    third = parallel(db, fake_work())

    assert (first.analyzed, second.analyzed, third.analyzed) == (1, 1, 0)


def test_a_bad_game_is_reported_and_the_others_continue(db):
    add_game(db, "bad00001", "zz9", "2024-03-01", with_moves=False)
    add_game(db, "good0001", "e4 e5", "2024-01-01")

    result = parallel(db, fake_work())

    assert result.analyzed == 1
    assert [lichess_id for lichess_id, _ in result.failures] == ["bad00001"]
    assert evaluation_count(db) == 3


def test_too_many_failures_abort_a_parallel_run(db, monkeypatch):
    monkeypatch.setattr(batch, "MAX_FAILURES", 1)
    for number in range(3):
        add_game(db, f"bad0000{number}", "zz9", f"2024-0{number + 1}-01", with_moves=False)

    result = parallel(db, fake_work(), max_in_flight=1)

    assert result.aborted is True
    assert result.analyzed == 0
    assert len(result.failures) == 2


def test_the_window_limits_how_many_games_are_in_flight(db):
    add_games(db, 6)
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}
    fake = FakeEngine()

    def slow_work(game, depth):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.02)
        try:
            return compute_game(fake, game, depth)
        finally:
            with lock:
                state["now"] -= 1

    result = parallel(db, slow_work, workers=4, max_in_flight=2)

    assert result.analyzed == 6
    assert state["peak"] <= 2


def test_parallel_progress_counts_games_as_they_finish(db):
    add_games(db, 2)
    seen = []

    parallel(
        db,
        fake_work(),
        on_game=lambda done, total, lichess_id, positions, seconds: seen.append((done, total)),
    )

    assert seen == [(1, 2), (2, 2)]


def test_an_engine_failure_stops_the_run_and_saves_nothing(db):
    add_games(db, 2)

    def broken(game, depth):
        raise RuntimeError("engine died")

    with pytest.raises(RuntimeError, match="engine died"):
        parallel(db, broken)

    assert evaluation_count(db) == 0


@pytest.mark.skipif(find_stockfish() is None, reason="Stockfish is not installed")
def test_real_worker_processes_analyze_and_save_games(db):
    for number in range(3):
        add_game(db, f"game000{number}", "e4 e5 Nf3", f"2024-01-0{number + 1}")

    result = analyze_games_in_processes(db, find_stockfish(), run_for(db), depth=5, workers=2)

    assert (result.analyzed, result.positions, result.failures) == (3, 12, [])
    assert evaluation_count(db) == 12


def test_recent_games_are_newest_first_whether_or_not_they_are_analyzed(db):
    add_game(db, "old00001", "e4 e5", "2024-01-01")
    add_game(db, "mid00001", "e4 e5", "2024-02-01")
    newest = add_game(db, "new00001", "e4 e5", "2024-03-01")
    parallel(db, fake_work(), limit=1)  # analyzes only the newest

    games = recent_games(db, 2)

    assert [g["lichess_id"] for g in games] == ["new00001", "mid00001"]
    assert games[0]["id"] == newest
    assert games[0]["moves_san"] == "e4 e5"
