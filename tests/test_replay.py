import chess
import pytest

from replay import replay_moves

FEN_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


@pytest.fixture
def rows(raw_game):
    return replay_moves(raw_game["moves"], tuple(raw_game["clocks"]))


def test_one_row_per_move_with_consecutive_plies(rows):
    assert len(rows) == 63
    assert [r.ply for r in rows] == list(range(1, 64))


def test_first_move_fields(rows):
    first = rows[0]

    assert first.san == "e4"
    assert first.uci == "e2e4"
    assert first.fen_after == FEN_AFTER_E4
    assert first.clock_cs == 18003


@pytest.mark.parametrize(("ply", "uci"), [(13, "e1g1"), (16, "e8g8")])
def test_castling_is_recorded_as_a_king_move(rows, ply, uci):
    row = rows[ply - 1]

    assert row.san == "O-O"
    assert row.uci == uci


def test_san_round_trip(raw_game, rows):
    assert " ".join(r.san for r in rows) == raw_game["moves"]


def test_final_position_has_black_in_check(rows):
    assert chess.Board(rows[-1].fen_after).is_check()


def test_extra_final_clock_is_ignored(rows):
    # 64 clock entries but 63 moves. The last entry (0) is Black's clock when flagged.
    assert rows[-1].clock_cs == 6770


def test_clock_belongs_to_the_player_who_moved():
    rows = replay_moves("e4 e5 Nf3", (100, 200, 300, 0))

    assert [r.clock_cs for r in rows] == [100, 200, 300]


def test_no_clocks_gives_none():
    rows = replay_moves("e4 e5")

    assert [r.clock_cs for r in rows] == [None, None]


def test_fewer_clocks_than_moves_gives_none_for_the_rest():
    rows = replay_moves("e4 e5 Nf3", (100, 200))

    assert [r.clock_cs for r in rows] == [100, 200, None]


def test_empty_moves_gives_no_rows():
    assert replay_moves("") == []


@pytest.mark.parametrize(("moves", "ply"), [("e4 e4", 2), ("Zz9", 1)])
def test_unplayable_move_error_names_the_ply(moves, ply):
    with pytest.raises(ValueError, match=f"ply {ply}"):
        replay_moves(moves)
