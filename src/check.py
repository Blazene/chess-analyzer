import os

import chess.engine
import psycopg
from dotenv import load_dotenv

load_dotenv()

with chess.engine.SimpleEngine.popen_uci(os.environ["STOCKFISH_PATH"]) as engine:
    print("Stockfish OK:", engine.id["name"])

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    version = conn.execute("select version()").fetchone()[0]
    print("Postgres OK:", version[:30])
