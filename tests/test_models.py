from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from models import parse_game

USER = "Blazene"


def test_parses_real_game_as_black_loss(raw_game):
    game = parse_game(raw_game, USER)

    assert game is not None
    assert game.lichess_id == "4MhVOLfl"
    assert game.color == "black"
    assert game.result == "loss"
    assert game.status == "outoftime"
    assert game.speed == "blitz"
    assert game.rated is True
    assert game.rating == 1611
    assert game.rating_diff == -14
    assert game.opponent_name == "a_jakov95"
    assert game.opponent_rating == 1636
    assert game.opponent_is_ai is False
    assert game.played_at == datetime(2026, 10, 17, 13, 49, 4, 436000, tzinfo=UTC)


@pytest.mark.parametrize("username", ["blazene", "BLAZENE"])
def test_username_match_ignores_case(raw_game, username):
    game = parse_game(raw_game, username)

    assert game is not None
    assert game.color == "black"


def test_opening_and_clock_fields(raw_game):
    game = parse_game(raw_game, USER)

    assert game.opening_eco == "B20"
    assert game.opening_name == "Sicilian Defense: Staunton-Cochrane Variation"
    assert game.opening_ply == 3
    assert game.clock_initial == 180
    assert game.clock_increment == 2


def test_clocks_have_one_more_entry_than_moves(raw_game):
    # Documents a quirk we must handle on Day 6: the final clock has no matching move.
    game = parse_game(raw_game, USER)

    assert len(game.moves.split()) == 63
    assert len(game.clocks) == 64


def test_no_lichess_analysis_by_default(raw_game):
    assert parse_game(raw_game, USER).lichess_analysis is None


def test_keeps_lichess_analysis_when_present(raw_game):
    raw_game["analysis"] = [{"eval": 20}]

    assert parse_game(raw_game, USER).lichess_analysis == [{"eval": 20}]


def test_white_win(raw_game):
    players = raw_game["players"]
    players["white"], players["black"] = players["black"], players["white"]
    raw_game["winner"] = "white"

    game = parse_game(raw_game, USER)

    assert game.color == "white"
    assert game.result == "win"
    assert game.rating == 1611


def test_draw(raw_game):
    del raw_game["winner"]
    raw_game["status"] = "draw"

    assert parse_game(raw_game, USER).result == "draw"


@pytest.mark.parametrize("status", ["aborted", "noStart", "created", "started", "unknownFinish"])
def test_skips_unfinished_games(raw_game, status):
    raw_game["status"] = status

    assert parse_game(raw_game, USER) is None


@pytest.mark.parametrize("variant", ["chess960", "fromPosition", "crazyhouse"])
def test_skips_non_standard_variants(raw_game, variant):
    raw_game["variant"] = variant

    assert parse_game(raw_game, USER) is None


def test_ai_opponent(raw_game):
    raw_game["players"]["white"] = {"aiLevel": 3}

    game = parse_game(raw_game, USER)

    assert game.opponent_is_ai is True
    assert game.opponent_name == "Stockfish level 3"
    assert game.opponent_rating is None


def test_missing_opening(raw_game):
    del raw_game["opening"]

    game = parse_game(raw_game, USER)

    assert game.opening_eco is None
    assert game.opening_name is None
    assert game.opening_ply is None


def test_foreign_game_raises(raw_game):
    with pytest.raises(ValueError, match="4MhVOLfl"):
        parse_game(raw_game, "someone_else")


def test_game_is_immutable(raw_game):
    game = parse_game(raw_game, USER)

    with pytest.raises(FrozenInstanceError):
        game.result = "win"
