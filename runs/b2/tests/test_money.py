from decimal import Decimal
from fractions import Fraction

import pytest

from tally import money, split

D = Decimal


# R1.1 ---------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (3, "3.00"), (0, "0.00"), (-7, "-7.00"),
    ("3.5", "3.50"), ("-0.1", "-0.10"), (" 12.34 ", "12.34"),
    (D("3.25"), "3.25"), (D("1E+2"), "100.00"),
])
def test_money_accepts_int_str_decimal_with_two_places(value, expected):
    result = money(value)
    assert isinstance(result, Decimal)
    assert result == D(expected)
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize("value", [1.5, 0.0, True, False, None, [1], (1,), b"1", 1 + 2j])
def test_money_rejects_other_types(value):
    with pytest.raises(TypeError):
        money(value)


@pytest.mark.parametrize("value", [
    "abc", "", "  ", "1.2.3", "12abc", "nan", "NaN", "inf", "-Infinity",
    D("NaN"), D("Infinity"), D("-Infinity"),
])
def test_money_rejects_non_numbers_and_non_finite(value):
    with pytest.raises(ValueError):
        money(value)


# R1.2 ---------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("2.664", "2.66"), ("2.666", "2.67"), ("2.675", "2.68"), ("0.001", "0.00"),
    ("0.006", "0.01"), ("-2.666", "-2.67"), ("-2.664", "-2.66"), ("1.0049", "1.00"),
    ("1.0051", "1.01"), ("0.135", "0.14"), ("0.015", "0.02"), ("0.1451", "0.15"),
])
def test_money_rounds_to_the_nearest_cent(value, expected):
    assert money(value) == D(expected)


@pytest.mark.xfail(strict=True, reason="rounds half up instead of half to even")
@pytest.mark.parametrize("value, expected", [
    ("2.665", "2.66"), ("0.125", "0.12"), ("0.145", "0.14"), ("0.005", "0.00"),
    ("0.025", "0.02"), ("-2.665", "-2.66"), ("-0.125", "-0.12"),
])
def test_money_rounds_exact_halves_to_even(value, expected):
    assert money(value) == D(expected)


# R1.3 ---------------------------------------------------------------------

def reference_split(total, weights):
    """Independent statement of R1.3 in whole cents."""
    cents = int(abs(money(total)) * 100)
    weights = [Fraction(w) for w in weights]
    whole = sum(weights)
    exact = [cents * w / whole for w in weights]
    parts = [int(e) for e in exact]
    left = cents - sum(parts)
    order = sorted(range(len(parts)), key=lambda i: (-(exact[i] - parts[i]), i))
    for i in order[:left]:
        parts[i] += 1
    sign = -1 if money(total) < 0 else 1
    return [D(sign * p) / 100 for p in parts]


@pytest.mark.parametrize("total, weights, expected", [
    ("10.00", [1, 1], ["5.00", "5.00"]),
    ("100.00", [1, 1, 1], ["33.34", "33.33", "33.33"]),
    ("1.00", [1, 2], ["0.33", "0.67"]),
    ("0.05", [1, 1, 1], ["0.02", "0.02", "0.01"]),
    ("0.01", [2, 3, 5], ["0.00", "0.00", "0.01"]),
    ("0.07", [3, 1, 1], ["0.04", "0.02", "0.01"]),
    ("0.03", [1, 1, 2], ["0.01", "0.01", "0.01"]),
    ("0.01", [1, 1], ["0.01", "0.00"]),
    ("0.01", [1, 0, 1], ["0.01", "0.00", "0.00"]),
    ("5.00", [0, 1, 0], ["0.00", "5.00", "0.00"]),
    ("7.00", [3], ["7.00"]),
    ("0.00", [1, 2], ["0.00", "0.00"]),
    ("-100.00", [1, 1, 1], ["-33.34", "-33.33", "-33.33"]),
    ("-0.01", [1, 1], ["-0.01", "0.00"]),
])
def test_split_examples(total, weights, expected):
    assert split(total, weights) == [D(x) for x in expected]


@pytest.mark.parametrize("total", ["0.00", "0.01", "0.99", "1.00", "9.99", "100.00", "1234.56", "99999.99"])
@pytest.mark.parametrize("weights", [
    [1], [1, 1], [1, 1, 1], [1, 2, 3], [3, 1, 1], [0, 1, 0, 2], [7, 7, 7, 7, 7, 7, 7],
    [D("0.5"), D("1.5")], [10, 20, 30, 40], [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
])
def test_split_parts_add_up_and_match_the_rule(total, weights):
    parts = split(total, weights)
    assert len(parts) == len(weights)
    assert sum(parts) == money(total)
    assert parts == reference_split(total, weights)
    for part, weight in zip(parts, weights):
        if weight == 0:
            assert part == 0


@pytest.mark.parametrize("total", ["0.01", "3.33", "100.00", "1234.56"])
@pytest.mark.parametrize("weights", [[1, 1, 1], [2, 3, 5], [1, 0, 6], [5, 5]])
def test_split_negative_total_is_the_negated_positive_result(total, weights):
    positive = split(total, weights)
    assert split("-" + total, weights) == [-p for p in positive]
    assert sum(split("-" + total, weights)) == -money(total)


def test_split_accepts_int_and_decimal_totals():
    assert split(10, [1, 1]) == [D("5.00"), D("5.00")]
    assert split(D("0.03"), [1, 1, 1]) == [D("0.01")] * 3


@pytest.mark.xfail(strict=True, reason="split parts such as Decimal('5') have no cents")
def test_split_parts_have_two_places():
    parts = split("10.00", [1, 1]) + split("-30.00", [1, 1, 1]) + split("0.00", [1])
    assert all(p.as_tuple().exponent == -2 for p in parts)


# R1.4 ---------------------------------------------------------------------

@pytest.mark.parametrize("weights", [[], [0], [0, 0, 0], [-1, 2], [1, -1], [3, -0.5]])
def test_split_rejects_bad_weights(weights):
    with pytest.raises(ValueError):
        split("10.00", weights)


def test_split_still_validates_total():
    with pytest.raises(TypeError):
        split(1.5, [1])
    with pytest.raises(ValueError):
        split("abc", [1])
