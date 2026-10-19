import psycopg
from db_helpers import TEST_DATABASE_URL, count

from db import connect, store_game
from models import parse_game


def test_store_game_commits_even_after_an_earlier_read(test_db_ready, raw_game):
    """Proves each game is committed for real. Another connection must see it at once."""
    game = parse_game(raw_game, "blazene")
    writer = connect(TEST_DATABASE_URL)
    try:
        writer.execute("SELECT 1")  # a read first, like the sync's cursor lookup
        store_game(writer, game)

        with psycopg.connect(TEST_DATABASE_URL) as reader:
            assert count(reader, "games") == 1
            assert count(reader, "moves") == 63
    finally:
        writer.close()
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as cleaner:
            cleaner.execute("DELETE FROM games")
