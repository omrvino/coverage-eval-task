from decimal import Decimal

import pytest

from tally import money, split


@pytest.mark.parametrize("value", [None, [1], object()])
def test_money_rejects_other_types(value):
    with pytest.raises(TypeError):
        money(value)


def test_money_rejects_bool():
    with pytest.raises(TypeError):
        money(True)


@pytest.mark.parametrize("text", ["abc", "", "1e", "inf", "-Infinity", "NaN"])
def test_money_rejects_text_that_is_not_a_finite_number(text):
    with pytest.raises(ValueError):
        money(text)


def test_money_rejects_decimal_nan():
    with pytest.raises(ValueError):
        money(Decimal("NaN"))


@pytest.mark.xfail(strict=True, reason="R1.2 says half to even; money() rounds half up")
def test_money_rounds_half_to_even():
    assert money("2.665") == Decimal("2.66")
    assert money("2.675") == Decimal("2.68")


def test_split_gives_leftover_cents_to_largest_remainders_then_earlier_positions():
    assert split("10.00", [1, 1, 1]) == [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]
    assert split("10.00", [1, 2]) == [Decimal("3.33"), Decimal("6.67")]


def test_split_always_adds_up_to_the_total():
    parts = split("100.00", [1, 1, 1, 1, 1, 1, 1])
    assert sum(parts) == Decimal("100.00")
    assert all(part in (Decimal("14.28"), Decimal("14.29")) for part in parts)


def test_split_negative_total_gives_negated_parts():
    assert split("-10.00", [1, 2]) == [Decimal("-3.33"), Decimal("-6.67")]


def test_split_zero_weight_receives_nothing():
    assert split("10.00", [0, 1, 1]) == [Decimal("0.00"), Decimal("5.00"), Decimal("5.00")]
    assert split("0.02", [1, 1, 0]) == [Decimal("0.01"), Decimal("0.01"), Decimal("0.00")]


@pytest.mark.parametrize("weights", [[1, -1], [0, 0], []])
def test_split_rejects_negative_all_zero_or_empty_weights(weights):
    with pytest.raises(ValueError):
        split("10.00", weights)
