"""SPEC section 1: money."""

from decimal import Decimal
from fractions import Fraction

import pytest

from tally import money, split

D = Decimal


def test_money_accepts_int_str_decimal():
    assert money(3) == D("3.00")
    assert money("3.5") == D("3.50")
    assert money(D("3.25")) == D("3.25")
    assert money(0) == D("0.00")
    assert money("-3.5") == D("-3.50")


@pytest.mark.parametrize("value", [3, "3", D("3"), "3.1", "3.14159", 0, -7])
def test_money_is_a_decimal_with_two_places(value):
    result = money(value)
    assert isinstance(result, Decimal)
    assert result.as_tuple().exponent == -2


def test_money_rejects_float():
    with pytest.raises(TypeError):
        money(1.5)


@pytest.mark.parametrize(
    "value", [1.0, float("nan"), True, False, None, b"1", [1], (1,), Fraction(1, 2), 1 + 0j],
    ids=repr,
)
def test_money_rejects_other_types(value):
    with pytest.raises(TypeError):
        money(value)


@pytest.mark.parametrize("value", ["", "abc", "1.2.3", "$5", "1,000", "12x", "--1"])
def test_money_rejects_text_that_is_not_a_number(value):
    with pytest.raises(ValueError):
        money(value)


@pytest.mark.parametrize("text", ["Infinity", "-Infinity", "inf", "NaN", "-NaN", "sNaN"])
def test_money_rejects_infinities_and_nan(text):
    with pytest.raises(ValueError):
        money(text)
    with pytest.raises(ValueError):
        money(Decimal(text))


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2.664", "2.66"), ("2.666", "2.67"), ("2.6649999", "2.66"), ("2.6650001", "2.67"),
        ("-2.664", "-2.66"), ("-2.666", "-2.67"), ("0.999", "1.00"), ("0.004", "0.00"),
    ],
)
def test_money_rounds_to_the_nearest_cent(value, expected):
    assert money(value) == D(expected)
    assert money(D(value)) == D(expected)


@pytest.mark.parametrize(
    "value, expected", [("2.675", "2.68"), ("0.015", "0.02"), ("-2.675", "-2.68")]
)
def test_money_rounds_half_up_to_an_even_cent(value, expected):
    assert money(value) == D(expected)


@pytest.mark.xfail(strict=True, reason="R1.2: ties round away from zero instead of half to even")
@pytest.mark.parametrize(
    "value, expected",
    [("2.665", "2.66"), ("0.005", "0.00"), ("0.125", "0.12"), ("-2.665", "-2.66")],
)
def test_money_rounds_half_down_to_an_even_cent(value, expected):
    assert money(value) == D(expected)


# -- split --------------------------------------------------------------------


@pytest.mark.parametrize(
    "total, weights, expected",
    [
        ("10.00", [1, 1], ["5.00", "5.00"]),
        ("10.00", [1], ["10.00"]),
        ("10.00", [3, 1], ["7.50", "2.50"]),
        ("10.00", [D("0.5"), D("1.5")], ["2.50", "7.50"]),
        (9, [1, 2], ["3.00", "6.00"]),
        ("0.00", [1, 2], ["0.00", "0.00"]),
    ],
)
def test_split_exact_shares(total, weights, expected):
    parts = split(total, weights)
    assert parts == [D(e) for e in expected]
    assert all(isinstance(part, Decimal) for part in parts)


@pytest.mark.parametrize(
    "total, weights, expected",
    [
        # Equal remainders: the earlier position gets the cent.
        ("10.00", [1, 1, 1], ["3.34", "3.33", "3.33"]),
        ("0.02", [1, 1, 1], ["0.01", "0.01", "0.00"]),
        ("0.05", [1, 1, 1, 1], ["0.02", "0.01", "0.01", "0.01"]),
        # Exact cents 14.28, 28.57, 57.14: the middle remainder is largest.
        ("1.00", [1, 2, 4], ["0.14", "0.29", "0.57"]),
        # Exact cents 16.67, 33.33, 50: the first remainder is largest.
        ("1.00", [1, 2, 3], ["0.17", "0.33", "0.50"]),
        # Exact cents 33.33, 16.67, 50: largest remainder, not largest part.
        ("1.00", [2, 1, 3], ["0.33", "0.17", "0.50"]),
        # Exact cents 0.6, 0.6, 1.8: the last part, then the first of the tie.
        ("0.03", [1, 1, 3], ["0.01", "0.00", "0.02"]),
    ],
)
def test_split_gives_leftover_cents_to_the_largest_remainders(total, weights, expected):
    assert split(total, weights) == [D(e) for e in expected]


@pytest.mark.parametrize(
    "total", ["0.01", "0.07", "1.00", "99.99", "100.00", "1234.57", "-0.07", "-99.99"]
)
@pytest.mark.parametrize(
    "weights", [[1, 1, 1], [7, 11, 13, 17], [0, 1, 0, 2], [D("0.1"), D("0.2"), D("0.4")], [1] * 12]
)
def test_split_parts_add_up_and_are_whole_cents(total, weights):
    parts = split(total, weights)
    assert len(parts) == len(weights)
    assert sum(parts) == D(total)
    assert all(part == part.quantize(D("0.01")) for part in parts)


def test_split_rounds_the_total_first():
    assert split("10.004", [1, 1]) == [D("5.00"), D("5.00")]
    assert sum(split("10.006", [1, 1, 1])) == D("10.01")


@pytest.mark.parametrize("weights", [[1, 1, 1], [1, 2, 4], [2, 1, 3], [0, 5, 7]])
def test_split_of_a_negative_total_is_the_negated_result(weights):
    for total in ("10.00", "1.00", "0.02", "7.77"):
        assert split("-" + total, weights) == [-part for part in split(total, weights)]


@pytest.mark.parametrize("weights", [[1, -1], [-1], [-1, 2], [5, 5, -1], [-1, -1]])
def test_split_rejects_negative_weights(weights):
    with pytest.raises(ValueError):
        split("10.00", weights)


@pytest.mark.parametrize("weights", [[], [0], [0, 0, 0]])
def test_split_rejects_empty_and_all_zero_weights(weights):
    with pytest.raises(ValueError):
        split("10.00", weights)


def test_split_zero_weight_always_receives_zero():
    assert split("0.05", [0, 1, 1, 0, 1]) == [D("0"), D("0.02"), D("0.02"), D("0"), D("0.01")]
    assert split("-0.01", [0, 3]) == [D("0"), D("-0.01")]


def test_split_total_follows_the_money_type_rules():
    with pytest.raises(TypeError):
        split(10.0, [1, 1])
    with pytest.raises(ValueError):
        split("ten", [1, 1])
