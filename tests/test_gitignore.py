import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def is_ignored(path: str) -> bool:
    """True if git would ignore this path (works even if the file does not exist)."""
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    return result.returncode == 0


def test_the_env_file_is_ignored():
    assert is_ignored(".env")


def test_streamlit_secrets_are_ignored():
    assert is_ignored(".streamlit/secrets.toml")
