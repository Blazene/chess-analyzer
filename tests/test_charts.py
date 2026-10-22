import pandas as pd

from charts import bar_chart, fill_missing_months, line_chart, openings_chart


def months(*rows):
    return pd.DataFrame(rows, columns=["Month", "Score %", "Avg rating"])


def gap_frame():
    return months(("2024-01", 80.0, 1000), ("2024-04", 60.0, 1100))


# ---------- filling in months ----------


def test_months_without_games_are_added_as_empty_rows():
    filled = fill_missing_months(gap_frame())

    assert list(filled["Month"]) == ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert filled["Score %"].isna().tolist() == [False, True, True, False]


def test_existing_months_keep_their_values():
    filled = fill_missing_months(gap_frame())

    assert filled["Score %"].dropna().tolist() == [80.0, 60.0]
    assert filled["Avg rating"].dropna().tolist() == [1000.0, 1100.0]


def test_an_empty_table_stays_empty():
    assert fill_missing_months(pd.DataFrame(columns=["Month", "Score %"])).empty


# ---------- line chart ----------


def test_the_line_has_a_break_for_every_missing_month():
    fig = line_chart(gap_frame(), "Score %", "T", "Y")

    assert list(fig.data[0].y) == [80.0, None, None, 60.0]


def test_the_axis_lists_every_month_including_the_empty_ones():
    fig = line_chart(gap_frame(), "Score %", "T", "Y")

    assert list(fig.data[0].x) == ["2024-01", "2024-02", "2024-03", "2024-04"]


def test_the_line_is_not_drawn_across_a_gap():
    fig = line_chart(gap_frame(), "Score %", "T", "Y")

    assert fig.data[0].connectgaps is False


def test_a_missing_value_in_a_month_that_has_games_is_a_break_too():
    frame = months(("2024-01", 80.0, 1000), ("2024-02", 70.0, None))

    fig = line_chart(frame, "Avg rating", "T", "Y")

    assert list(fig.data[0].y) == [1000.0, None]


def test_the_vertical_range_can_be_fixed():
    fig = line_chart(gap_frame(), "Score %", "T", "Y", y_range=(0, 100))

    assert tuple(fig.layout.yaxis.range) == (0, 100)


def test_the_line_chart_has_a_title_and_an_axis_label():
    fig = line_chart(gap_frame(), "Score %", "Score by month", "percent")

    assert fig.layout.title.text == "Score by month"
    assert fig.layout.yaxis.title.text == "percent"


# ---------- bar chart ----------


def test_bars_keep_the_tables_order_and_values():
    frame = pd.DataFrame({"Phase": ["opening", "middlegame"], "Blunder %": [4.5, 9.0]})

    fig = bar_chart(frame, "Phase", "Blunder %", "T", "Y")

    assert list(fig.data[0].x) == ["opening", "middlegame"]
    assert list(fig.data[0].y) == [4.5, 9.0]


def test_a_bar_chart_has_a_title_and_an_axis_label():
    frame = pd.DataFrame({"Phase": ["opening"], "Blunder %": [4.5]})

    fig = bar_chart(frame, "Phase", "Blunder %", "Blunders", "percent")

    assert fig.layout.title.text == "Blunders"
    assert fig.layout.yaxis.title.text == "percent"


def test_a_bar_chart_of_an_empty_table_has_no_bars():
    fig = bar_chart(pd.DataFrame(columns=["Phase", "Blunder %"]), "Phase", "Blunder %", "T", "Y")

    assert len(fig.data[0].x) == 0


# ---------- openings chart ----------


def openings(count):
    return pd.DataFrame(
        {
            "Color": ["white"] * count,
            "Opening": [f"Opening {n}" for n in range(1, count + 1)],
            "Score %": [float(n) for n in range(1, count + 1)],
        }
    )


def test_openings_are_labelled_with_their_color_and_most_played_ends_on_top():
    frame = pd.DataFrame(
        {
            "Color": ["white", "black"],
            "Opening": ["Italian Game", "Sicilian Defense"],
            "Score %": [60.0, 40.0],
        }
    )

    fig = openings_chart(frame)

    assert list(fig.data[0].y) == ["Sicilian Defense (black)", "Italian Game (white)"]
    assert list(fig.data[0].x) == [40.0, 60.0]


def test_only_the_most_played_openings_are_shown():
    fig = openings_chart(openings(12), top=10)

    assert len(fig.data[0].y) == 10
    assert "Opening 1 (white)" in list(fig.data[0].y)
    assert "Opening 11 (white)" not in list(fig.data[0].y)


def test_the_openings_chart_has_a_fifty_percent_reference_line():
    fig = openings_chart(openings(3))

    assert len(fig.layout.shapes) == 1
    assert fig.layout.shapes[0].x0 == 50
