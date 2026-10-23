import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
SETTINGS = {"LICHESS_USERNAME", "DATABASE_URL", "STOCKFISH_PATH"}


def is_web_link(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "#"))


def env_keys() -> set[str]:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    return {
        line.split("=", 1)[0].strip()
        for line in lines
        if "=" in line and not line.lstrip().startswith("#")
    }


def test_no_placeholder_is_left_unfilled():
    lines = [
        f"line {number}: {line.strip()[:70]}"
        for number, line in enumerate(README.splitlines(), start=1)
        if "<<FILL" in line
    ]

    assert not lines, "Fill in these before committing:\n" + "\n".join(lines)


def test_every_local_link_and_image_points_to_a_file_that_exists():
    targets = re.findall(r"\]\(([^)\s]+)\)", README)
    local = [t.split("#")[0] for t in targets if not is_web_link(t)]
    missing = [t for t in local if not (ROOT / t).exists()]

    assert not missing, f"README points at files that do not exist: {missing}"


def test_the_readme_shows_at_least_four_screenshots():
    images = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", README)
    local = [t for t in images if not is_web_link(t)]

    assert len(local) >= 4


def test_every_source_path_in_the_readme_exists():
    paths = set(re.findall(r"src/[A-Za-z_]+\.py", README))

    assert paths
    assert [p for p in sorted(paths) if not (ROOT / p).exists()] == []


def test_every_source_module_is_listed_in_the_layout_table():
    names = [path.name for path in sorted((ROOT / "src").glob("*.py"))]
    missing = [name for name in names if f"`{name}`" not in README]

    assert names
    assert not missing, f"Add these to the README layout table: {missing}"


def test_every_migration_is_listed():
    names = [path.name for path in sorted((ROOT / "sql" / "migrations").glob("*.sql"))]
    missing = [name for name in names if f"`{name}`" not in README]

    assert names
    assert not missing, f"Add these migrations to the README: {missing}"


def test_env_example_defines_exactly_the_three_settings():
    assert env_keys() == SETTINGS


def test_the_readme_names_each_setting():
    missing = [name for name in sorted(SETTINGS) if name not in README]

    assert not missing


def test_the_readme_links_to_the_live_app():
    assert re.search(r"https://[a-z0-9-]+\.streamlit\.app", README)


def test_the_readme_describes_the_deployment():
    assert "## Deployment" in README
