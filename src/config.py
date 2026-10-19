"""Settings loaded from .env. Fails fast if something is missing."""

import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing setting {name}. Add it to your .env file.")
    return value


LICHESS_USERNAME = _require("LICHESS_USERNAME")
if LICHESS_USERNAME == "your_lichess_username":
    raise RuntimeError("Replace the placeholder LICHESS_USERNAME in .env with your real username.")

DATABASE_URL = _require("DATABASE_URL")
STOCKFISH_PATH = _require("STOCKFISH_PATH")
