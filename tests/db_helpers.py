"""Helpers for tests that need the database (same idea as the bank's tests/helpers/db.js)."""

TEST_DATABASE_URL = "postgresql://analyzer:analyzer@localhost:5433/chess_analyzer_test"

GAME_DEFAULTS = {
    "lichess_id": "4MhVOLfl",
    "played_at": "2026-10-17T13:49:04Z",
    "speed": "blitz",
    "rated": True,
    "color": "black",
    "result": "loss",
    "status": "outoftime",
    "opponent_name": "a_jakov95",
    "moves_san": "e4 c5",
}


def assert_test_database(url: str) -> None:
    """Refuse destructive setup on any database whose name does not end in _test."""
    name = url.rsplit("/", 1)[-1].split("?")[0]
    if not name.endswith("_test"):
        raise RuntimeError(f"Refusing to reset database '{name}': its name must end in _test")


def insert(db, table: str, **values) -> None:
    """Insert one row. Table and column names come from test code only, never from users."""
    columns = ", ".join(values)
    placeholders = ", ".join(["%s"] * len(values))
    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(values.values()))


def insert_game(db, **overrides) -> int:
    values = {**GAME_DEFAULTS, **overrides}
    columns = ", ".join(values)
    placeholders = ", ".join(["%s"] * len(values))
    sql = f"INSERT INTO games ({columns}) VALUES ({placeholders}) RETURNING id"
    return db.execute(sql, list(values.values())).fetchone()[0]


def insert_run(db, **overrides) -> int:
    values = {"engine_name": "Stockfish 17.1", "depth": 14, **overrides}
    columns = ", ".join(values)
    placeholders = ", ".join(["%s"] * len(values))
    sql = f"INSERT INTO analysis_runs ({columns}) VALUES ({placeholders}) RETURNING id"
    return db.execute(sql, list(values.values())).fetchone()[0]


def count(db, table: str) -> int:
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
