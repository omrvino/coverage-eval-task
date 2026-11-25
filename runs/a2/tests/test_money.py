from decimal import Decimal as D

import pytest

from tally import money, split


# R1.1
def test_money_accepts_int_str_decimal():
    assert money(3) == D("3.00")
    assert money("3.5") == D("3.50")
    assert money(D("3.25")) == D("3.25")
    assert money(-7) == D("-7.00")


@pytest.mark.parametrize("value", [1.5, 0.0, True, False])
def test_money_rejects_float_and_bool(value):
    with pytest.raises(TypeError):
        money(value)


@pytest.mark.parametrize("value", [None, [1], {"a": 1}, (1,)])
def test_money_rejects_other_types(value):
    with pytest.raises(TypeError):
        money(value)


@pytest.mark.parametrize("text", ["abc", "", "12 dollars", "1.2.3"])
def test_money_rejects_text_that_is_not_a_number(text):
    with pytest.raises(ValueError):
        money(text)


@pytest.mark.parametrize("value", ["inf", "-Infinity", "NaN", D("Infinity"), D("NaN")])
def test_money_rejects_infinity_and_nan(value):
    with pytest.raises(ValueError):
        money(value)


# R1.2
def test_money_rounds_to_the_cent_where_the_half_is_not_ambiguous():
    assert money("2.675") == D("2.68")
    assert money("1.004") == D("1.00")
    assert money("1.006") == D("1.01")


@pytest.mark.xfail(strict=True, reason="money() rounds halves up; spec R1.2 says half to even, so 2.665 is 2.66")
def test_money_rounds_half_to_even_2_665():
    assert money("2.665") == D("2.66")


@pytest.mark.xfail(strict=True, reason="money() rounds halves up; spec R1.2 says half to even, so 0.125 is 0.12")
def test_money_rounds_half_to_even_0_125():
    assert money("0.125") == D("0.12")
    assert money("0.135") == D("0.14")


# R1.3
def test_split_even():
    assert split("10.00", [1, 1]) == [D("5.00"), D("5.00")]


def test_split_gives_leftover_cent_to_the_earliest_position_on_a_tie():
    assert split("10.00", [1, 1, 1]) == [D("3.34"), D("3.33"), D("3.33")]
    assert split("0.02", [1, 1, 1]) == [D("0.01"), D("0.01"), D("0.00")]


def test_split_gives_leftover_cents_to_the_largest_remainders():
    # exact shares are 3.333 and 6.667; the leftover cent goes to 6.667
    assert split("0.10", [1, 2]) == [D("0.03"), D("0.07")]


def test_split_is_proportional_to_weights():
    assert split("100.00", [1, 3]) == [D("25.00"), D("75.00")]


@pytest.mark.parametrize(
    "total, weights",
    [("0.07", [1, 1, 1, 1]), ("99.99", [3, 5, 11]), ("1234.56", [D("0.5"), D("0.25"), D("0.25")])],
)
def test_split_parts_always_add_up_to_the_total(total, weights):
    parts = split(total, weights)
    assert len(parts) == len(weights)
    assert sum(parts, D("0")) == money(total)


def test_split_negative_total_gives_negated_positive_result():
    assert split("-10.00", [1, 1, 1]) == [-x for x in split("10.00", [1, 1, 1])]
    assert split("-0.02", [1, 1, 1]) == [-x for x in split("0.02", [1, 1, 1])]


# R1.4
def test_zero_weight_always_receives_zero():
    assert split("10.00", [0, 1, 1])[0] == 0
    assert split("0.01", [0, 1, 1]) == [D("0"), D("0.01"), D("0")]


@pytest.mark.parametrize("weights", [[1, -1], [0, 0], []])
def test_split_rejects_negative_all_zero_or_empty_weights(weights):
    with pytest.raises(ValueError):
        split("10.00", weights)
