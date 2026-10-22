from datetime import date

import pytest

from filters import Filters, render


def test_default_filters_only_exclude_the_computer():
    sql, params = Filters().where()

    assert sql == "(%(include_ai)s OR NOT g.opponent_is_ai)"
    assert params == {"include_ai": False}


def test_a_color_adds_a_clause_and_a_parameter():
    sql, params = Filters(color="black").where()

    assert "g.color = %(color)s" in sql
    assert params["color"] == "black"


def test_speeds_become_an_any_clause_with_a_list_parameter():
    sql, params = Filters(speeds=("blitz", "rapid")).where()

    assert "g.speed = ANY(%(speeds)s)" in sql
    assert params["speeds"] == ["blitz", "rapid"]


def test_no_speeds_selected_matches_nothing_and_adds_no_parameter():
    sql, params = Filters(speeds=()).where()

    assert "FALSE" in sql
    assert "speeds" not in params


def test_both_dates_add_inclusive_utc_clauses():
    sql, params = Filters(start=date(2024, 1, 1), end=date(2024, 2, 1)).where()

    assert ">= %(start)s" in sql
    assert "<= %(end)s" in sql
    assert params["start"] == date(2024, 1, 1)
    assert params["end"] == date(2024, 2, 1)


def test_one_date_adds_only_its_own_clause():
    sql, params = Filters(start=date(2024, 1, 1)).where()

    assert "%(start)s" in sql
    assert "%(end)s" not in sql
    assert "end" not in params


def test_an_unknown_color_is_rejected():
    with pytest.raises(ValueError, match="color"):
        Filters(color="green")


def test_a_start_after_the_end_is_rejected():
    with pytest.raises(ValueError, match="start"):
        Filters(start=date(2024, 2, 1), end=date(2024, 1, 1))


def test_a_one_day_range_is_allowed():
    Filters(start=date(2024, 1, 1), end=date(2024, 1, 1))


def test_render_fills_the_where_placeholder_and_merges_parameters():
    sql, params = render("SELECT 1 FROM games g WHERE {where}", Filters(color="white"), n=5)

    assert "{" not in sql
    assert "g.color = %(color)s" in sql
    assert params == {"include_ai": False, "color": "white", "n": 5}


def test_render_fills_my_moves_and_the_filters_inside_it():
    sql, params = render("{my_moves}\nSELECT 1 FROM my_moves", Filters(color="white"), run_id=7)

    assert sql.lstrip().startswith("WITH my_moves AS")
    assert "{" not in sql
    assert "g.color = %(color)s" in sql
    assert params["run_id"] == 7
