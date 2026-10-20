from analysis_helpers import FakeEngine, add_game

import batch
from batch import analyze_games
from db import get_or_create_run


def run_for(db):
    return get_or_create_run(db, "Fake 1", 5)


def test_batch_stores_evaluations_and_losses_for_a_game(db):
    game_id = add_game(db)

    result = analyze_games(db, FakeEngine(), run_for(db), 5)

    assert (result.analyzed, result.positions, result.failures, result.aborted) == (1, 4, [], False)
    evals = db.execute(
        "SELECT ply, stockfish_cp FROM evaluations WHERE game_id = %s ORDER BY ply", (game_id,)
    ).fetchall()
    assert evals == [(0, 25), (1, -25), (2, 25), (3, -25)]
    losses = db.execute(
        "SELECT ply, loss_cp, label FROM move_losses WHERE game_id = %s ORDER BY ply", (game_id,)
    ).fetchall()
    assert [(ply, loss) for ply, loss, _ in losses] == [(1, 50), (2, 50), (3, 50), (4, 0)]
    assert losses[-1][2] == "ok"  # the checkmating move has a row, with zero loss


def test_a_second_run_has_nothing_to_do(db):
    add_game(db)
    run_id = run_for(db)
    first = analyze_games(db, FakeEngine(), run_id, 5)
    fake = FakeEngine()

    second = analyze_games(db, fake, run_id, 5)

    assert (first.analyzed, second.analyzed) == (1, 0)
    assert fake.calls == []


def test_a_limited_run_can_be_continued(db):
    add_game(db, "aaaa0001", "e4 e5", "2024-02-01")
    add_game(db, "bbbb0001", "e4 e5", "2024-01-01")
    run_id = run_for(db)

    first = analyze_games(db, FakeEngine(), run_id, 5, limit=1)
    second = analyze_games(db, FakeEngine(), run_id, 5)
    third = analyze_games(db, FakeEngine(), run_id, 5)

    assert (first.analyzed, second.analyzed, third.analyzed) == (1, 1, 0)


def test_a_bad_game_is_reported_and_the_run_continues(db):
    add_game(db, "bad00001", "zz9", "2024-03-01", with_moves=False)
    good_id = add_game(db, "good0001", "e4 e5", "2024-01-01")

    result = analyze_games(db, FakeEngine(), run_for(db), 5)

    assert result.analyzed == 1
    assert [lichess_id for lichess_id, _ in result.failures] == ["bad00001"]
    assert "zz9" in result.failures[0][1]
    stored = db.execute("SELECT count(*) FROM evaluations WHERE game_id = %s", (good_id,))
    assert stored.fetchone()[0] == 3


def test_too_many_failures_abort_the_run(db, monkeypatch):
    monkeypatch.setattr(batch, "MAX_FAILURES", 1)
    for number in range(3):
        add_game(db, f"bad0000{number}", "zz9", f"2024-0{number + 1}-01", with_moves=False)

    result = analyze_games(db, FakeEngine(), run_for(db), 5)

    assert result.aborted is True
    assert result.analyzed == 0
    assert len(result.failures) == 2


def test_game_key_and_depth_reach_the_engine(db):
    add_game(db)
    fake = FakeEngine()

    analyze_games(db, fake, run_for(db), 5)

    assert {call["game"] for call in fake.calls} == {"abcd1234"}
    assert {call["depth"] for call in fake.calls} == {5}


def test_progress_callback_reports_each_game(db):
    add_game(db, "aaaa0001", "e4 e5", "2024-02-01")
    add_game(db, "bbbb0001", "e4 e5", "2024-01-01")
    seen = []

    analyze_games(
        db,
        FakeEngine(),
        run_for(db),
        5,
        on_game=lambda i, total, lichess_id, positions, seconds: seen.append(
            (i, total, lichess_id, positions)
        ),
    )

    assert seen == [(1, 2, "aaaa0001", 3), (2, 2, "bbbb0001", 3)]
