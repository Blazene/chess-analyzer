"""Helpers for the analysis tests: tiny games written with plain SQL, and a fake engine."""

import chess
from chess.engine import Cp, PovScore

INSERT_TEST_GAME = (
    "INSERT INTO games (lichess_id, played_at, speed, rated, color, result, status, "
    "opponent_name, moves_san) "
    "VALUES (%s, %s::timestamptz, 'blitz', true, 'white', 'loss', 'mate', 'opponent', %s) "
    "RETURNING id"
)

INSERT_TEST_MOVE = (
    "INSERT INTO moves (game_id, ply, san, uci, fen_after) VALUES (%s, %s, %s, %s, %s)"
)


def add_game(
    conn,
    lichess_id="abcd1234",
    moves_san="f3 e5 g4 Qh4#",
    played_at="2024-01-01",
    with_moves=True,
) -> int:
    """Insert a game (and its move rows) and return its id. with_moves=False skips the rows."""
    game_id = conn.execute(INSERT_TEST_GAME, (lichess_id, played_at, moves_san)).fetchone()[0]
    if with_moves:
        board = chess.Board()
        for ply, san in enumerate(moves_san.split(), start=1):
            move = board.push_san(san)
            conn.execute(INSERT_TEST_MOVE, (game_id, ply, san, move.uci(), board.fen()))
    return game_id


class FakeEngine:
    """Answers +25 for the side to move and records what it was asked."""

    def __init__(self):
        self.calls = []

    def analyse(self, board, limit, game=None):
        self.calls.append({"history": len(board.move_stack), "game": game, "depth": limit.depth})
        return {"score": PovScore(Cp(25), board.turn), "pv": [next(iter(board.legal_moves))]}
