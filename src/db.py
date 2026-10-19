"""Database access. Together with migrate.py, the only place that runs SQL."""

from datetime import datetime

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
    """Autocommit connection: each store_game call is then its own real transaction."""
    return psycopg.connect(database_url, autocommit=True)


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


def newest_played_at(conn: psycopg.Connection) -> datetime | None:
    """When the newest stored game started, or None if no games are stored."""
    return conn.execute("SELECT max(played_at) FROM games").fetchone()[0]


def full_sync_done(conn: psycopg.Connection, username: str) -> bool:
    """Has the complete history of this user been loaded at least once?"""
    row = conn.execute(
        "SELECT 1 FROM sync_state WHERE lichess_username = %s", (username.lower(),)
    ).fetchone()
    return row is not None


def mark_full_sync(conn: psycopg.Connection, username: str) -> None:
    """Record that the complete history of this user has been loaded."""
    conn.execute(
        "INSERT INTO sync_state (lichess_username) VALUES (%s) "
        "ON CONFLICT (lichess_username) DO UPDATE SET full_sync_completed_at = now()",
        (username.lower(),),
    )


def table_counts(conn: psycopg.Connection) -> tuple[int, int]:
    """(number of games, number of moves) currently stored."""
    row = conn.execute(
        "SELECT (SELECT count(*) FROM games), (SELECT count(*) FROM moves)"
    ).fetchone()
    return row[0], row[1]
