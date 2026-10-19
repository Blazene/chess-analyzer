import json
import os
from pathlib import Path

import pytest

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
