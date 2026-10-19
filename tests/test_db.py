from datetime import UTC, datetime

import pytest
from db_helpers import count

from db import insert_game, store_game
from models import parse_game

USER = "blazene"
FEN_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


@pytest.fixture
def game(raw_game):
    return parse_game(raw_game, USER)


def test_store_game_saves_the_game_and_all_its_moves(db, game):
    assert store_game(db, game) is True

    assert count(db, "games") == 1
    assert count(db, "moves") == 63


def test_game_columns_are_stored_correctly(db, game):
    store_game(db, game)

    row = db.execute(
        "SELECT lichess_id, color, result, status, rating, rating_diff, opponent_name, "
        "opening_name, played_at, clock_initial, moves_san FROM games"
    ).fetchone()

    assert row == (
        "4MhVOLfl",
        "black",
        "loss",
        "outoftime",
        1611,
        -14,
        "a_jakov95",
        "Sicilian Defense: Staunton-Cochrane Variation",
        datetime(2026, 10, 17, 13, 49, 4, 436000, tzinfo=UTC),
        180,
        game.moves,
    )


def test_move_rows_have_fen_and_clock(db, game):
    store_game(db, game)

    row = db.execute("SELECT san, uci, fen_after, clock_cs FROM moves WHERE ply = 1").fetchone()

    assert row == ("e4", "e2e4", FEN_AFTER_E4, 18003)


def test_storing_the_same_game_twice_changes_nothing(db, game):
    assert store_game(db, game) is True
    assert store_game(db, game) is False

    assert count(db, "games") == 1
    assert count(db, "moves") == 63


def test_insert_game_returns_none_for_a_duplicate(db, game):
    assert isinstance(insert_game(db, game), int)
    assert insert_game(db, game) is None


def test_stored_moves_rebuild_the_games_move_string(db, game):
    store_game(db, game)

    rebuilt = db.execute("SELECT string_agg(san, ' ' ORDER BY ply) FROM moves").fetchone()[0]
    original = db.execute("SELECT moves_san FROM games").fetchone()[0]

    assert rebuilt == original


def test_failed_replay_rolls_back_the_game(db, raw_game):
    raw_game["moves"] = "e4 e4"
    bad_game = parse_game(raw_game, USER)

    with pytest.raises(ValueError, match="4MhVOLfl"):
        store_game(db, bad_game)

    assert count(db, "games") == 0
    assert count(db, "moves") == 0


def test_lichess_analysis_is_stored_as_json(db, raw_game):
    raw_game["analysis"] = [{"eval": 20}]

    store_game(db, parse_game(raw_game, USER))

    stored = db.execute("SELECT lichess_analysis FROM games").fetchone()[0]
    assert stored == [{"eval": 20}]


def test_missing_lichess_analysis_is_null(db, game):
    store_game(db, game)

    assert db.execute("SELECT lichess_analysis FROM games").fetchone()[0] is None


def test_game_without_clock_data_stores_null_clocks(db, raw_game):
    del raw_game["clocks"]

    store_game(db, parse_game(raw_game, USER))

    nulls = db.execute("SELECT count(*) FROM moves WHERE clock_cs IS NULL").fetchone()[0]
    assert nulls == 63
