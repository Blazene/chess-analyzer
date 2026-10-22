import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def dockerfile_lines() -> list[str]:
    """Instructions with line continuations joined and comments removed."""
    text = (ROOT / "Dockerfile").read_text().replace("\\\n", " ")
    return [line.strip() for line in text.splitlines() if line.strip()]


def instructions() -> list[str]:
    return [line for line in dockerfile_lines() if not line.startswith("#")]


def ignored_paths() -> list[str]:
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def test_the_env_file_never_enters_the_build_context():
    assert ".env" in ignored_paths()


def test_git_history_and_the_virtualenv_stay_out_of_the_build_context():
    assert {".git", ".venv"} <= set(ignored_paths())


def test_dockerfile_copies_named_paths_not_the_whole_project():
    copies = [line.split() for line in instructions() if line.startswith("COPY ")]
    own_files = [tokens for tokens in copies if not any(t.startswith("--from") for t in tokens)]

    assert own_files
    for tokens in own_files:
        assert not {".", "./"} & set(tokens[1:-1])
    assert not any(line.startswith("ADD ") for line in instructions())


def test_dependencies_are_installed_from_the_lockfile():
    syncs = [line for line in instructions() if "uv sync" in line]

    assert syncs
    assert all("--locked" in line for line in syncs)


def test_development_tools_stay_out_of_the_image():
    syncs = [line for line in instructions() if "uv sync" in line]

    assert all("--no-dev" in line for line in syncs)


def test_the_container_does_not_run_as_root():
    users = [line.split()[1] for line in instructions() if line.startswith("USER ")]

    assert users
    assert users[-1] not in ("root", "0")


def test_the_image_has_a_healthcheck():
    assert any(line.startswith("HEALTHCHECK ") for line in instructions())


def test_the_image_installs_no_system_packages():
    text = "\n".join(instructions())

    assert "apt-get" not in text
    assert "apt install" not in text


def test_streamlit_listens_on_all_interfaces_and_runs_the_dashboard():
    commands = [line for line in instructions() if line.startswith("CMD ")]

    assert len(commands) == 1
    assert "--server.address=0.0.0.0" in commands[0]
    assert "src/dashboard.py" in commands[0]


def test_the_project_is_not_built_as_a_package():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert config["tool"]["uv"]["package"] is False
