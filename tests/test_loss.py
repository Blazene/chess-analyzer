import pytest

from analyze import PlyEval
from engine import Evaluation
from loss import clamp_cp, classify, move_losses, summarize, to_cp, win_percent


def pos(ply, cp=None, mate=None, checkmate=False):
    """A position with an evaluation from White's point of view. No cp and no mate = none."""
    evaluation = None if cp is None and mate is None else Evaluation(cp, mate, None)
    return PlyEval(ply, "x" if ply else None, evaluation, 0.0, checkmate)


def only(results):
    losses = move_losses(results)
    assert len(losses) == 1
    return losses[0]


# ---------- capping and mates ----------


@pytest.mark.parametrize(
    "cp, expected", [(0, 0), (250, 250), (-250, -250), (5000, 1000), (-5000, -1000)]
)
def test_clamp_cp(cp, expected):
    assert clamp_cp(cp) == expected


@pytest.mark.parametrize("mate, expected", [(3, 1000), (-3, -1000), (1, 1000), (-9, -1000)])
def test_any_mate_becomes_the_cap_for_the_side_that_mates(mate, expected):
    assert to_cp(Evaluation(None, mate, None)) == expected


def test_centipawns_pass_through_until_the_cap():
    assert to_cp(Evaluation(120, None, None)) == 120
    assert to_cp(Evaluation(-4000, None, None)) == -1000


# ---------- win probability ----------


def test_equal_position_is_fifty_percent():
    assert win_percent(0) == pytest.approx(50.0)


def test_win_percent_is_symmetric():
    assert win_percent(300) + win_percent(-300) == pytest.approx(100.0)


def test_win_percent_rises_with_the_evaluation():
    values = [win_percent(cp) for cp in (-1000, -300, -100, 0, 100, 300, 1000)]

    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_the_cap_is_almost_but_not_exactly_certain():
    assert 97 < win_percent(1000) < 98


# ---------- thresholds ----------


@pytest.mark.parametrize(
    "drop, label",
    [
        (0.0, "ok"),
        (4.99, "ok"),
        (5.0, "inaccuracy"),
        (9.99, "inaccuracy"),
        (10.0, "mistake"),
        (14.99, "mistake"),
        (15.0, "blunder"),
        (60.0, "blunder"),
    ],
)
def test_classify_bands(drop, label):
    assert classify(drop) == label


# ---------- loss per move ----------


def test_white_blunder():
    loss = only([pos(0, 0), pos(1, -300)])

    assert (loss.ply, loss.san, loss.mover) == (1, "x", "white")
    assert loss.loss_cp == 300
    assert loss.label == "blunder"


def test_black_blunder_is_measured_from_blacks_point_of_view():
    loss = only([pos(1, 0), pos(2, 300)])

    assert loss.mover == "black"
    assert loss.loss_cp == 300
    assert loss.label == "blunder"


def test_black_improving_its_position_loses_nothing():
    loss = only([pos(1, 0), pos(2, -200)])

    assert loss.loss_cp == 0
    assert loss.win_drop == 0.0
    assert loss.label == "ok"


def test_white_improving_its_position_loses_nothing():
    loss = only([pos(0, 0), pos(1, 50)])

    assert loss.loss_cp == 0
    assert loss.win_drop == 0.0


def test_small_loss_is_an_inaccuracy():
    loss = only([pos(0, 0), pos(1, -80)])

    assert loss.loss_cp == 80
    assert loss.label == "inaccuracy"


def test_medium_loss_is_a_mistake():
    loss = only([pos(0, 0), pos(1, -140)])

    assert loss.loss_cp == 140
    assert loss.label == "mistake"


def test_tiny_loss_is_ok():
    loss = only([pos(0, 0), pos(1, -20)])

    assert loss.label == "ok"


def test_losing_centipawns_in_a_won_position_is_not_a_big_deal():
    loss = only([pos(2, 900), pos(3, 700)])

    assert loss.loss_cp == 200
    assert loss.label == "ok"


def test_scores_beyond_the_cap_do_not_count_as_loss():
    loss = only([pos(2, 2500), pos(3, 1200)])

    assert loss.loss_cp == 0


def test_a_faster_or_slower_mate_is_not_a_loss():
    loss = only([pos(2, mate=3), pos(3, mate=5)])

    assert loss.loss_cp == 0
    assert loss.label == "ok"


def test_throwing_away_a_mate_is_a_blunder():
    loss = only([pos(2, mate=3), pos(3, 50)])

    assert loss.loss_cp == 950
    assert loss.label == "blunder"


def test_walking_into_mate_is_a_blunder_for_black():
    loss = only([pos(1, 0), pos(2, mate=2)])

    assert loss.mover == "black"
    assert loss.loss_cp == 1000
    assert loss.label == "blunder"


def test_the_checkmating_move_has_zero_loss():
    loss = only([pos(3, mate=-1), pos(4, checkmate=True)])

    assert loss.mover == "black"
    assert loss.loss_cp == 0
    assert loss.label == "ok"


def test_a_draw_ending_counts_as_zero_centipawns():
    loss = only([pos(2, 800), pos(3)])

    assert loss.loss_cp == 800
    assert loss.label == "blunder"


def test_one_loss_per_move_in_order():
    results = [pos(0, 0), pos(1, 0), pos(2, 0), pos(3, 0), pos(4, checkmate=True)]

    losses = move_losses(results)

    assert [m.ply for m in losses] == [1, 2, 3, 4]
    assert [m.mover for m in losses] == ["white", "black", "white", "black"]


def test_a_missing_evaluation_before_a_move_is_an_error():
    with pytest.raises(ValueError, match="ply 1"):
        move_losses([pos(0), pos(1, 0)])


# ---------- per-side summary ----------


def sample_losses():
    # White loses 300 (blunder), Black loses 0, White loses 120 (inaccuracy).
    return move_losses([pos(0, 0), pos(1, -300), pos(2, -300), pos(3, -420)])


def test_summary_for_the_side_with_two_moves():
    average, counts = summarize(sample_losses(), "white")

    assert average == 210.0
    assert dict(counts) == {"blunder": 1, "inaccuracy": 1}


def test_summary_for_the_other_side():
    average, counts = summarize(sample_losses(), "black")

    assert average == 0.0
    assert dict(counts) == {"ok": 1}


def test_summary_without_moves_has_no_average():
    average, counts = summarize([], "white")

    assert average is None
    assert not counts
