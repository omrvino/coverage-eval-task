"""SPEC section 1: money."""

from decimal import Decimal
from fractions import Fraction

import pytest

from helpers import DUE, JAN_5, D, days, issued, make_invoice
from tally import Line, money, split

# -- R1.1 ------------------------------------------------------------------


@pytest.mark.parametrize("value, expected", [
    (3, "3.00"),
    (0, "0.00"),
    (-7, "-7.00"),
    ("3.5", "3.50"),
    ("-0.25", "-0.25"),
    ("1234567.89", "1234567.89"),
    (D("3.25"), "3.25"),
    (D("3"), "3.00"),
])
def test_r1_1_accepts_int_str_and_decimal(value, expected):
    result = money(value)
    assert isinstance(result, Decimal)
    assert str(result) == expected  # always two places


@pytest.mark.parametrize("value", [
    1.5, 2.0, float("nan"), True, False, None, b"1", [1], (1,), Fraction(1, 2), 1 + 0j, object,
], ids=repr)
def test_r1_1_other_types_are_type_errors(value):
    with pytest.raises(TypeError):
        money(value)


@pytest.mark.parametrize("value", [
    "", "abc", "1,000", "$5", "1.2.3", "--1", "NaN", "sNaN", "inf", "Infinity", "-Infinity",
    D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"),
], ids=repr)
def test_r1_1_non_numbers_are_value_errors(value):
    with pytest.raises(ValueError):
        money(value)


# -- R1.2 ------------------------------------------------------------------


@pytest.mark.parametrize("value, expected", [
    ("2.675", "2.68"),  # a tie whose even neighbour is above
    ("-2.675", "-2.68"),
    ("0.015", "0.02"),
    ("2.664", "2.66"),
    ("2.6649999", "2.66"),
    ("2.6650001", "2.67"),
    ("2.666", "2.67"),
    ("-2.664", "-2.66"),
    ("-2.666", "-2.67"),
    ("0.999", "1.00"),
])
def test_r1_2_rounds_to_the_nearest_cent(value, expected):
    assert money(value) == D(expected)
    assert money(D(value)) == D(expected)


R1_2 = pytest.mark.xfail(strict=True, reason="R1.2: ties round half up instead of half to even")


@R1_2
@pytest.mark.parametrize("value, expected", [
    ("2.665", "2.66"), ("-2.665", "-2.66"), ("0.005", "0.00"), ("0.125", "0.12"),
])
def test_r1_2_ties_go_to_the_even_cent_below(value, expected):
    assert money(value) == D(expected)


@R1_2
def test_r1_2_applies_to_line_nets():
    assert Line("half a nickel", "0.5", "0.05").net == D("0.02")


@R1_2
def test_r1_2_applies_to_tax():
    assert make_invoice(price="0.50", tax_rate="5").tax == D("0.02")


@R1_2
def test_r1_2_applies_to_early_payment_discounts():
    ledger = issued(make_invoice(price="4.50", terms="1/10 NET 30"))
    ledger.receive("P1", "acme", "4.50", JAN_5)  # 1 percent is 0.045
    assert ledger.credit("acme") == D("0.04")


@R1_2
def test_r1_2_applies_to_late_fees():
    ledger = issued(make_invoice(price="343.00"))
    ledger.assess_late_fees(DUE + days(10))  # 1.5 percent is 5.145
    assert ledger.invoices["INV-1"].fees_due == D("5.14")


# -- R1.3 ------------------------------------------------------------------


@pytest.mark.parametrize("total, weights, expected", [
    ("10.00", [1, 1], ["5.00", "5.00"]),
    ("10.00", [1], ["10.00"]),
    ("10.00", [1, 1, 1], ["3.34", "3.33", "3.33"]),  # tie: earliest position
    ("0.05", [1, 1, 1], ["0.02", "0.02", "0.01"]),  # two leftover cents
    ("0.02", [1, 1, 1], ["0.01", "0.01", "0.00"]),
    ("1.00", [1, 2, 4], ["0.14", "0.29", "0.57"]),  # remainders .29 .57 .14
    ("1.00", [4, 2, 1], ["0.57", "0.29", "0.14"]),
    ("0.10", [1, 1, 4], ["0.02", "0.02", "0.06"]),  # remainders .67 .67 .67
    ("0.10", [4, 1, 1], ["0.07", "0.02", "0.01"]),
    ("0.01", [1, 2], ["0.00", "0.01"]),  # largest remainder, not first
    ("0.01", [1, 1000, 1], ["0.00", "0.01", "0.00"]),
    ("100.00", [30, 70], ["30.00", "70.00"]),
    ("0.00", [1, 2], ["0.00", "0.00"]),
    (7, [1, 1], ["3.50", "3.50"]),
    (D("0.03"), [D("0.5"), D("0.5")], ["0.02", "0.01"]),
])
def test_r1_3_largest_remainder_split(total, weights, expected):
    assert split(total, weights) == [D(x) for x in expected]


@pytest.mark.parametrize("total, weights", [
    ("10.00", [1, 1, 1]), ("1.00", [1, 2, 4]), ("0.05", [1, 1, 1]), ("0.01", [1, 2]),
    ("99.99", [3, 0, 5, 7]),
])
def test_r1_3_negative_total_is_the_negated_positive_split(total, weights):
    assert split("-" + total, weights) == [-part for part in split(total, weights)]


def test_r1_3_negative_tie_goes_to_the_earlier_position():
    assert split("-10.00", [1, 1, 1]) == [D("-3.34"), D("-3.33"), D("-3.33")]


@pytest.mark.parametrize("total", ["0.01", "1.00", "99.99", "1000.01", "10.005", "-33.34", 17])
@pytest.mark.parametrize("weights", [
    [1], [1, 1, 1], [1, 2, 3, 4, 5, 6, 7], [0, 1, 0, 2], [D("0.1"), D("0.2"), D("0.3")],
    list(range(1, 60)),
], ids=lambda w: f"{len(w)} weights" if isinstance(w, list) else repr(w))
def test_r1_3_parts_add_up_exactly_and_stay_within_a_cent(total, weights):
    parts = split(total, weights)
    assert len(parts) == len(weights)
    assert sum(parts) == money(total)
    for part, weight in zip(parts, weights):
        exact = Fraction(money(total)) * Fraction(weight) / sum(map(Fraction, weights))
        assert isinstance(part, Decimal)
        assert abs(Fraction(part) - exact) < Fraction(1, 100)
        assert part == money(part)  # whole cents


# -- R1.4 ------------------------------------------------------------------


@pytest.mark.parametrize("weights", [
    [], [0], [0, 0], [-1], [2, -1], [1, -1], [-1, -2],
], ids=repr)
def test_r1_4_unusable_weights(weights):
    with pytest.raises(ValueError):
        split("10.00", weights)


@pytest.mark.parametrize("total", ["0.01", "0.02", "10.00", "0.05", "-0.05"])
def test_r1_4_zero_weight_receives_zero(total):
    parts = split(total, [0, 1, 0, 1, 1, 0])
    assert [parts[0], parts[2], parts[5]] == [0, 0, 0]
    assert sum(parts) == D(total)
