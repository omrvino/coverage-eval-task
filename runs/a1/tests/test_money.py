from decimal import Decimal
from fractions import Fraction

import pytest

from tally import money, split

D = Decimal

XFAIL_HALF_TO_EVEN = pytest.mark.xfail(
    strict=True,
    reason="R1.2: money() rounds ties half up (2.665 gives 2.67); the spec says half to even (2.66)",
)


def test_money_accepts_int_str_and_decimal():
    assert str(money(3)) == "3.00"
    assert str(money("3.5")) == "3.50"
    assert str(money(D("3.25"))) == "3.25"
    assert str(money("-7")) == "-7.00"


@pytest.mark.parametrize("value", [1.5, 0.0, True, False, None, [1], {"a": 1}])
def test_money_rejects_other_types(value):
    with pytest.raises(TypeError):
        money(value)


@pytest.mark.parametrize(
    "value",
    ["abc", "", "12 dollars", "1,000", "inf", "-Infinity", "NaN", "sNaN", D("NaN"), D("Infinity")],
)
def test_money_rejects_text_that_is_not_a_finite_number(value):
    with pytest.raises(ValueError):
        money(value)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2.6649", "2.66"),
        ("2.6651", "2.67"),
        ("2.675", "2.68"),
        pytest.param("2.665", "2.66", marks=XFAIL_HALF_TO_EVEN, id="tie-2.665"),
        pytest.param("2.645", "2.64", marks=XFAIL_HALF_TO_EVEN, id="tie-2.645"),
    ],
)
def test_money_rounds_to_the_cent(text, expected):
    assert str(money(text)) == expected


def test_split_gives_leftover_cents_to_the_largest_remainders():
    assert split("10.00", [1, 2, 3]) == [D("1.67"), D("3.33"), D("5.00")]
    assert split("0.05", [2, 1]) == [D("0.03"), D("0.02")]


def test_split_ties_go_to_the_earlier_position():
    assert split("10.00", [1, 1, 1]) == [D("3.34"), D("3.33"), D("3.33")]
    assert split("0.04", [1, 1, 1]) == [D("0.02"), D("0.01"), D("0.01")]


def test_split_zero_weight_always_receives_zero():
    assert split("10.00", [0, 1, 1]) == [D("0"), D("5.00"), D("5.00")]
    assert split("0.02", [0, 1, 1, 1]) == [D("0"), D("0.01"), D("0.01"), D("0")]


def test_split_negative_total_gives_the_negated_parts():
    assert split("-10.00", [1, 2, 3]) == [D("-1.67"), D("-3.33"), D("-5.00")]
    assert split("-10.00", [1, 1]) == [D("-5.00"), D("-5.00")]


@pytest.mark.parametrize("total", ["0.00", "0.01", "0.99", "10.00", "1234.56", "-0.03", "-999.99"])
@pytest.mark.parametrize(
    "weights", [[1], [1, 1, 1], [3, 1, 7, 0, 2], [1, 2, 3, 4, 5, 6, 7], [0.5, 0.25, 0.25]]
)
def test_split_parts_add_up_exactly_and_stay_within_a_cent_of_their_share(total, weights):
    parts = split(total, weights)
    assert len(parts) == len(weights)
    assert sum(parts, D(0)) == money(total)
    share_sum = sum(Fraction(w) for w in weights)
    for part, weight in zip(parts, weights):
        exact = Fraction(total) * Fraction(weight) / share_sum
        assert abs(Fraction(part) - exact) < Fraction(1, 100)
        if weight == 0:
            assert part == 0


@pytest.mark.parametrize("weights", [[], [0], [0, 0], [1, -1], [-2]])
def test_split_refuses_negative_or_all_zero_weights(weights):
    with pytest.raises(ValueError):
        split("10.00", weights)
