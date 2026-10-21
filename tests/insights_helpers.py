"""Helpers for the insights tests: games, moves and losses written with plain SQL."""

import itertools

_ids = itertools.count(1)

# Only the piece placement matters to the phase rule. Counted pieces exclude pawns and kings.
FEN_FULL = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"  # 14 pieces
FEN_SEVEN = "rnbqk3/pppp4/8/8/8/8/PPPP4/RNB1K3 w - - 0 1"  # 7 pieces
FEN_SIX = "rnb1k3/pppp4/8/8/8/8/PPPP4/RNB1K3 w - - 0 1"  # 6 pieces

INSERT_GAME = (
    "INSERT INTO games (lichess_id, played_at, speed, rated, color, result, status, "
    "opponent_name, opponent_is_ai, opening_name, moves_san) "
    "VALUES (%s, '2024-01-01'::timestamptz, 'blitz', true, %s, %s, 'mate', 'opponent', "
    "%s, %s, 'x') RETURNING id"
)
INSERT_MOVE = (
    "INSERT INTO moves (game_id, ply, san, uci, fen_after) VALUES (%s, %s, 'x', 'a1a1', %s)"
)
INSERT_LOSS = (
    "INSERT INTO move_losses (analysis_run_id, game_id, ply, loss_cp, label) "
    "VALUES (%s, %s, %s, %s, %s)"
)


def mv(ply, loss_cp=0, label="ok", fen=FEN_FULL):
    """One move to store: (ply, loss_cp, label, fen_after)."""
    return (ply, loss_cp, label, fen)


def add_scored_game(
    db,
    run_id=None,
    *,
    color="white",
    result="win",
    opening="Italian Game: Giuoco Piano",
    opponent_is_ai=False,
    moves=(),
) -> int:
    """Insert a game, plus a move row and a loss row for each entry in `moves`."""
    lichess_id = f"g{next(_ids):07d}"
    game_id = db.execute(
        INSERT_GAME, (lichess_id, color, result, opponent_is_ai, opening)
    ).fetchone()[0]
    for ply, loss_cp, label, fen in moves:
        db.execute(INSERT_MOVE, (game_id, ply, fen))
        db.execute(INSERT_LOSS, (run_id, game_id, ply, loss_cp, label))
    return game_id
