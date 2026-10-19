"""Fetch games from the Lichess API and print a short summary of each."""

import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from config import LICHESS_USERNAME

BASE_URL = "https://lichess.org"
USER_AGENT = "chess-analyzer (+https://github.com/Blazene/chess-analyzer)"


def stream_games(username: str, max_games: int | None = None) -> Iterator[dict]:
    """Yield one game (as a dict) at a time, newest first."""
    params: dict = {"clocks": True, "opening": True, "evals": True, "moves": True}
    if max_games is not None:
        params["max"] = max_games

    headers = {"Accept": "application/x-ndjson", "User-Agent": USER_AGENT}
    timeout = httpx.Timeout(10.0, read=60.0)

    with httpx.stream(
        "GET",
        f"{BASE_URL}/api/games/user/{username}",
        params=params,
        headers=headers,
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                yield json.loads(line)


def describe(game: dict, username: str) -> str:
    """Turn one raw game into a one-line summary from the user's point of view."""
    white = game["players"]["white"]
    black = game["players"]["black"]
    white_name = white.get("user", {}).get("name", "").lower()

    color = "white" if white_name == username.lower() else "black"
    me = white if color == "white" else black

    winner = game.get("winner")
    if winner is None:
        result = "draw"
    elif winner == color:
        result = "win"
    else:
        result = "loss"

    played = datetime.fromtimestamp(game["createdAt"] / 1000, tz=UTC).date()
    opening = game.get("opening", {}).get("name", "unknown")
    rating = me.get("rating", "?")

    return f"{played}  {game['speed']:<10} {color:<6} {result:<5} {rating:>5}  {opening}"


def main() -> None:
    games = list(stream_games(LICHESS_USERNAME, max_games=50))

    if "--raw" in sys.argv and games:
        print(json.dumps(games[0], indent=2))
        return

    print(f"Fetched {len(games)} games for {LICHESS_USERNAME}\n")
    for game in games:
        print(describe(game, LICHESS_USERNAME))


if __name__ == "__main__":
    main()
