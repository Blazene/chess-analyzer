"""Temporary Day 6 demo: store your newest usable game. Replaced by the Day 7 wiring."""

from config import DATABASE_URL, LICHESS_USERNAME
from db import connect, store_game
from fetch import stream_games
from models import parse_game


def main() -> None:
    raws = list(stream_games(LICHESS_USERNAME, max_games=10))
    games = [g for g in (parse_game(r, LICHESS_USERNAME) for r in raws) if g is not None]
    if not games:
        print("No usable game among the newest 10")
        return

    game = games[0]
    with connect(DATABASE_URL) as conn:
        is_new = store_game(conn, game)

    label = "Stored" if is_new else "Already stored"
    print(f"{label}: {game.lichess_id} ({game.color}, {game.result}, {game.status})")


if __name__ == "__main__":
    main()
