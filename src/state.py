"""Remembers how far we have fetched. Scaffolding until the database exists (Day 7)."""

import json
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / ".fetch_state.json"


def load_since(username: str, path: Path = STATE_FILE) -> int | None:
    """Return the saved cursor (milliseconds since epoch) for this user, or None."""
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("username") != username.lower():
        return None
    since = data.get("since_ms")
    return since if isinstance(since, int) else None


def save_since(username: str, since_ms: int, path: Path = STATE_FILE) -> None:
    """Save the cursor. Writes a temp file first so a crash can't leave a half-written file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"username": username.lower(), "since_ms": since_ms}))
    tmp.replace(path)
