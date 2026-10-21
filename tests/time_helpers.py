"""Helpers for the time-insight tests: games, moves with clocks, and losses via plain SQL."""

import itertools

_ids = itertools.count(1)

FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

INSERT_GAME = (
    "INSERT INTO games (lichess_id, played_at, speed, rated, color, result, status, rating, "
    "opponent_name, opponent_is_ai, clock_initial, moves_san) "
    "VALUES (%s, %s::timestamptz, %s, true, %s, %s, %s, %s, 'opponent', %s, %s, 'x') "
    "RETURNING id"
)
INSERT_MOVE = (
    "INSERT INTO moves (game_id, ply, san, uci, fen_after, clock_cs) "
    "VALUES (%s, %s, 'x', 'a1a1', %s, %s)"
)
INSERT_LOSS = (
    "INSERT INTO move_losses (analysis_run_id, game_id, ply, loss_cp, label) "
    "VALUES (%s, %s, %s, %s, %s)"
)


def mv(ply, clock_cs=None, loss_cp=0, label="ok"):
    """One move to store: (ply, clock_cs, loss_cp, label)."""
    return (ply, clock_cs, loss_cp, label)


def add_timed_game(
    db,
    run_id=None,
    *,
    color="white",
    result="win",
    status="mate",
    speed="blitz",
    played_at="2024-01-01 12:00+00",
    rating=None,
    clock_initial=180,
    opponent_is_ai=False,
    moves=(),
) -> int:
    """Insert a game, plus a move row and a loss row for each entry in `moves`."""
    lichess_id = f"t{next(_ids):07d}"
    game_id = db.execute(
        INSERT_GAME,
        (
            lichess_id,
            played_at,
            speed,
            color,
            result,
            status,
            rating,
            opponent_is_ai,
            clock_initial,
        ),
    ).fetchone()[0]
    for ply, clock_cs, loss_cp, label in moves:
        db.execute(INSERT_MOVE, (game_id, ply, FEN, clock_cs))
        db.execute(INSERT_LOSS, (run_id, game_id, ply, loss_cp, label))
    return game_id
