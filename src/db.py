"""Database access. Together with migrate.py, the only place that runs SQL."""

from collections.abc import Sequence
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from analyze import PlyEval
from loss import MoveLoss
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


GAME_COLUMNS = ("lichess_id", "color", "result", "status", "opponent_name", "moves_san")


def get_game(conn: psycopg.Connection, lichess_id: str | None = None) -> dict | None:
    """One stored game as a dict (your newest game if no id is given), or None."""
    columns = ", ".join(GAME_COLUMNS)
    if lichess_id is None:
        sql = f"SELECT {columns} FROM games ORDER BY played_at DESC LIMIT 1"
        row = conn.execute(sql).fetchone()
    else:
        sql = f"SELECT {columns} FROM games WHERE lichess_id = %s"
        row = conn.execute(sql, (lichess_id,)).fetchone()
    return None if row is None else dict(zip(GAME_COLUMNS, row, strict=True))


GET_OR_CREATE_RUN_SQL = """
INSERT INTO analysis_runs (engine_name, depth) VALUES (%s, %s)
ON CONFLICT (engine_name, depth) DO UPDATE SET engine_name = EXCLUDED.engine_name
RETURNING id
"""

INSERT_EVALUATION_SQL = (
    "INSERT INTO evaluations "
    "(analysis_run_id, game_id, ply, stockfish_cp, stockfish_mate, best_move) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)

INSERT_MOVE_LOSS_SQL = (
    "INSERT INTO move_losses (analysis_run_id, game_id, ply, loss_cp, label) "
    "VALUES (%s, %s, %s, %s, %s)"
)

# A game is analyzed for a run once ANY evaluation row exists for it. That is safe because
# store_analysis writes all of a game's rows in one transaction.
UNANALYZED_SQL = """
FROM games g
WHERE NOT EXISTS (
    SELECT 1 FROM evaluations e WHERE e.analysis_run_id = %s AND e.game_id = g.id
)
"""


def get_or_create_run(conn: psycopg.Connection, engine_name: str, depth: int) -> int:
    """The id of the analysis run for these settings, created on first use.

    The no-op DO UPDATE is there so RETURNING also works when the row already exists.
    """
    return conn.execute(GET_OR_CREATE_RUN_SQL, (engine_name, depth)).fetchone()[0]


def games_to_analyze(conn: psycopg.Connection, run_id: int, limit: int | None = None) -> list[dict]:
    """Games with no evaluations under this run, newest first."""
    sql = "SELECT g.id, g.lichess_id, g.moves_san " + UNANALYZED_SQL
    sql += " ORDER BY g.played_at DESC, g.id DESC"
    params: list = [run_id]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [{"id": r[0], "lichess_id": r[1], "moves_san": r[2]} for r in rows]


def remaining_work(conn: psycopg.Connection, run_id: int) -> tuple[int, int]:
    """(games not yet analyzed under this run, total moves in those games)."""
    sql = (
        "SELECT count(*), coalesce(sum(n), 0) FROM ("
        "SELECT (SELECT count(*) FROM moves m WHERE m.game_id = g.id) AS n "
        + UNANALYZED_SQL
        + ") t"
    )
    row = conn.execute(sql, (run_id,)).fetchone()
    return row[0], int(row[1])


def store_analysis(
    conn: psycopg.Connection,
    run_id: int,
    game_id: int,
    results: Sequence[PlyEval],
    losses: Sequence[MoveLoss],
) -> None:
    """Save one game's evaluations and move losses in ONE transaction.

    Positions with no evaluation (a finished game) get no evaluations row.
    Storing the same game twice for one run is an error, not a silent overwrite.
    """
    evaluation_rows = [
        (run_id, game_id, r.ply, r.evaluation.cp, r.evaluation.mate, r.evaluation.best_move)
        for r in results
        if r.evaluation is not None
    ]
    loss_rows = [(run_id, game_id, m.ply, m.loss_cp, m.label) for m in losses]
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(INSERT_EVALUATION_SQL, evaluation_rows)
        cur.executemany(INSERT_MOVE_LOSS_SQL, loss_rows)


def recent_games(conn: psycopg.Connection, limit: int) -> list[dict]:
    """The newest stored games, analyzed or not. Used for timing experiments."""
    rows = conn.execute(
        "SELECT id, lichess_id, moves_san FROM games ORDER BY played_at DESC, id DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [{"id": r[0], "lichess_id": r[1], "moves_san": r[2]} for r in rows]


INTEGRITY_SQL = """
SELECT g.lichess_id,
       (SELECT count(*) FROM moves m WHERE m.game_id = g.id),
       (SELECT count(*) FROM evaluations e
         WHERE e.analysis_run_id = %s AND e.game_id = g.id),
       (SELECT count(*) FROM move_losses l
         WHERE l.analysis_run_id = %s AND l.game_id = g.id)
FROM games g
ORDER BY g.id
"""


def integrity_rows(conn: psycopg.Connection, run_id: int) -> list[tuple]:
    """(lichess_id, moves, evaluations, move_losses) for every stored game."""
    return conn.execute(INTEGRITY_SQL, (run_id, run_id)).fetchall()


def comparison_data(conn: psycopg.Connection, run_id: int) -> list[dict]:
    """Games that carry Lichess's own analysis, with our evaluations and labels for them."""
    games = conn.execute(
        "SELECT id, lichess_id, lichess_analysis FROM games "
        "WHERE lichess_analysis IS NOT NULL ORDER BY id"
    ).fetchall()
    ids = [g[0] for g in games]
    cps: dict[int, dict] = {i: {} for i in ids}
    labels: dict[int, dict] = {i: {} for i in ids}

    evaluations = conn.execute(
        "SELECT game_id, ply, stockfish_cp, stockfish_mate FROM evaluations "
        "WHERE analysis_run_id = %s AND game_id = ANY(%s)",
        (run_id, ids),
    )
    for game_id, ply, cp, mate in evaluations:
        cps[game_id][ply] = (cp, mate)

    move_losses = conn.execute(
        "SELECT game_id, ply, label FROM move_losses "
        "WHERE analysis_run_id = %s AND game_id = ANY(%s)",
        (run_id, ids),
    )
    for game_id, ply, label in move_losses:
        labels[game_id][ply] = label

    return [
        {"lichess_id": g[1], "analysis": g[2], "cps": cps[g[0]], "labels": labels[g[0]]}
        for g in games
    ]
