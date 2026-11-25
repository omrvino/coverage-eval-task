from decimal import Decimal

import pytest

from tally import money, split


def test_money_accepts_int_str_decimal():
    assert money(3) == Decimal("3.00")
    assert money("3.5") == Decimal("3.50")
    assert money(Decimal("3.25")) == Decimal("3.25")


def test_money_rejects_float():
    with pytest.raises(TypeError):
        money(1.5)


def test_money_rejects_bool():
    with pytest.raises(TypeError):
        money(True)


def test_money_rejects_other_types():
    with pytest.raises(TypeError):
        money(None)
    with pytest.raises(TypeError):
        money(["1.00"])


def test_money_rejects_text_that_is_not_a_number():
    with pytest.raises(ValueError):
        money("twelve")


def test_money_rejects_infinity_and_nan():
    for value in ("Infinity", "NaN", Decimal("-Infinity")):
        with pytest.raises(ValueError):
            money(value)


def test_money_rounds_to_the_cent():
    assert money("2.665") == Decimal("2.67")
    assert money("2.675") == Decimal("2.68")


def test_split_even():
    assert split("10.00", [1, 1]) == [Decimal("5.00"), Decimal("5.00")]


def test_split_leftover_cent_goes_to_earliest_tie():
    parts = split("10.00", [1, 1, 1])
    assert parts == [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]
    assert sum(parts) == Decimal("10.00")


def test_split_leftover_cent_goes_to_largest_remainder():
    assert split("0.10", [1, 2]) == [Decimal("0.03"), Decimal("0.07")]


def test_split_zero_weight_gets_zero():
    assert split("10.00", [0, 1]) == [Decimal("0.00"), Decimal("10.00")]


def test_split_negative_total_negates_the_positive_result():
    assert split("-10.00", [1, 1]) == [Decimal("-5.00"), Decimal("-5.00")]
    assert split("-10.00", [1, 2]) == [Decimal("-3.33"), Decimal("-6.67")]


def test_split_rejects_bad_weights():
    with pytest.raises(ValueError):
        split("10.00", [1, -1])
    with pytest.raises(ValueError):
        split("10.00", [0, 0])
    with pytest.raises(ValueError):
        split("10.00", [])
