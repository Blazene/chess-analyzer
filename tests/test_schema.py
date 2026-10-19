import psycopg
import pytest
from db_helpers import (
    TEST_DATABASE_URL,
    assert_test_database,
    count,
    insert,
    insert_game,
    insert_run,
)
from psycopg.types.json import Jsonb

FEN_AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
MOVE = {"san": "e4", "uci": "e2e4", "fen_after": FEN_AFTER_E4, "clock_cs": 18003}

CheckViolation = psycopg.errors.CheckViolation
UniqueViolation = psycopg.errors.UniqueViolation
ForeignKeyViolation = psycopg.errors.ForeignKeyViolation
NotNullViolation = psycopg.errors.NotNullViolation


# ---------- games ----------


def test_valid_game_is_accepted_with_defaults(db):
    game_id = insert_game(db)

    row = db.execute(
        "SELECT opponent_is_ai, created_at, rating, lichess_analysis FROM games WHERE id = %s",
        (game_id,),
    ).fetchone()

    assert row[0] is False
    assert row[1] is not None
    assert row[2] is None
    assert row[3] is None


def test_duplicate_lichess_id_is_rejected(db):
    insert_game(db)

    with pytest.raises(UniqueViolation) as exc:
        insert_game(db)

    assert exc.value.diag.constraint_name == "games_lichess_id_unique"


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("lichess_id", "abc", "games_lichess_id_format"),
        ("speed", "hyperbullet", "games_speed_valid"),
        ("color", "green", "games_color_valid"),
        ("result", "won", "games_result_valid"),
        ("status", "", "games_status_not_empty"),
        ("rating", 0, "games_rating_positive"),
        ("opponent_rating", -5, "games_opponent_rating_positive"),
        ("opening_eco", "Z99", "games_opening_eco_format"),
        ("opening_ply", -1, "games_opening_ply_nonnegative"),
        ("clock_initial", -1, "games_clock_initial_nonnegative"),
        ("clock_increment", -1, "games_clock_increment_nonnegative"),
    ],
)
def test_games_check_constraints(db, field, value, constraint):
    with pytest.raises(CheckViolation) as exc:
        insert_game(db, **{field: value})

    assert exc.value.diag.constraint_name == constraint


def test_lichess_analysis_must_be_a_json_array(db):
    with pytest.raises(CheckViolation) as exc:
        insert_game(db, lichess_analysis=Jsonb({"eval": 20}))

    assert exc.value.diag.constraint_name == "games_lichess_analysis_array"


def test_lichess_analysis_array_is_accepted(db):
    game_id = insert_game(db, lichess_analysis=Jsonb([{"eval": 20}]))

    stored = db.execute("SELECT lichess_analysis FROM games WHERE id = %s", (game_id,))

    assert stored.fetchone()[0] == [{"eval": 20}]


@pytest.mark.parametrize(
    "field",
    [
        "lichess_id",
        "played_at",
        "speed",
        "rated",
        "color",
        "result",
        "status",
        "opponent_name",
        "moves_san",
    ],
)
def test_required_game_columns(db, field):
    with pytest.raises(NotNullViolation) as exc:
        insert_game(db, **{field: None})

    assert exc.value.diag.column_name == field


# ---------- moves ----------


def test_valid_move_is_accepted(db):
    game_id = insert_game(db)

    insert(db, "moves", game_id=game_id, ply=1, **MOVE)

    assert count(db, "moves") == 1


def test_ply_zero_is_rejected(db):
    game_id = insert_game(db)

    with pytest.raises(CheckViolation) as exc:
        insert(db, "moves", game_id=game_id, ply=0, **MOVE)

    assert exc.value.diag.constraint_name == "moves_ply_positive"


def test_duplicate_ply_in_a_game_is_rejected(db):
    game_id = insert_game(db)
    insert(db, "moves", game_id=game_id, ply=1, **MOVE)

    with pytest.raises(UniqueViolation) as exc:
        insert(db, "moves", game_id=game_id, ply=1, **MOVE)

    assert exc.value.diag.constraint_name == "moves_pkey"


def test_move_for_missing_game_is_rejected(db):
    with pytest.raises(ForeignKeyViolation) as exc:
        insert(db, "moves", game_id=999999, ply=1, **MOVE)

    assert exc.value.diag.constraint_name == "moves_game_id_fkey"


def test_negative_clock_is_rejected(db):
    game_id = insert_game(db)

    with pytest.raises(CheckViolation) as exc:
        insert(db, "moves", game_id=game_id, ply=1, **{**MOVE, "clock_cs": -1})

    assert exc.value.diag.constraint_name == "moves_clock_nonnegative"


def test_deleting_a_game_removes_its_moves_and_evaluations(db):
    game_id = insert_game(db)
    run_id = insert_run(db)
    insert(db, "moves", game_id=game_id, ply=1, **MOVE)
    insert(db, "evaluations", analysis_run_id=run_id, game_id=game_id, ply=1, stockfish_cp=20)

    db.execute("DELETE FROM games WHERE id = %s", (game_id,))

    assert count(db, "moves") == 0
    assert count(db, "evaluations") == 0
    assert count(db, "analysis_runs") == 1


def test_deleting_a_run_removes_only_its_evaluations(db):
    game_id = insert_game(db)
    run_id = insert_run(db)
    insert(db, "moves", game_id=game_id, ply=1, **MOVE)
    insert(db, "evaluations", analysis_run_id=run_id, game_id=game_id, ply=1, stockfish_cp=20)

    db.execute("DELETE FROM analysis_runs WHERE id = %s", (run_id,))

    assert count(db, "evaluations") == 0
    assert count(db, "games") == 1
    assert count(db, "moves") == 1


# ---------- analysis_runs ----------


def test_valid_run_is_accepted(db):
    run_id = insert_run(db)

    assert isinstance(run_id, int)


def test_duplicate_run_settings_are_rejected(db):
    insert_run(db)

    with pytest.raises(UniqueViolation) as exc:
        insert_run(db)

    assert exc.value.diag.constraint_name == "analysis_runs_settings_unique"


def test_same_engine_at_a_different_depth_is_allowed(db):
    insert_run(db, depth=14)
    insert_run(db, depth=18)

    assert count(db, "analysis_runs") == 2


def test_depth_zero_is_rejected(db):
    with pytest.raises(CheckViolation) as exc:
        insert_run(db, depth=0)

    assert exc.value.diag.constraint_name == "analysis_runs_depth_positive"


# ---------- evaluations ----------


def test_centipawn_evaluation_is_accepted(db):
    game_id, run_id = insert_game(db), insert_run(db)

    insert(db, "evaluations", analysis_run_id=run_id, game_id=game_id, ply=1, stockfish_cp=-35)

    assert count(db, "evaluations") == 1


def test_mate_evaluation_is_accepted(db):
    game_id, run_id = insert_game(db), insert_run(db)

    insert(db, "evaluations", analysis_run_id=run_id, game_id=game_id, ply=1, stockfish_mate=-3)

    assert count(db, "evaluations") == 1


def test_evaluation_with_both_cp_and_mate_is_rejected(db):
    game_id, run_id = insert_game(db), insert_run(db)

    with pytest.raises(CheckViolation) as exc:
        insert(
            db,
            "evaluations",
            analysis_run_id=run_id,
            game_id=game_id,
            ply=1,
            stockfish_cp=20,
            stockfish_mate=3,
        )

    assert exc.value.diag.constraint_name == "evaluations_cp_xor_mate"


def test_evaluation_with_neither_cp_nor_mate_is_rejected(db):
    game_id, run_id = insert_game(db), insert_run(db)

    with pytest.raises(CheckViolation) as exc:
        insert(db, "evaluations", analysis_run_id=run_id, game_id=game_id, ply=1)

    assert exc.value.diag.constraint_name == "evaluations_cp_xor_mate"


def test_negative_ply_is_rejected(db):
    game_id, run_id = insert_game(db), insert_run(db)

    with pytest.raises(CheckViolation) as exc:
        insert(db, "evaluations", analysis_run_id=run_id, game_id=game_id, ply=-1, stockfish_cp=0)

    assert exc.value.diag.constraint_name == "evaluations_ply_nonnegative"


def test_ply_zero_start_position_is_accepted(db):
    game_id, run_id = insert_game(db), insert_run(db)

    insert(db, "evaluations", analysis_run_id=run_id, game_id=game_id, ply=0, stockfish_cp=20)

    assert count(db, "evaluations") == 1


def test_duplicate_evaluation_is_rejected(db):
    game_id, run_id = insert_game(db), insert_run(db)
    insert(db, "evaluations", analysis_run_id=run_id, game_id=game_id, ply=1, stockfish_cp=20)

    with pytest.raises(UniqueViolation) as exc:
        insert(db, "evaluations", analysis_run_id=run_id, game_id=game_id, ply=1, stockfish_cp=30)

    assert exc.value.diag.constraint_name == "evaluations_pkey"


def test_evaluation_for_missing_game_is_rejected(db):
    run_id = insert_run(db)

    with pytest.raises(ForeignKeyViolation) as exc:
        insert(db, "evaluations", analysis_run_id=run_id, game_id=999999, ply=1, stockfish_cp=0)

    assert exc.value.diag.constraint_name == "evaluations_game_id_fkey"


def test_evaluation_for_missing_run_is_rejected(db):
    game_id = insert_game(db)

    with pytest.raises(ForeignKeyViolation) as exc:
        insert(db, "evaluations", analysis_run_id=999999, game_id=game_id, ply=1, stockfish_cp=0)

    assert exc.value.diag.constraint_name == "evaluations_analysis_run_id_fkey"


# ---------- migrations and test safety ----------


def test_applying_migrations_twice_changes_nothing(test_db_ready):
    from migrate import apply_migrations

    assert apply_migrations(TEST_DATABASE_URL) == []

    with psycopg.connect(TEST_DATABASE_URL) as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
    assert "0001_init_schema" in versions


def test_expected_indexes_exist(db):
    rows = db.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    names = {row[0] for row in rows}

    assert {"games_played_at_idx", "evaluations_game_id_idx"} <= names


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@localhost:5433/chess_analyzer",
        "postgresql://u:p@localhost:5433/postgres",
    ],
)
def test_guard_refuses_real_databases(url):
    with pytest.raises(RuntimeError, match="_test"):
        assert_test_database(url)


def test_guard_accepts_the_test_database():
    assert_test_database(TEST_DATABASE_URL)
