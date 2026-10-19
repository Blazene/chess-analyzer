"""Talk to the Lichess API. Run this file directly to PREVIEW games: nothing is stored."""

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Iterator

import httpx

from config import LICHESS_USERNAME
from models import Game, parse_game

BASE_URL = "https://lichess.org"
USER_AGENT = "chess-analyzer (+https://github.com/Blazene/chess-analyzer)"
MAX_ATTEMPTS = 5
RATE_LIMIT_WAIT_SECONDS = 60
PROGRESS_EVERY = 250


def _check_status(response: httpx.Response, username: str) -> None:
    if response.status_code == 404:
        raise RuntimeError(
            f"Lichess returned 404 for '{username}'. Either the username is wrong, "
            "or Lichess is rejecting the request (check the User-Agent header)."
        )
    response.raise_for_status()


def stream_games(
    username: str, max_games: int | None = None, since_ms: int | None = None
) -> Iterator[dict]:
    """Yield raw games (dicts), newest first. Retries when Lichess answers 429."""
    params: dict = {"clocks": True, "opening": True, "evals": True, "moves": True}
    if max_games is not None:
        params["max"] = max_games
    if since_ms is not None:
        params["since"] = since_ms

    headers = {"Accept": "application/x-ndjson", "User-Agent": USER_AGENT}
    timeout = httpx.Timeout(10.0, read=60.0)
    url = f"{BASE_URL}/api/games/user/{username}"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        with httpx.stream("GET", url, params=params, headers=headers, timeout=timeout) as response:
            if response.status_code != 429:
                _check_status(response, username)
                for line in response.iter_lines():
                    if not line:
                        continue
                    game = json.loads(line)
                    # Belt and braces: never hand back a game older than the cursor.
                    if since_ms is not None and game["createdAt"] < since_ms:
                        continue
                    yield game
                return

        if attempt == MAX_ATTEMPTS:
            raise RuntimeError("Still rate limited after several retries. Try again later.")
        print(
            f"Rate limited (429). Waiting {RATE_LIMIT_WAIT_SECONDS}s "
            f"(attempt {attempt}/{MAX_ATTEMPTS})...",
            file=sys.stderr,
        )
        time.sleep(RATE_LIMIT_WAIT_SECONDS)


def describe(game: Game) -> str:
    """One-line summary of a game."""
    rating = game.rating if game.rating is not None else "?"
    opening = game.opening_name or "unknown"
    return (
        f"{game.played_at.date()}  {game.speed:<10} {game.color:<6} "
        f"{game.result:<5} {rating:>5}  {opening}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview Lichess games (nothing is stored).")
    parser.add_argument("--max", type=int, default=None, help="stop after this many games")
    parser.add_argument("--show", type=int, default=5, help="how many games to print")
    parser.add_argument("--raw", action="store_true", help="print the newest raw game and exit")
    args = parser.parse_args()

    limit = 1 if args.raw else args.max
    games: list[Game] = []
    skipped: Counter[str] = Counter()
    seen = 0

    for raw in stream_games(LICHESS_USERNAME, max_games=limit):
        if args.raw:
            print(json.dumps(raw, indent=2))
            return

        seen += 1
        game = parse_game(raw, LICHESS_USERNAME)
        if game is None:
            skipped[f"{raw.get('variant')}/{raw.get('status')}"] += 1
        else:
            games.append(game)

        if seen % PROGRESS_EVERY == 0:
            print(f"  ...{seen} games read", flush=True)

    print(f"\nRead {seen} games, kept {len(games)}, skipped {sum(skipped.values())}")
    for reason, count in skipped.most_common():
        print(f"  skipped {count} x {reason}")

    for game in games[: args.show]:
        print(describe(game))


if __name__ == "__main__":
    main()
