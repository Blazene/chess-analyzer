from state import load_since, save_since


def test_no_file_means_no_cursor(tmp_path):
    assert load_since("blazene", path=tmp_path / "state.json") is None


def test_save_then_load(tmp_path):
    path = tmp_path / "state.json"

    save_since("blazene", 1792244944437, path=path)

    assert load_since("blazene", path=path) == 1792244944437


def test_username_is_case_insensitive(tmp_path):
    path = tmp_path / "state.json"

    save_since("Blazene", 5, path=path)

    assert load_since("BLAZENE", path=path) == 5


def test_cursor_for_another_user_is_ignored(tmp_path):
    path = tmp_path / "state.json"

    save_since("blazene", 5, path=path)

    assert load_since("someone_else", path=path) is None


def test_corrupted_file_means_no_cursor(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")

    assert load_since("blazene", path=path) is None
