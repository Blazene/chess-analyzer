"""Typed representation of a Lichess game, and the parser that builds it."""

from dataclasses import dataclass
from datetime import UTC, datetime

# Games that never really started. They have no winner and no useful moves.
SKIPPED_STATUSES = {"created", "started", "aborted", "noStart", "unknownFinish"}


@dataclass(frozen=True)
class Game:
    lichess_id: str
    played_at: datetime
    speed: str
    rated: bool
    color: str  # "white" or "black": the colour I played
    result: str  # "win", "loss" or "draw": from my point of view
    status: str  # how the game ended: mate, resign, outoftime, ...
    rating: int | None
    rating_diff: int | None
    opponent_name: str
    opponent_rating: int | None
    opponent_is_ai: bool
    opening_eco: str | None
    opening_name: str | None
    opening_ply: int | None
    clock_initial: int | None  # seconds
    clock_increment: int | None  # seconds
    moves: str  # SAN moves, space separated
    clocks: tuple[int, ...]  # centiseconds, white first, then black alternating
    lichess_analysis: list[dict] | None  # Lichess's own evals, when they exist


def parse_game(raw: dict, username: str) -> Game | None:
    """Build a Game from one raw Lichess game. Returns None for games we skip."""
    if raw.get("variant") != "standard" or raw["status"] in SKIPPED_STATUSES:
        return None

    white = raw["players"]["white"]
    black = raw["players"]["black"]
    wanted = username.lower()

    if white.get("user", {}).get("id") == wanted:
        color, me, opponent = "white", white, black
    elif black.get("user", {}).get("id") == wanted:
        color, me, opponent = "black", black, white
    else:
        raise ValueError(f"Game {raw['id']} does not involve user {username}")

    winner = raw.get("winner")
    if winner is None:
        result = "draw"
    elif winner == color:
        result = "win"
    else:
        result = "loss"

    ai_level = opponent.get("aiLevel")
    if ai_level is not None:
        opponent_name = f"Stockfish level {ai_level}"
    else:
        opponent_name = opponent.get("user", {}).get("name", "anonymous")

    opening = raw.get("opening") or {}
    clock = raw.get("clock") or {}

    return Game(
        lichess_id=raw["id"],
        played_at=datetime.fromtimestamp(raw["createdAt"] / 1000, tz=UTC),
        speed=raw["speed"],
        rated=raw["rated"],
        color=color,
        result=result,
        status=raw["status"],
        rating=me.get("rating"),
        rating_diff=me.get("ratingDiff"),
        opponent_name=opponent_name,
        opponent_rating=opponent.get("rating"),
        opponent_is_ai=ai_level is not None,
        opening_eco=opening.get("eco"),
        opening_name=opening.get("name"),
        opening_ply=opening.get("ply"),
        clock_initial=clock.get("initial"),
        clock_increment=clock.get("increment"),
        moves=raw.get("moves", ""),
        clocks=tuple(raw.get("clocks", [])),
        lichess_analysis=raw.get("analysis"),
    )
