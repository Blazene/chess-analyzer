"""Replay a game's SAN moves with python-chess: UCI, FEN and clock for every ply."""

from dataclasses import dataclass

import chess


@dataclass(frozen=True)
class MoveRow:
    ply: int  # 1 = White's first move, 2 = Black's first move, ...
    san: str  # the move exactly as Lichess wrote it
    uci: str  # the same move in engine notation, e.g. e2e4
    fen_after: str  # the full position after this move
    clock_cs: int | None  # the mover's remaining time after the move, in centiseconds


def replay_moves(moves_san: str, clocks: tuple[int, ...] | list[int] = ()) -> list[MoveRow]:
    """Play the moves on a fresh board. Raises ValueError (naming the ply) on an illegal move."""
    board = chess.Board()
    rows: list[MoveRow] = []

    for ply, san in enumerate(moves_san.split(), start=1):
        try:
            move = board.parse_san(san)
        except ValueError as exc:
            raise ValueError(f"cannot replay move '{san}' at ply {ply}: {exc}") from exc
        board.push(move)

        # clocks[0] is White's time after ply 1, clocks[1] is Black's after ply 2, and so on.
        clock = clocks[ply - 1] if ply <= len(clocks) else None
        rows.append(MoveRow(ply, san, move.uci(), board.fen(), clock))

    return rows
