import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Written in two parts so this file does not contain the strings it searches for.
MARKERS = ("neon" + ".tech", "channel" + "_binding")


def tracked_text_files() -> list[tuple[str, str]]:
    names = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    files = []
    for name in names:
        try:
            files.append((name, (ROOT / name).read_text(encoding="utf-8")))
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # images and other binary files
    return files


def test_no_tracked_file_contains_a_neon_hostname_or_connection_option():
    offenders = [
        name for name, text in tracked_text_files() if any(marker in text for marker in MARKERS)
    ]

    assert not offenders, f"Remove the connection details from: {offenders}"
