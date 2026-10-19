"""Database access. Together with migrate.py, the only place that runs SQL."""

import psycopg
from psycopg.types.json import Jsonb

from models import Game
from replay import MoveRow, replay_moves

INSERT_GAME_SQL = """
INSERT INTO games (
    lichess_id, played_at, speed, rated, color, result, status,
    rating, rating_diff, opponent_name, opponent_rating, opponent_is_ai,
    opening_eco, opening_name, opening_ply, clock_initial, clock_increment,
    moves_san, lichess_analysis
) VALUES (
    %(lichess_id)s, %(played_at)s, %(speed)s, %(rated)s, %(color)s, %(result)s, %(status)s,
    %(rating)s, %(rating_diff)s, %(opponent_name)s, %(opponent_rating)s, %(opponent_is_ai)s,
    %(opening_eco)s, %(opening_name)s, %(opening_ply)s, %(clock_initial)s, %(clock_increment)s,
    %(moves_san)s, %(lichess_analysis)s
)
ON CONFLICT (lichess_id) DO NOTHING
RETURNING id
"""

INSERT_MOVE_SQL = (
    "INSERT INTO moves (game_id, ply, san, uci, fen_after, clock_cs) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url)


def insert_game(conn: psycopg.Connection, game: Game) -> int | None:
    """Insert the game row. Returns its new id, or None if we already had this game."""
    params = {
        "lichess_id": game.lichess_id,
        "played_at": game.played_at,
        "speed": game.speed,
        "rated": game.rated,
        "color": game.color,
        "result": game.result,
        "status": game.status,
        "rating": game.rating,
        "rating_diff": game.rating_diff,
        "opponent_name": game.opponent_name,
        "opponent_rating": game.opponent_rating,
        "opponent_is_ai": game.opponent_is_ai,
        "opening_eco": game.opening_eco,
        "opening_name": game.opening_name,
        "opening_ply": game.opening_ply,
        "clock_initial": game.clock_initial,
        "clock_increment": game.clock_increment,
        "moves_san": game.moves,
        "lichess_analysis": (
            Jsonb(game.lichess_analysis) if game.lichess_analysis is not None else None
        ),
    }
    row = conn.execute(INSERT_GAME_SQL, params).fetchone()
    return row[0] if row else None


def insert_moves(conn: psycopg.Connection, game_id: int, rows: list[MoveRow]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            INSERT_MOVE_SQL,
            [(game_id, r.ply, r.san, r.uci, r.fen_after, r.clock_cs) for r in rows],
        )


def store_game(conn: psycopg.Connection, game: Game) -> bool:
    """Store a game and all its moves in ONE transaction.

    Returns True if the game was new, False if we already had it.
    If anything fails, nothing is saved, so there is never a game without its moves.
    """
    with conn.transaction():
        game_id = insert_game(conn, game)
        if game_id is None:
            return False
        try:
            rows = replay_moves(game.moves, game.clocks)
        except ValueError as exc:
            raise ValueError(f"Game {game.lichess_id}: {exc}") from exc
        insert_moves(conn, game_id, rows)
    return True
