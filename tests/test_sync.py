import copy
from datetime import UTC, datetime

import psycopg
import pytest
from db_helpers import count, insert, insert_game

from db import full_sync_done, mark_full_sync, newest_played_at, table_counts
from sync import MAX_FAILURES, OVERLAP, TooManyFailures, choose_since, sync_games

USER = "blazene"


def make_raw(raw_game: dict, game_id: str, **changes) -> dict:
    """A copy of the real fixture game with a different id and optional edits."""
    raw = copy.deepcopy(raw_game)
    raw["id"] = game_id
    raw.update(changes)
    return raw


# ---------- choosing where to start ----------


def test_no_marker_means_full_history(db):
    insert_game(db)

    assert choose_since(db, USER) is None


def test_marker_without_games_means_full_history(db):
    mark_full_sync(db, USER)

    assert choose_since(db, USER) is None


def test_marker_and_games_gives_newest_minus_overlap(db):
    insert_game(db, played_at="2026-10-17T13:49:04Z")
    mark_full_sync(db, USER)

    assert choose_since(db, USER) == datetime(2026, 10, 17, 13, 49, 4, tzinfo=UTC) - OVERLAP


def test_full_flag_ignores_the_marker(db):
    insert_game(db)
    mark_full_sync(db, USER)

    assert choose_since(db, USER, full=True) is None


# ---------- sync state and counts ----------


def test_full_sync_done_is_false_until_marked(db):
    assert full_sync_done(db, USER) is False

    mark_full_sync(db, USER)

    assert full_sync_done(db, USER) is True


def test_username_comparison_ignores_case(db):
    mark_full_sync(db, "Blazene")

    assert full_sync_done(db, "BLAZENE") is True


def test_marking_twice_keeps_one_row(db):
    mark_full_sync(db, USER)
    mark_full_sync(db, USER)

    assert count(db, "sync_state") == 1


def test_newest_played_at(db):
    assert newest_played_at(db) is None

    insert_game(db, lichess_id="AAAAAAAA", played_at="2026-01-01T00:00:00Z")
    insert_game(db, lichess_id="BBBBBBBB", played_at="2026-03-01T00:00:00Z")

    assert newest_played_at(db) == datetime(2026, 3, 1, tzinfo=UTC)


def test_table_counts(db, raw_game):
    sync_games(db, [raw_game], USER)

    assert table_counts(db) == (1, 63)


def test_sync_state_username_must_be_lowercase(db):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        insert(db, "sync_state", lichess_username="Blazene")

    assert exc.value.diag.constraint_name == "sync_state_username_lowercase"


def test_sync_state_username_must_not_be_empty(db):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        insert(db, "sync_state", lichess_username="")

    assert exc.value.diag.constraint_name == "sync_state_username_not_empty"


def test_sync_state_has_one_row_per_username(db):
    insert(db, "sync_state", lichess_username="blazene")

    with pytest.raises(psycopg.errors.UniqueViolation) as exc:
        insert(db, "sync_state", lichess_username="blazene")

    assert exc.value.diag.constraint_name == "sync_state_pkey"


# ---------- syncing games ----------


def test_new_games_are_stored_with_their_moves(db, raw_game):
    games = [make_raw(raw_game, "AAAAAAAA"), make_raw(raw_game, "BBBBBBBB")]

    report = sync_games(db, games, USER)

    assert (report.seen, report.inserted, report.already_stored) == (2, 2, 0)
    assert table_counts(db) == (2, 126)


def test_running_again_stores_nothing_new(db, raw_game):
    games = [make_raw(raw_game, "AAAAAAAA"), make_raw(raw_game, "BBBBBBBB")]
    sync_games(db, games, USER)

    report = sync_games(db, games, USER)

    assert (report.inserted, report.already_stored) == (0, 2)
    assert table_counts(db) == (2, 126)


def test_unfinished_and_variant_games_are_counted_but_not_stored(db, raw_game):
    aborted = make_raw(raw_game, "AAAAAAAA", status="aborted")
    chess960 = make_raw(raw_game, "BBBBBBBB", variant="chess960")

    report = sync_games(db, [aborted, chess960], USER)

    assert report.skipped == {"standard/aborted": 1, "chess960/outoftime": 1}
    assert report.failures == []
    assert table_counts(db) == (0, 0)


def test_unplayable_game_is_reported_and_the_run_continues(db, raw_game):
    bad = make_raw(raw_game, "BADMOVES", moves="e4 e4")
    good = make_raw(raw_game, "GOODGAME")

    report = sync_games(db, [bad, good], USER)

    assert report.inserted == 1
    assert [game_id for game_id, _ in report.failures] == ["BADMOVES"]
    assert "ply 2" in report.failures[0][1]
    assert table_counts(db) == (1, 63)


def test_foreign_game_is_reported_not_fatal(db, raw_game):
    report = sync_games(db, [make_raw(raw_game, "AAAAAAAA")], "someone_else")

    assert [game_id for game_id, _ in report.failures] == ["AAAAAAAA"]
    assert table_counts(db) == (0, 0)


def test_missing_field_is_reported_not_fatal(db, raw_game):
    broken = make_raw(raw_game, "AAAAAAAA")
    del broken["status"]

    report = sync_games(db, [broken], USER)

    assert report.failures[0][0] == "AAAAAAAA"
    assert "KeyError" in report.failures[0][1]


def test_database_rejection_is_reported_and_the_connection_survives(db, raw_game):
    bad = make_raw(raw_game, "SPEEDBAD", speed="hyperbullet")
    good = make_raw(raw_game, "GOODGAME")

    report = sync_games(db, [bad, good], USER)

    assert "CheckViolation" in report.failures[0][1]
    assert report.inserted == 1
    assert table_counts(db) == (1, 63)


def test_too_many_failures_aborts_the_run(db, raw_game):
    bad_games = (make_raw(raw_game, f"BAD{i:05d}", moves="e4 e4") for i in range(MAX_FAILURES + 5))

    with pytest.raises(TooManyFailures):
        sync_games(db, bad_games, USER)

    assert table_counts(db) == (0, 0)
