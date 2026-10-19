import json
import os
from pathlib import Path

import psycopg
import pytest
from db_helpers import TEST_DATABASE_URL, assert_test_database

# Tests must never depend on the developer's real .env (same idea as the bank's .env.test).
os.environ["LICHESS_USERNAME"] = "test_user"
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5433/test"
os.environ["STOCKFISH_PATH"] = "/usr/bin/stockfish"

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_game() -> dict:
    """A fresh copy of a real Lichess game: blazene as black, lost on time."""
    with open(FIXTURES / "game_outoftime.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def test_db_ready():
    """Rebuild the test database from the migration files, once per test session."""
    from migrate import apply_migrations

    assert_test_database(TEST_DATABASE_URL)
    try:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DROP SCHEMA public CASCADE")
            conn.execute("CREATE SCHEMA public")
    except psycopg.OperationalError as exc:
        raise RuntimeError(
            "Cannot reach the test database. Is Docker running, and does "
            "chess_analyzer_test exist? (Day 5, Step 5)"
        ) from exc
    apply_migrations(TEST_DATABASE_URL)


@pytest.fixture
def db(test_db_ready):
    """A connection whose work is rolled back after every test."""
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        yield conn
        conn.rollback()
