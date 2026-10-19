"""Apply the SQL files in sql/migrations/ in order. Each file runs in its own transaction."""

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"


def apply_migrations(database_url: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration not yet recorded. Returns the versions applied by this call."""
    applied_now: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(directory.glob("*.sql")):
            if path.stem in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            applied_now.append(path.stem)
    return applied_now


def main() -> None:
    from config import DATABASE_URL

    applied = apply_migrations(DATABASE_URL)
    if applied:
        print("Applied: " + ", ".join(applied))
    else:
        print("Nothing to apply: database is up to date")


if __name__ == "__main__":
    main()
